#!/usr/bin/env python3
"""Run one configuration on every board in samples/ and print one table.

    python scripts/eval_boards.py

Each samples/<name>.truth.json names its photo and has a "role":

  reference   samples/ref_labelled.jpg. Its chips carry readable print (MT1379GE, MT1336E, M12L64164A,
              HY29LV800BT), so it is the board to tune settings on and to check marking reading against.
  held_out    boards the settings were NOT tuned on. Look at these once, after choosing settings on the reference.
              If a setting helps the reference but hurts here, it was fitted to one photo.

This does not train the model. It measures a fixed model with fixed settings on boards it has not been tuned on.
The close-up pass runs by default because that is where chip text is read. Use --no-detail for a faster run.
Truth boxes are drawn by eye (a few percent) and the held-out photos are only 500 px wide, so read the boxes.jpg
files too and treat a difference of one part as noise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from smoke_vlm import run_smoke  # noqa: E402

from app.adapters import AdapterError, MockAdapter, OllamaAdapter  # noqa: E402
from app.intake import IntakeError  # noqa: E402
from app.pipeline import AnalysisFailed  # noqa: E402
from app.tiles import parse_grid  # noqa: E402

ORDER = {"reference": 0, "held_out": 1}


def load_boards(samples: Path, only: list[str] | None):
    boards = []
    for tp in sorted(samples.glob("*.truth.json")):
        truth = json.loads(tp.read_text())
        name = tp.name.removesuffix(".truth.json")
        if only and name not in only:
            continue
        boards.append((name, truth.get("role", "held_out"), samples / truth["image"], tp))
    return sorted(boards, key=lambda b: (ORDER.get(b[1], 9), b[0]))


def row(name, role, m) -> dict:
    s = m["score"]
    mk = s["markings"]
    return {
        "board": name, "role": role,
        "found": f"{s['found']}/{s['truth_parts_counted']}",
        "box+category": s["recall_box_and_category"],
        "false_pos": len(s["false_positives"]),
        "poor": len(s["poor_boxes"]),
        "markings": f"{len(mk['correct'])} ok, {len(mk['near'])} near, {len(mk['wrong'])} wrong, {len(mk['not_read'])} unread, {len(mk['not_found'])} chip not found of {mk['readable_parts']}",
        "unreadable_claims": len(s["marking_claims_on_unreadable"]),
        "cut_off": m["reply_cut_off"],
        "seconds": m["wall_s"],
        "detections": m["observations"],
        "by_look_alike": (m.get("repeat_pass") or {}).get("found", "-"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="samples")
    ap.add_argument("--out", default="eval_out")
    ap.add_argument("--model", default="huihui_ai/qwen3-vl-abliterated:4b-instruct")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--tiles", default="off", help="off, 2x2, 3x2 ...")
    ap.add_argument("--presence-penalty", type=float, help="default is the app default (1.5)")
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--no-detail", action="store_true", help="skip the close-up pass (no markings are read)")
    ap.add_argument("--repeats", action="store_true", help="after the model passes, search the photo for look-alikes of the small parts it boxed (no model call; blue boxes)")
    ap.add_argument("--repeat-threshold", type=float, default=0.75, help="match strength 0-1; lower finds more and adds more junk")
    ap.add_argument("--only", nargs="*", help="board names, e.g. --only ref_labelled test_b_control")
    ap.add_argument("--mock", action="store_true", help="plumbing check with the labelled MOCK adapter")
    args = ap.parse_args()

    try:
        grid = parse_grid(args.tiles)
    except ValueError as exc:
        print(exc)
        return 2
    sampling = {} if args.presence_penalty is None else {"presence_penalty": args.presence_penalty}
    boards = load_boards(Path(args.samples), args.only)
    if not boards:
        print(f"No *.truth.json files found in {args.samples}.")
        return 2

    rows = []
    for name, role, image, truth in boards:
        print(f"\n=== {name} ({role})", flush=True)
        adapter = MockAdapter() if args.mock else OllamaAdapter(args.model, host=args.host)
        try:
            m = run_smoke(image, adapter, Path(args.out) / name, grid=grid, sampling=sampling, max_tokens=args.max_tokens,
                          truth=truth, quiet=True, detail=not args.no_detail, repeats=args.repeats, repeat_threshold=args.repeat_threshold)
        except (AdapterError, AnalysisFailed, IntakeError) as exc:
            print(f"   FAILED: {getattr(exc, 'message', None) or getattr(exc, 'detail', str(exc))}")
            rows.append({"board": name, "role": role, "failed": True})
            continue
        rows.append(row(name, role, m))
        for d in m["score"]["markings"]["details"]:
            print(f"   {d['truth']}: expected {d['expected']!r}, model said {d['claimed']!r} -> {d['result']}")

    print("\n" + "=" * 100)
    print(("MOCK adapter: numbers below mean nothing\n" if args.mock else "") + f"model {args.model}  tiles {args.tiles}  presence penalty {args.presence_penalty or 'default'}")
    cols = ["board", "role", "found", "box+category", "false_pos", "poor", "detections", "by_look_alike", "unreadable_claims", "cut_off", "seconds"]
    print("  ".join(f"{c:>14}" for c in cols))
    for r in rows:
        print("  ".join(f"{str(r.get(c, 'FAILED' if c == 'found' else '')):>14}" for c in cols))
    for r in rows:
        if "markings" in r:
            print(f"markings, {r['board']}: {r['markings']}")
    Path(args.out).mkdir(parents=True, exist_ok=True)
    (Path(args.out) / "summary.json").write_text(json.dumps(rows, indent=2))
    print(f"\nOpen {args.out}\\<board>\\boxes.jpg for each board, then zip {args.out} and send it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
