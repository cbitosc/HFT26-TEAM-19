#!/usr/bin/env python3
"""Minimal REAL image-inference smoke test. Run this first on the target laptop.

    python scripts/smoke_vlm.py path/to/board.jpg --model huihui_ai/qwen3-vl-abliterated:4b-instruct
    python scripts/smoke_vlm.py path/to/board.jpg --model qwen3-vl:4b-instruct
    python scripts/smoke_vlm.py samples/ref_labelled.jpg --tiles 3x2 --detail --truth samples/ref_labelled.truth.json

Outputs (next to --out, default ./smoke_out): raw model text, parsed observations (JSON),
the image with boxes drawn, and a metrics JSON (load time, latency, peak VRAM if nvidia-smi
exists). Exit code 1 if the model is unreachable or returns nothing usable. Add --mock to
exercise the plumbing without a model; mock output is labelled MOCK in every file.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from PIL import ImageDraw  # noqa: E402

from app.adapters import AdapterError, MockAdapter, OllamaAdapter  # noqa: E402
from app.intake import IntakeError, prepare_image  # noqa: E402
from app.detail import run_detail_pass  # noqa: E402
from app.repeats import find_repeats  # noqa: E402
from app.evaluation import score  # noqa: E402
from app.pipeline import DEFAULT_MAX_TOKENS, AnalysisFailed, run_overview  # noqa: E402
from app.tiles import parse_grid, run_overview_tiled  # noqa: E402


class VramSampler:
    """Polls nvidia-smi for peak used memory. Returns None if no NVIDIA tooling."""

    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self.peak_mib: int | None = None
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)
        self.available = shutil.which("nvidia-smi") is not None

    def _read(self) -> int | None:
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout.strip().splitlines()
            return max(int(x) for x in out) if out else None
        except Exception:
            return None

    def _run(self):
        while not self._stop.is_set():
            v = self._read()
            if v is not None:
                self.peak_mib = v if self.peak_mib is None else max(self.peak_mib, v)
            self._stop.wait(self.interval)

    def __enter__(self):
        if self.available:
            self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self.available:
            self._t.join(timeout=2)


def run_smoke(image_path, adapter, out, *, grid=None, sampling=None, max_tokens=DEFAULT_MAX_TOKENS, truth=None, quiet=False, detail=False, repeats=False, repeat_threshold=0.75) -> dict:
    """One analysis of one image. Writes raw.txt, observations.json, boxes.jpg and metrics.json into ``out``.
    Returns the metrics dict, or raises IntakeError / AdapterError / AnalysisFailed."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    prepared = prepare_image(Path(image_path).read_bytes())
    if not quiet:
        print(f"Image {prepared.size[0]}x{prepared.size[1]} (EXIF orientation {prepared.exif_orientation}); "
              f"analysis view {prepared.analysis_view.width}x{prepared.analysis_view.height}")
        if not prepared.quality.ok:
            print("Quality warnings:", *prepared.quality.problems, sep="\n  - ")

    t0 = time.perf_counter()
    with VramSampler() as vram:
        if grid:
            res = run_overview_tiled(prepared, adapter, image_id="smoke", grid=grid, max_tokens=max_tokens, sampling=sampling)
        else:
            res = run_overview(prepared, adapter, image_id="smoke", max_tokens=max_tokens, sampling=sampling)
        observations, detail_summary = res.observations, None
        if detail:  # the close-up pass is where chip markings are read
            observations, detail_summary = run_detail_pass(prepared, adapter, res.observations)
    repeat_summary = None
    if repeats:  # look-alike search, no model call
        found, repeat_summary = find_repeats(prepared, observations, threshold=repeat_threshold, id_prefix="rep")
        observations = list(observations) + found
    wall = time.perf_counter() - t0

    (out / "raw.txt").write_text(res.raw_text)
    (out / "observations.json").write_text(json.dumps([o.model_dump(mode="json") for o in res.observations], indent=2))
    if detail:
        (out / "observations_after_closeups.json").write_text(json.dumps([o.model_dump(mode="json") for o in observations], indent=2))
    if repeats:
        (out / "observations_after_repeats.json").write_text(json.dumps([o.model_dump(mode="json") for o in observations], indent=2))
    img = prepared.original.copy()
    d = ImageDraw.Draw(img)
    lw = max(2, img.size[0] // 400)
    for o in observations:
        d.rectangle(o.bbox, outline=(64, 160, 255) if o.source.value == "assist" else (255, 64, 64), width=lw)
        d.text((o.bbox[0] + 3, o.bbox[1] + 3), f"{o.id} {o.category.value}", fill=(255, 255, 0))
    img.save(out / "boxes.jpg", quality=90)

    metrics = {
        "model": res.model,
        "adapter": res.adapter,
        "MOCK": res.is_mock,
        "sampling": sampling or "defaults",
        "max_tokens": max_tokens,
        "tiles": res.tiles,
        "attempts": res.attempts,
        "observations": len(observations),
        "detail_pass": detail_summary,
        "repeat_pass": repeat_summary,
        "reply_cut_off": res.truncated,
        "warnings": res.warnings,
        "dropped": res.dropped,
        "coordinate_conventions_seen": sorted(res.conventions),
        "model_latency_s": res.latency_s,
        "load_s": res.load_s,
        "wall_s": round(wall, 3),
        "peak_vram_mib": vram.peak_mib if vram.available else None,
        "vram_note": "peak of nvidia-smi samples every 0.5 s; whole-GPU, includes other processes",
    }
    if truth:
        metrics["score"] = score(json.loads(Path(truth).read_text()), [o.model_dump(mode="json") for o in observations]).summary()
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--model", default="huihui_ai/qwen3-vl-abliterated:4b-instruct")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--out", default="smoke_out")
    ap.add_argument("--mock", action="store_true", help="use the labelled MOCK adapter (no model)")
    ap.add_argument("--tiles", default="off", help="also analyse overlapping sections: off, 2x2, 3x2 ...")
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    ap.add_argument("--temperature", type=float)
    ap.add_argument("--top-p", type=float)
    ap.add_argument("--top-k", type=int)
    ap.add_argument("--presence-penalty", type=float)
    ap.add_argument("--truth", help="score against a samples/*.truth.json file")
    ap.add_argument("--detail", action="store_true", help="also run the close-up pass (reads chip markings; slower)")
    args = ap.parse_args()

    sampling = {k: v for k, v in {"temperature": args.temperature, "top_p": args.top_p, "top_k": args.top_k,
                                  "presence_penalty": args.presence_penalty}.items() if v is not None}
    try:
        grid = parse_grid(args.tiles)
    except ValueError as exc:
        print(exc)
        return 2

    adapter = MockAdapter() if args.mock else OllamaAdapter(args.model, host=args.host, num_ctx=args.num_ctx)
    if not args.mock:
        print("Health:", json.dumps(adapter.health(), indent=2))
    try:
        metrics = run_smoke(args.image, adapter, args.out, grid=grid, sampling=sampling, max_tokens=args.max_tokens, truth=args.truth, detail=args.detail)
    except IntakeError as exc:
        print(f"Image rejected [{exc.code}]: {exc.message}")
        return 1
    except AdapterError as exc:
        print(f"Model error [{exc.code}]: {exc.message}")
        return 1
    except AnalysisFailed as exc:
        print(exc.detail)
        for a in exc.attempts:
            print("  ", a)
        return 1

    print(json.dumps(metrics, indent=2))
    if metrics["reply_cut_off"]:
        print("\nNOTE: the model's reply was cut off at the token limit. Raise --max-tokens or check raw.txt for a loop.")
    print(f"\nWrote {args.out}/boxes.jpg - open it and check that boxes sit on the right parts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
