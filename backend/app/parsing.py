"""Turn raw model text into validated Observations in ORIGINAL pixel space.

Never fabricates detections: malformed items are dropped and reported, and an entirely
unusable reply raises :class:`ModelOutputError` so the caller can run a bounded repair
retry and then show a visible failure.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from .geometry import GeometryError, ImageView, is_whole_image, model_box_to_original
from .schemas import IdStatus, Observation, RawDetection, Source

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_ITEM = re.compile(r"\{[^{}]*\}")
# The same 1-6 characters five or more times in a row ("0808080808...") is a loop, not print.
RUNAWAY_TEXT = re.compile(r"(.{1,6}?)\1{5,}", re.S)


class ModelOutputError(ValueError):
    """The reply cannot be used. ``detail`` is safe to show to the user and to feed a repair prompt."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


@dataclass
class ParseResult:
    observations: list[Observation]
    dropped: list[str] = field(default_factory=list)  # reasons, for logs / the UI
    conventions: set[str] = field(default_factory=set)  # coordinate conventions seen


def _loads_lenient(text: str):
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Salvage complete flat objects from truncated output; never invent the missing ones.
    items = []
    for m in _ITEM.finditer(cleaned):
        try:
            items.append(json.loads(m.group(0)))
        except json.JSONDecodeError:
            continue
    if items:
        return items
    raise ModelOutputError("The reply was not valid JSON.")


def parse_detections(
    text: str,
    *,
    view: ImageView,
    original_w: int,
    original_h: int,
    image_id: str,
    frame_id: str | None = None,
    id_prefix: str = "obs",
    start_index: int = 0,
    region: tuple[float, float, float, float] | None = None,
) -> ParseResult:
    """``region`` is the part of the original (original px) the model was shown. It defaults to the
    whole image. A box that covers the whole region is dropped, because it describes nothing."""
    data = _loads_lenient(text)
    if isinstance(data, dict):  # some runtimes wrap the array
        for key in ("detections", "components", "objects", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        raise ModelOutputError("Expected a JSON array of detections.")

    out = ParseResult(observations=[])
    for i, raw_item in enumerate(data):
        try:
            raw = RawDetection.model_validate(raw_item)
        except ValidationError as exc:
            out.dropped.append(f"item {i}: invalid fields ({exc.errors()[0]['loc']})")
            continue
        try:
            box, convention = model_box_to_original(raw.bbox_2d, view, original_w, original_h)
        except GeometryError as exc:
            out.dropped.append(f"item {i} ({raw.label}): {exc}")
            continue
        rx1, ry1, rx2, ry2 = region or (0.0, 0.0, float(original_w), float(original_h))
        local = (box[0] - rx1, box[1] - ry1, box[2] - rx1, box[3] - ry1)
        if is_whole_image(local, rx2 - rx1, ry2 - ry1):
            out.dropped.append(f"item {i} ({raw.label}): box covers the whole image")
            continue
        out.conventions.add(convention)

        marking = (raw.marking_text or "").strip() or None
        if marking and RUNAWAY_TEXT.search(marking):
            out.dropped.append(f"item {i} ({raw.label}): marking looked like a repetition loop, so the marking was discarded")
            marking = None
        # Evidence rule: text the model says it could not read is not a marking.
        if not raw.readable:
            marking = None
        if marking and raw.readable:
            status = IdStatus.tentative  # only a reference match or the user can confirm
            candidates = [{"identity": raw.identity_guess.strip()}] if raw.identity_guess and raw.identity_guess.strip() else []
        else:
            status = IdStatus.unknown
            candidates = []

        limitations = []
        if not raw.readable:
            limitations.append("Marking not readable in this view")
        if raw.note:
            limitations.append(raw.note.strip())
        evidence = [f"Model saw: {raw.label.strip()}"]
        if marking:
            evidence.append(f"Marking read by the model (unverified): {marking}")

        try:
            out.observations.append(
                Observation(
                    id=f"{id_prefix}_{start_index + len(out.observations):03d}",
                    image_id=image_id,
                    frame_id=frame_id,
                    category=raw.category,
                    marking_text=marking,
                    candidates=candidates,
                    bbox=box,
                    status=status,
                    evidence=evidence,
                    limitations=limitations,
                    source=Source.vlm,
                )
            )
        except ValidationError as exc:
            out.dropped.append(f"item {i} ({raw.label}): {exc.errors()[0]['msg']}")

    if not out.observations and data:
        raise ModelOutputError("None of the detections in the reply were usable.")
    return out


def repair_prompt(error_detail: str) -> str:
    """Text appended for a bounded repair retry (the caller caps retries at 2)."""
    return (
        "Your previous reply could not be used: "
        f"{error_detail} Reply again with ONLY a JSON array. Each item needs label, category, "
        "bbox_2d [x1,y1,x2,y2] (integers 0-1000), readable (true/false). No prose, no markdown."
    )
