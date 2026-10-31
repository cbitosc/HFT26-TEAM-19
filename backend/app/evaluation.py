"""Score detections against a hand-made ground-truth file (samples/*.truth.json).

The truth files are approximate. They are drawn by eye, so treat a score as a rough comparison
between models or settings on the same photo, not as a measured accuracy.

Matching is one-to-one by IoU, best pairs first. A truth part counts as found at IoU >= ``match_iou``.
Parts marked ``ambiguous`` may be matched but are never counted as missed. Detections that overlap
nothing are false positives; detections that overlap something but not enough are poor boxes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .geometry import iou

MATCH_IOU = 0.30
NOISE_IOU = 0.10
NEAR_RATIO = 0.80


def _norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def marking_result(expected: str, claimed: str | None) -> str:
    """'correct', 'near', 'wrong' or 'not_read' for one printed marking.

    Compared as upper-case letters and digits only. Correct when one contains the other (at least 5
    characters), near when they are 80% alike, which is usually one misread character. 'wrong' is the case
    to watch: the model returned text that is not what is printed.
    """
    e, c = _norm(expected), _norm(claimed or "")
    if not c:
        return "not_read"
    if e == c or e in c or (len(c) >= 5 and c in e):
        return "correct"
    if SequenceMatcher(None, e, c).ratio() >= NEAR_RATIO:
        return "near"
    return "wrong"


@dataclass
class Score:
    found: list[dict] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)
    poor_boxes: list[str] = field(default_factory=list)
    marking_claims_on_unreadable: list[dict] = field(default_factory=list)
    markings: list[dict] = field(default_factory=list)
    counted: int = 0

    @property
    def recall_box(self) -> float | None:
        if not self.counted:
            return None
        return sum(1 for f in self.found if not f["ambiguous"]) / self.counted

    @property
    def recall_box_and_category(self) -> float | None:
        if not self.counted:
            return None
        return sum(1 for f in self.found if not f["ambiguous"] and f["category_ok"]) / self.counted

    def summary(self) -> dict:
        r1, r2 = self.recall_box, self.recall_box_and_category
        return {
            "truth_parts_counted": self.counted,
            "found": sum(1 for f in self.found if not f["ambiguous"]),
            "recall_box": None if r1 is None else round(r1, 3),
            "recall_box_and_category": None if r2 is None else round(r2, 3),
            "missed": self.missed,
            "false_positives": self.false_positives,
            "poor_boxes": self.poor_boxes,
            "marking_claims_on_unreadable": self.marking_claims_on_unreadable,
            "markings": self.marking_summary(),
        }

    def marking_summary(self) -> dict:
        by = {k: [m["truth"] for m in self.markings if m["result"] == k] for k in ("correct", "near", "wrong", "not_read", "not_found")}
        return {"readable_parts": len(self.markings), **by, "details": self.markings}


def score(truth: dict, observations: list[dict], *, match_iou: float = MATCH_IOU) -> Score:
    parts = truth["parts"]
    pairs = []
    for ti, t in enumerate(parts):
        for oi, o in enumerate(observations):
            v = iou(t["bbox"], o["bbox"])
            if v > 0:
                pairs.append((v, ti, oi))
    pairs.sort(reverse=True)
    used_t: set[int] = set()
    used_o: set[int] = set()
    out = Score(counted=sum(1 for t in parts if not t.get("ambiguous")))
    for v, ti, oi in pairs:
        if v < match_iou:
            break
        if ti in used_t or oi in used_o:
            continue
        used_t.add(ti)
        used_o.add(oi)
        t, o = parts[ti], observations[oi]
        out.found.append(
            {
                "truth": t["name"],
                "observation": o["id"],
                "iou": round(v, 3),
                "category_ok": o["category"] == t["category"],
                "category_got": o["category"],
                "ambiguous": bool(t.get("ambiguous")),
            }
        )
        if t.get("marking") is None and (o.get("marking_text") or "").strip():
            out.marking_claims_on_unreadable.append(
                {"truth": t["name"], "observation": o["id"], "claimed": o["marking_text"], "status": o.get("status")}
            )
        if t.get("marking"):
            out.markings.append(
                {
                    "truth": t["name"],
                    "observation": o["id"],
                    "expected": t["marking"],
                    "claimed": (o.get("marking_text") or "").strip() or None,
                    "status": o.get("status"),
                    "result": marking_result(t["marking"], o.get("marking_text")),
                }
            )
    out.missed = [t["name"] for i, t in enumerate(parts) if i not in used_t and not t.get("ambiguous")]
    for i, t in enumerate(parts):
        if i not in used_t and t.get("marking") and not t.get("ambiguous"):
            out.markings.append({"truth": t["name"], "observation": None, "expected": t["marking"], "claimed": None, "status": None, "result": "not_found"})
    for oi, o in enumerate(observations):
        if oi in used_o:
            continue
        best = max((iou(t["bbox"], o["bbox"]) for t in parts), default=0.0)
        label = f"{o['id']} {o['category']}"
        (out.poor_boxes if best >= NOISE_IOU else out.false_positives).append(label)
    return out
