"""One background worker. The GPU runs one analysis at a time (OLLAMA_NUM_PARALLEL=1 on purpose)."""

from __future__ import annotations

import logging
import queue
import threading
import time

from .adapters import AdapterError, InferenceAdapter
from .detail import run_detail_pass
from .intake import IntakeError, IntakeLimits, prepare_image
from .repeats import find_repeats
from .pipeline import AnalysisFailed, DEFAULT_MAX_TOKENS, run_overview
from .tiles import run_overview_tiled
from .store import Store

log = logging.getLogger("visionguard.jobs")


class JobRunner:
    def __init__(self, store: Store, adapter: InferenceAdapter, limits: IntakeLimits, max_tokens: int = DEFAULT_MAX_TOKENS, detail_pass: bool = True, tile_grid=None, sampling: dict | None = None, repeats: bool = False, repeat_threshold: float = 0.75):
        self.store = store
        self.adapter = adapter
        self.limits = limits
        self.max_tokens = max_tokens
        self.detail_pass = detail_pass
        self.tile_grid = tile_grid
        self.sampling = sampling or {}
        self.repeats = repeats
        self.repeat_threshold = repeat_threshold
        self._q: "queue.Queue[str | None]" = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="visionguard-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._q.put(None)
        self._thread.join(timeout=5)

    def submit(self, analysis_id: str) -> None:
        self._q.put(analysis_id)

    def _loop(self) -> None:
        while True:
            job = self._q.get()
            if job is None:
                return
            try:
                self._run(job)
            except Exception:  # never let the worker die
                log.exception("job %s crashed", job)
                self.store.set_status(
                    job,
                    "failed",
                    only_if=("queued", "running"),
                    error={"code": "internal", "message": "The analysis stopped unexpectedly. The server log has details."},
                    finished=time.time(),
                )

    def _fail(self, job: str, code: str, message: str, raw: str | None = None) -> None:
        fields = {"error": {"code": code, "message": message}, "finished": time.time()}
        if raw is not None:
            fields["raw_text"] = raw
        self.store.set_status(job, "failed", only_if=("running",), **fields)

    def _run(self, job: str) -> None:
        # Compare-and-set: a job cancelled while it waited in the queue is skipped.
        if not self.store.set_status(job, "running", only_if=("queued",), started=time.time()):
            return
        analysis = self.store.get_analysis(job)
        image = self.store.get_image(analysis["image_id"]) if analysis else None
        if not analysis or not image:
            self._fail(job, "missing_image", "The photo for this analysis is no longer stored. Upload it again.")
            return
        try:
            prepared = prepare_image(self.store.read_image_bytes(image), self.limits)
            if self.tile_grid:
                result = run_overview_tiled(
                    prepared, self.adapter, image_id=image["id"], grid=self.tile_grid, max_tokens=self.max_tokens,
                    sampling=self.sampling, should_stop=lambda: (self.store.get_analysis(job) or {}).get("status") != "running",
                )
            else:
                result = run_overview(prepared, self.adapter, image_id=image["id"], max_tokens=self.max_tokens, sampling=self.sampling)
        except AnalysisFailed as exc:
            self._fail(job, "model_output_invalid", exc.detail, raw="\n---\n".join(exc.attempts))
            return
        except AdapterError as exc:
            self._fail(job, exc.code, exc.message)
            return
        except IntakeError as exc:
            self._fail(job, exc.code, exc.message)
            return

        # Observation ids must be unique across analyses; the shared prefix keeps their order.
        observations = [o.model_copy(update={"id": f"{job}_{i:03d}"}) for i, o in enumerate(result.observations)]
        # Overview results are saved first, so a problem in the close-up pass cannot lose them.
        self.store.save_observations(job, observations)
        detail_summary = None
        if self.detail_pass:
            observations, detail_summary = run_detail_pass(
                prepared,
                self.adapter,
                observations,
                should_stop=lambda: (self.store.get_analysis(job) or {}).get("status") != "running",
            )
            self.store.save_observations(job, observations)
        repeat_summary = None
        if self.repeats:
            # Look-alike search, no model call. Failure here must not lose the model's results.
            try:
                found, repeat_summary = find_repeats(prepared, observations, threshold=self.repeat_threshold, id_prefix=f"{job}_r")
                if found:
                    observations = observations + found
                    self.store.save_observations(job, observations)
            except Exception:  # noqa: BLE001
                log.exception("repeat pass failed for %s", job)
                repeat_summary = {"error": "The look-alike search failed; the model's results are unchanged."}
        meta = {
            "model": result.model,
            "adapter": result.adapter,
            "is_mock": result.is_mock,
            "latency_s": result.latency_s,
            "load_s": result.load_s,
            "attempts": result.attempts,
            "dropped": result.dropped,
            "coordinate_conventions": sorted(result.conventions),
            "detail_pass": detail_summary,
            "repeat_pass": repeat_summary,
            "warnings": result.warnings,
            "tiles": result.tiles,
        }
        if not self.store.set_status(job, "done", only_if=("running",), meta=meta, raw_text=result.raw_text, finished=time.time()):
            # Cancelled while the model was running: discard the result.
            self.store.save_observations(job, [])
