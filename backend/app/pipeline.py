"""Overview analysis: prepared image -> validated observations (original px).

One pass = one model call (plus bounded repair retries) on one image the model is shown. The overview
shows the whole photo downsized. ``tiles.py`` runs the same pass on higher-resolution sections.
Reference matching is added later behind the same interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from PIL import Image

from . import prompts
from .adapters.base import InferenceAdapter, InferenceRequest, InferenceResult
from .geometry import ImageView
from .guards import drop_blank_boxes, drop_repeated_boxes, drop_repetition_runs, merge_same_chip
from .intake import PreparedImage, encode_jpeg
from .parsing import RUNAWAY_TEXT, ModelOutputError, ParseResult, parse_detections, repair_prompt
from .schemas import RAW_DETECTIONS_SCHEMA, Observation

MAX_REPAIR_RETRIES = 2
DEFAULT_MAX_TOKENS = 2048  # the prompt allows 25 items, which needs well over 1024 tokens

TRUNCATED_WARNING = (
    "The model's reply was cut off at the length limit, so parts after the cut are missing."
)


class AnalysisFailed(RuntimeError):
    """Visible failure after bounded retries. Never replaced with plausible detections."""

    def __init__(self, detail: str, attempts: list[str]):
        super().__init__(detail)
        self.detail = detail
        self.attempts = attempts


@dataclass
class OverviewResult:
    observations: list[Observation]
    dropped: list[str]
    conventions: set[str]
    model: str
    adapter: str
    is_mock: bool
    attempts: int
    latency_s: float
    load_s: float | None
    raw_text: str = field(repr=False, default="")
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)
    tiles: Optional[dict] = None


def run_pass(
    image: Image.Image,
    view: ImageView,
    adapter: InferenceAdapter,
    *,
    original_size: tuple[int, int],
    region: tuple[float, float, float, float] | None,
    image_id: str,
    prompt: str = prompts.OVERVIEW,
    frame_id: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_retries: int = MAX_REPAIR_RETRIES,
    sampling: dict | None = None,
) -> OverviewResult:
    jpeg = encode_jpeg(image)
    ow, oh = original_size
    base_prompt = prompt
    total_latency = 0.0
    load_s = None
    errors: list[str] = []

    for attempt in range(1, max_retries + 2):
        result: InferenceResult = adapter.analyze(
            InferenceRequest(
                prompt=prompt,
                images=[jpeg],
                system=prompts.SYSTEM,
                json_schema=RAW_DETECTIONS_SCHEMA,
                max_tokens=max_tokens,
                **(sampling or {}),
            )
        )
        total_latency += result.latency_s
        load_s = result.load_s if result.load_s is not None else load_s
        if result.truncated and attempt <= max_retries and RUNAWAY_TEXT.search(result.text) and prompts.NO_TEXT not in prompt:
            # The model got stuck writing a repeated string inside one marking and ran out of tokens.
            # Everything after that item is lost, so ask again for boxes only; markings come from close-ups.
            errors.append(f"attempt {attempt}: the reply ran away inside a text field and was cut off; asked again without text reading")
            prompt = base_prompt + prompts.NO_TEXT
            continue
        try:
            parsed: ParseResult = parse_detections(
                result.text,
                view=view,
                original_w=ow,
                original_h=oh,
                image_id=image_id,
                frame_id=frame_id,
                region=region,
            )
        except ModelOutputError as exc:
            errors.append(f"attempt {attempt}: {exc.detail}")
            prompt = base_prompt + "\n\n" + repair_prompt(exc.detail)
            continue

        observations, loop_reasons = drop_repetition_runs(parsed.observations, truncated=result.truncated)
        observations, repeat_reasons = drop_repeated_boxes(observations)
        loop_reasons = [*loop_reasons, *repeat_reasons]
        # Re-number so ids stay dense after drops.
        observations = [o.model_copy(update={"id": f"obs_{i:03d}"}) for i, o in enumerate(observations)]
        return OverviewResult(
            observations=observations,
            dropped=[*parsed.dropped, *loop_reasons],
            conventions=parsed.conventions,
            model=result.model,
            adapter=result.adapter,
            is_mock=result.is_mock,
            attempts=attempt,
            latency_s=round(total_latency, 3),
            load_s=load_s,
            raw_text=result.text,
            truncated=result.truncated,
            warnings=[TRUNCATED_WARNING] if result.truncated else [],
        )

    raise AnalysisFailed(
        "The model did not return usable detections after retrying. No detections are shown.", errors
    )


def finish(prepared: PreparedImage, result: OverviewResult) -> OverviewResult:
    """Checks that need the pixels or the whole result, applied once to a finished overview."""
    obs, blank = drop_blank_boxes(result.observations, prepared.original)
    obs, twice = merge_same_chip(obs)
    result.observations = [o.model_copy(update={"id": f"obs_{i:03d}"}) for i, o in enumerate(obs)]
    result.dropped = list(result.dropped) + blank + twice
    return result


def run_overview(
    prepared: PreparedImage,
    adapter: InferenceAdapter,
    *,
    image_id: str,
    frame_id: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_retries: int = MAX_REPAIR_RETRIES,
    sampling: dict | None = None,
) -> OverviewResult:
    """The whole photo, downsized to the analysis size."""
    w, h = prepared.size
    return finish(prepared, run_pass(
        prepared.analysis,
        prepared.analysis_view,
        adapter,
        original_size=(w, h),
        region=None,
        image_id=image_id,
        frame_id=frame_id,
        max_tokens=max_tokens,
        max_retries=max_retries,
        sampling=sampling,
    ))
