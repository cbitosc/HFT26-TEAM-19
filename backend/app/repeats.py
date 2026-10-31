"""Find more of the same small part by how it looks.

A 4B vision model lists a few of the resistors and capacitors on a board and then stops, so a row of ten
identical parts comes back as two. Parts that repeat look alike, so this pass takes each small part the model did
box and searches the whole photo for look-alikes with OpenCV template matching (no model call).

Evidence rules, all independent of any model:

* A match is ``source: assist``, status ``unknown``, with no marking and no candidate identity. It is a part that
  looks like another part, not a part anyone read.
* The category is copied from the part it resembles, and the observation says so in its evidence and limits.
* Matches that overlap anything already found, or sit inside a larger part (a chip, a connector), are dropped.
* Exemplars are limited to small repeatable categories. A model-found chip is never used to label other chips.

The thresholds were chosen on one close-up photo (see docs/benchmark.md), so treat the result as a suggestion
the person reviews, not a count.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .geometry import iou
from .intake import PreparedImage
from .schemas import Category, IdStatus, Observation, Source

REPEAT_CATEGORIES = {Category.resistor, Category.capacitor, Category.led, Category.button}
MIN_EXEMPLAR_SIDE = 6.0  # original pixels; smaller than this has no texture to match
MAX_EXEMPLAR_SIDE = 220.0
MAX_EXEMPLARS = 8
MAX_NEW_TOTAL = 150
MAX_PER_EXEMPLAR = 60
SCALES = (0.7, 0.85, 1.0, 1.2, 1.4)
THRESHOLD = 0.80  # TM_CCOEFF_NORMED on colour, 1.0 = identical
MIN_TEMPLATE_STD = 10.0  # a flat patch matches everything
WORK_LONG_SIDE = 1600  # large photos are matched on a reduced copy
NMS_IOU = 0.30
EXISTING_IOU = 0.25


@dataclass
class _Hit:
    score: float
    box: tuple[float, float, float, float]  # original pixels
    source_id: str
    category: Category


def _pick_exemplars(observations: list[Observation]) -> list[Observation]:
    chosen: list[Observation] = []
    per_category: dict[Category, int] = {}
    for o in sorted(observations, key=lambda o: -((o.bbox[2] - o.bbox[0]) * (o.bbox[3] - o.bbox[1]))):
        if o.category not in REPEAT_CATEGORIES:
            continue
        w, h = o.bbox[2] - o.bbox[0], o.bbox[3] - o.bbox[1]
        if min(w, h) < MIN_EXEMPLAR_SIDE or max(w, h) > MAX_EXEMPLAR_SIDE:
            continue
        if per_category.get(o.category, 0) >= 3 or any(iou(o.bbox, c.bbox) > 0.5 for c in chosen):
            continue
        chosen.append(o)
        per_category[o.category] = per_category.get(o.category, 0) + 1
        if len(chosen) >= MAX_EXEMPLARS:
            break
    return chosen


def _nms(hits: list[_Hit]) -> list[_Hit]:
    kept: list[_Hit] = []
    for h in sorted(hits, key=lambda h: -h.score):
        if all(iou(h.box, k.box) <= NMS_IOU for k in kept):
            kept.append(h)
    return kept


def _inside(point, box) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def find_repeats(
    prepared: PreparedImage,
    observations: list[Observation],
    *,
    exemplars: list[Observation] | None = None,
    threshold: float = THRESHOLD,
    id_prefix: str = "rep",
) -> tuple[list[Observation], dict]:
    """Return (new look-alike observations, summary). Never raises on a bad photo: it just finds nothing.

    ``exemplars`` is the part (or parts) to search for. Left as None, the pass picks small resistors,
    capacitors, LEDs and buttons from ``observations`` itself. A person-chosen exemplar may be any category
    except the board, since a person decided it is worth searching for.
    """
    summary = {"exemplars": 0, "found": 0, "rejected_overlap": 0, "threshold": threshold}
    if exemplars is None:
        exemplars = _pick_exemplars(observations)
    else:
        exemplars = [o for o in exemplars if o.category != Category.board and min(o.bbox[2] - o.bbox[0], o.bbox[3] - o.bbox[1]) >= MIN_EXEMPLAR_SIDE]
    summary["exemplars"] = len(exemplars)
    if not exemplars:
        return [], summary

    rgb = np.asarray(prepared.original.convert("RGB"))
    img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    long_side = max(img.shape[:2])
    work = min(1.0, WORK_LONG_SIDE / long_side)
    if work < 1.0:
        img = cv2.resize(img, None, fx=work, fy=work, interpolation=cv2.INTER_AREA)
    ih, iw = img.shape[:2]

    hits: list[_Hit] = []
    for ex in exemplars:
        x1, y1, x2, y2 = (round(v * work) for v in ex.bbox)
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(iw, x2), min(ih, y2)
        tmpl0 = img[y1:y2, x1:x2]
        if tmpl0.shape[0] < 4 or tmpl0.shape[1] < 4 or float(tmpl0.std()) < MIN_TEMPLATE_STD:
            continue
        candidates: list[_Hit] = []
        for rot in (0, 1):
            base = np.rot90(tmpl0, rot) if rot else tmpl0
            for s in SCALES:
                t = cv2.resize(np.ascontiguousarray(base), None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
                th, tw = t.shape[:2]
                if min(th, tw) < 5 or th >= ih // 2 or tw >= iw // 2:
                    continue
                res = cv2.matchTemplate(img, t, cv2.TM_CCOEFF_NORMED)
                res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
                ys, xs = np.where(res >= threshold)
                for y, x in zip(ys.tolist(), xs.tolist()):
                    box = ((x) / work, (y) / work, (x + tw) / work, (y + th) / work)
                    candidates.append(_Hit(float(res[y, x]), box, ex.id, ex.category))
        candidates = _nms(candidates)[:MAX_PER_EXEMPLAR]
        hits.extend(candidates)

    hits = _nms(hits)  # the same spot found from two exemplars keeps the better score
    found: list[Observation] = []
    big = [o for o in observations if o.category != Category.board]
    for h in hits:
        centre = ((h.box[0] + h.box[2]) / 2, (h.box[1] + h.box[3]) / 2)
        if any(iou(h.box, o.bbox) > EXISTING_IOU or _inside(centre, o.bbox) for o in big):
            summary["rejected_overlap"] += 1
            continue
        w, h_ = prepared.size
        box = (max(0.0, h.box[0]), max(0.0, h.box[1]), min(float(w), h.box[2]), min(float(h_), h.box[3]))
        if box[2] - box[0] < 3 or box[3] - box[1] < 3:
            continue
        found.append(
            Observation(
                id=f"{id_prefix}_{len(found):03d}",
                image_id=exemplars[0].image_id,
                category=h.category,
                bbox=box,
                status=IdStatus.unknown,
                evidence=[f"Found by appearance: looks like {h.source_id} (match {h.score:.2f}). Not read by the model."],
                limitations=["Matched by appearance only", f"Category copied from {h.source_id}"],
                source=Source.assist,
            )
        )
        if len(found) >= MAX_NEW_TOTAL:
            break
    summary["found"] = len(found)
    return found, summary
