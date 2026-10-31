"""Applying a person's correction to an observation.

The rules here, not the model and not the UI, decide what a correction is allowed to do:

* Only a person who ticked "I checked this against the physical part" can make a model-seen part
  ``confirmed`` (``source`` becomes ``user``). Typing a marking or a name without ticking it gives
  ``tentative`` at best.
* Confirming needs something to confirm: a marking or a part name.
* Changing the marking or the name drops any matched reference, because the match was for the old text.
* A model score no longer describes a part the person has edited, so it is cleared.
"""

from __future__ import annotations

import math
from typing import Any

from .detail import CLOSE_UP_CONTRADICTS, CLOSE_UP_UNREADABLE
from .geometry import GeometryError, clamp_box
from .schemas import Candidate, Category, IdStatus, Observation, Source

MIN_BOX_SIDE_PX = 4.0
_MODEL_MARKING = "Marking read by the model"  # also matches "Marking read by the model (unverified)" from overview
_CLOSE_UP_MARKING = "Marking read from a close-up by the model"
_UNREADABLE = ("Marking not readable in this view", "Take a close-up with light from the side", CLOSE_UP_UNREADABLE, CLOSE_UP_CONTRADICTS)
USER_CONFIRMED = "Confirmed by you against the physical part"
KNOWN_FIELDS = {"category", "marking_text", "identity", "confirmed", "bbox"}


class CorrectionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _text(value: Any, field: str, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CorrectionError("invalid_field", f"{field} must be text.")
    value = " ".join(value.split())
    if len(value) > limit:
        raise CorrectionError("invalid_field", f"{field} is longer than {limit} characters.")
    return value or None


def _bbox(value: Any, width: int, height: int) -> tuple[float, float, float, float]:
    try:
        x1, y1, x2, y2 = (float(v) for v in value)
    except (TypeError, ValueError) as exc:
        raise CorrectionError("invalid_box", "The box needs four numbers: x1, y1, x2, y2.") from exc
    if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
        raise CorrectionError("invalid_box", "The box has a value that is not a number.")
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    try:
        box = clamp_box((x1, y1, x2, y2), width, height)
    except GeometryError as exc:
        raise CorrectionError("invalid_box", "The box lies outside the photo. Draw it around the part.") from exc
    if box[2] - box[0] < MIN_BOX_SIDE_PX or box[3] - box[1] < MIN_BOX_SIDE_PX:
        raise CorrectionError("invalid_box", "The box is too small or lies outside the photo. Draw it around the part.")
    return box


def _without(items: list[str], *prefixes: str) -> list[str]:
    return [s for s in items if not s.startswith(prefixes)]


def _add(items: list[str], line: str) -> list[str]:
    return items if line in items else [*items, line]


def apply_correction(obs: Observation, patch: dict[str, Any], width: int, height: int) -> Observation:
    unknown = set(patch) - KNOWN_FIELDS
    if unknown:
        raise CorrectionError("unknown_field", f"These fields cannot be changed: {', '.join(sorted(unknown))}.")

    data = obs.model_copy(deep=True)
    evidence = list(data.evidence)
    limitations = list(data.limitations)
    changed_identity = False
    changed_category = False

    if "category" in patch:
        try:
            category = Category(patch["category"])
        except ValueError as exc:
            raise CorrectionError("invalid_field", "That part type is not one VisionGuard knows.") from exc
        if category != data.category:
            changed_category = True
            evidence = _add(evidence, f"You set the part type to {category.value.replace('_', ' ')}")
            data.category = category

    marking = data.marking_text
    if "marking_text" in patch:
        new = _text(patch["marking_text"], "Marking", 200)
        if new != marking:
            changed_identity = True
            evidence = _without(evidence, _MODEL_MARKING, _CLOSE_UP_MARKING, "You entered the marking")
            if new:
                evidence = _add(evidence, f"You entered the marking: {new}")
                limitations = _without(limitations, *_UNREADABLE)
            marking = new

    identity = data.candidates[0].identity if data.candidates else None
    if "identity" in patch:
        new = _text(patch["identity"], "Part name", 120)
        if new != identity:
            changed_identity = True
            evidence = _without(evidence, "You named the part")
            if new:
                evidence = _add(evidence, f"You named the part: {new}")
            identity = new

    if "bbox" in patch:
        box = _bbox(patch["bbox"], width, height)
        if box != tuple(data.bbox):
            data.bbox = box
            evidence = _add(evidence, "You redrew the box")

    has_identity = bool(marking or identity)
    wants_confirm = bool(patch["confirmed"]) if "confirmed" in patch else (
        data.status == IdStatus.confirmed and data.source == Source.user
    )
    if "confirmed" in patch and not isinstance(patch["confirmed"], bool):
        raise CorrectionError("invalid_field", "confirmed must be true or false.")
    if wants_confirm and not has_identity:
        raise CorrectionError(
            "nothing_to_confirm", "Enter the marking or the part name before confirming it against the physical part."
        )

    data.marking_text = marking
    data.candidates = [Candidate(identity=identity)] if identity else []
    if changed_identity:
        data.reference_ids = []
        for c in data.candidates:
            c.reference_id = None

    evidence = _without(evidence, USER_CONFIRMED)
    if wants_confirm:
        data.status = IdStatus.confirmed
        data.source = Source.user
        evidence = _add(evidence, USER_CONFIRMED)
    elif has_identity:
        data.status = IdStatus.tentative
    else:
        data.status = IdStatus.unknown
        limitations = _add(limitations, "Marking not readable in this view")

    if changed_identity or changed_category or wants_confirm:
        data.model_score = None
    data.evidence = evidence
    data.limitations = limitations
    # Re-run the schema's own consistency rules (confirmed needs a reference or the user, etc.).
    return Observation.model_validate(data.model_dump())
