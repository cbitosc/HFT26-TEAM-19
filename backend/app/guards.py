"""Checks on a model reply that no prompt can guarantee.

Repetition loop: when a small model gets stuck it writes the same item over and over with a box
that steps along the image. The first real photo produced a column of 8 identical "capacitor" strips
and a column of 10 "connector" blocks, both ending where the token limit cut the reply off. The
parser used to keep them as detections. They are not parts, so they are dropped and the drop is reported.

A run is a sequence of consecutive items of one category, near-equal size, lined up in one column (or row)
and chained edge to edge. A genuine row of identical parts can look like this, so the thresholds are
deliberately high: 5 or more when the reply was cut off, 8 or more otherwise. Dropped items are listed
in ``dropped`` so nothing disappears silently.
"""

from __future__ import annotations

from .schemas import Category, Observation

MIN_RUN_TRUNCATED = 5
MIN_RUN_COMPLETE = 8
SIZE_TOLERANCE = 0.25
ALIGN_TOLERANCE = 0.15
CHAIN_GAP = 0.35  # overlap or gap between neighbours, as a fraction of the box size along the chain


def _chained(a: Observation, b: Observation) -> str | None:
    """'column' or 'row' if ``b`` continues ``a`` in a stepping run, else None."""
    if a.category != b.category:
        return None
    aw, ah = a.bbox[2] - a.bbox[0], a.bbox[3] - a.bbox[1]
    bw, bh = b.bbox[2] - b.bbox[0], b.bbox[3] - b.bbox[1]
    if abs(aw - bw) > SIZE_TOLERANCE * max(aw, bw) or abs(ah - bh) > SIZE_TOLERANCE * max(ah, bh):
        return None
    w, h = max(aw, bw), max(ah, bh)
    same_x = abs(a.bbox[0] - b.bbox[0]) <= ALIGN_TOLERANCE * w and abs(a.bbox[2] - b.bbox[2]) <= ALIGN_TOLERANCE * w
    same_y = abs(a.bbox[1] - b.bbox[1]) <= ALIGN_TOLERANCE * h and abs(a.bbox[3] - b.bbox[3]) <= ALIGN_TOLERANCE * h
    gap_y = max(a.bbox[1], b.bbox[1]) - min(a.bbox[3], b.bbox[3])  # negative when they overlap
    gap_x = max(a.bbox[0], b.bbox[0]) - min(a.bbox[2], b.bbox[2])
    if same_x and not same_y and abs(gap_y) <= CHAIN_GAP * h:
        return "column"
    if same_y and not same_x and abs(gap_x) <= CHAIN_GAP * w:
        return "row"
    return None


def drop_repetition_runs(observations: list[Observation], *, truncated: bool) -> tuple[list[Observation], list[str]]:
    min_run = MIN_RUN_TRUNCATED if truncated else MIN_RUN_COMPLETE
    drop: set[int] = set()
    reasons: list[str] = []
    i = 0
    while i < len(observations) - 1:
        kind = _chained(observations[i], observations[i + 1])
        if not kind:
            i += 1
            continue
        j = i + 1
        while j + 1 < len(observations) and _chained(observations[j], observations[j + 1]) == kind:
            j += 1
        n = j - i + 1
        if n >= min_run:
            drop.update(range(i, j + 1))
            cat = observations[i].category.value
            reasons.append(
                f"{n} '{cat}' boxes of the same size chained edge to edge down the image look like a repetition loop, "
                f"so they were dropped" if kind == "column" else
                f"{n} '{cat}' boxes of the same size chained edge to edge across the image look like a repetition loop, "
                f"so they were dropped"
            )
        i = j + 1 if n >= 2 else i + 1
    kept = [o for k, o in enumerate(observations) if k not in drop]
    return kept, reasons


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


REPEAT_IOU = 0.9


def drop_repeated_boxes(observations: list[Observation]) -> tuple[list[Observation], list[str]]:
    """Keep the first copy of a box and drop later copies of it.

    The second real run (no repetition penalty) showed a loop the chain test cannot see: the model
    alternated between the same two boxes, a tall one and a short one, 12 times each. A model that is
    reading a board has no reason to report the same part twice with the same box, so a later box of the
    same category that overlaps an earlier one by 0.9 or more is a repeat. The first copy stays.
    """
    kept: list[Observation] = []
    dropped_by_category: dict[str, int] = {}
    for obs in observations:
        if any(k.category == obs.category and _iou(k.bbox, obs.bbox) >= REPEAT_IOU for k in kept):
            cat = obs.category.value
            dropped_by_category[cat] = dropped_by_category.get(cat, 0) + 1
            continue
        kept.append(obs)
    reasons = [
        f"{n} repeated '{cat}' box{'es' if n != 1 else ''} with the same position as an earlier one looked like a repetition loop, so "
        f"{'they were' if n != 1 else 'it was'} dropped"
        for cat, n in dropped_by_category.items()
    ]
    return kept, reasons


BLANK_STD = 6.0  # grey-level spread inside a box; a real part has print, edges or texture
CHIP_FAMILY = {Category.ic_package, Category.microcontroller_module}
SAME_CHIP_IOU = 0.6


def drop_blank_boxes(observations: list[Observation], original) -> tuple[list[Observation], list[str]]:
    """Drop a box over a flat, featureless patch of the photo (white banner, blank background).

    Tiles of a photo with a plain border made the model draw capacitors on empty white. Checked on the pixels,
    so it does not depend on what the model says. The board itself is never dropped.
    """
    import numpy as np

    gray = np.asarray(original.convert("L"), dtype=float)
    h, w = gray.shape
    kept: list[Observation] = []
    blank = 0
    for o in observations:
        if o.category == Category.board:
            kept.append(o)
            continue
        x1, y1, x2, y2 = (int(round(v)) for v in o.bbox)
        patch = gray[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
        if patch.size and float(patch.std()) < BLANK_STD:
            blank += 1
            continue
        kept.append(o)
    reasons = [f"{blank} box{'es' if blank != 1 else ''} over a blank area of the photo, dropped"] if blank else []
    return kept, reasons


def merge_same_chip(observations: list[Observation]) -> tuple[list[Observation], list[str]]:
    """One chip boxed twice under two chip-like categories (ic_package and microcontroller_module): keep the first."""
    kept: list[Observation] = []
    merged = 0
    for o in observations:
        if o.category in CHIP_FAMILY and any(k.category in CHIP_FAMILY and k.category != o.category and _iou(k.bbox, o.bbox) >= SAME_CHIP_IOU for k in kept):
            merged += 1
            continue
        kept.append(o)
    reasons = [f"{merged} chip{'s' if merged != 1 else ''} boxed twice under two chip categories, kept the first"] if merged else []
    return kept, reasons
