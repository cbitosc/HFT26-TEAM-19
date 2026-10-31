"""Score one or more smoke_out/observations.json files against a truth file.

    python scripts/eval_detections.py samples/ref_labelled.truth.json smoke_abliterated/observations.json
    python scripts/eval_detections.py samples/ref_labelled.truth.json smoke_abliterated/observations.json smoke_base/observations.json

With two or more files it prints them side by side, which is how the abliterated model is compared
with its unmodified base. The truth file is approximate (see backend/app/evaluation.py).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.evaluation import score  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    truth = json.loads(Path(argv[1]).read_text())
    print(f"Truth: {argv[1]}  ({truth['provenance']})\n")
    for path in argv[2:]:
        obs = json.loads(Path(path).read_text())
        s = score(truth, obs).summary()
        print(f"== {path}  ({len(obs)} detections)")
        print(f"   boxes found: {s['found']}/{s['truth_parts_counted']}  recall {s['recall_box']}   with right category: {s['recall_box_and_category']}")
        print(f"   missed: {', '.join(s['missed']) or 'none'}")
        print(f"   false positives (touch nothing): {', '.join(s['false_positives']) or 'none'}")
        print(f"   poor boxes (overlap, below threshold): {', '.join(s['poor_boxes']) or 'none'}")
        for m in s["marking_claims_on_unreadable"]:
            print(f"   CHECK BY EYE: {m['observation']} claims marking {m['claimed']!r} on {m['truth']}, which the annotator could not read ({m['status']})")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
