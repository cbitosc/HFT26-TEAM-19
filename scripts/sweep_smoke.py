#!/usr/bin/env python3
"""Run several settings on one photo and print one comparison table.

    python scripts/sweep_smoke.py samples/ref_labelled.jpg --truth samples/ref_labelled.truth.json

Default runs (4 model runs; a few minutes on a laptop GPU), the second round after the first sweep
showed presence penalty 1.5 was best of 0 / 0.5 / 1.5 on the sample photo:

  C  abliterated, no tiles, presence penalty 1.5   (the new default, repeated as the reference)
  F  abliterated, no tiles, presence penalty 1.0   (is 1.5 the best value, or just better than 0.5?)
  G  abliterated, 3x2 tiles, presence penalty 1.5  (small-part search without the loops)
  H  abliterated, 2x2 tiles, presence penalty 1.5  (fewer, larger tiles: cheaper)

The first-round runs (A, B, D, E) can still be repeated with --only.

Each run writes <out>/<name>/ (boxes.jpg, raw.txt, observations.json, metrics.json). The table is an
approximate comparison on one photo against a hand-made truth file. Open the boxes.jpg files too.
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
from app.pipeline import AnalysisFailed  # noqa: E402
from app.tiles import parse_grid  # noqa: E402

ABL = "huihui_ai/qwen3-vl-abliterated:4b-instruct"
BASE = "qwen3-vl:4b-instruct"
DEFAULT_RUNS = [
    ("C_abl_pp1.5", ABL, "off", 1.5),
    ("F_abl_pp1.0", ABL, "off", 1.0),
    ("G_abl_tiles3x2_pp1.5", ABL, "3x2", 1.5),
    ("H_abl_tiles2x2_pp1.5", ABL, "2x2", 1.5),
]
FIRST_ROUND_RUNS = [
    ("A_abl_pp0.5", ABL, "off", 0.5),
    ("B_abl_pp0", ABL, "off", 0.0),
    ("D_abl_tiles3x2", ABL, "3x2", 0.5),
    ("E_base_pp0.5", BASE, "off", 0.5),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--truth", required=True)
    ap.add_argument("--out", default="sweep_ref")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--only", nargs="*", help="run only these names, e.g. --only C_abl_pp1.5 G_abl_tiles3x2_pp1.5")
    ap.add_argument("--mock", action="store_true", help="plumbing check with the labelled MOCK adapter")
    args = ap.parse_args()

    rows = []
    for name, model, tiles, pp in (DEFAULT_RUNS + FIRST_ROUND_RUNS if args.only else DEFAULT_RUNS):
        if args.only and name not in args.only:
            continue
        print(f"\n=== {name}: {model}, tiles {tiles}, presence penalty {pp}", flush=True)
        adapter = MockAdapter() if args.mock else OllamaAdapter(model, host=args.host)
        try:
            m = run_smoke(args.image, adapter, Path(args.out) / name, grid=parse_grid(tiles),
                          sampling={"presence_penalty": pp}, truth=args.truth, quiet=True)
        except (AdapterError, AnalysisFailed) as exc:
            msg = getattr(exc, "message", None) or getattr(exc, "detail", str(exc))
            print(f"   FAILED: {msg}")
            rows.append((name, None))
            continue
        sc = m["score"]
        print(f"   found {sc['found']}/{sc['truth_parts_counted']}, false positives {len(sc['false_positives'])}, "
              f"{m['wall_s']} s, cut off: {m['reply_cut_off']}")
        rows.append((name, m))

    print("\n" + "=" * 100)
    print(f"{'run':<18}{'found':>8}{'cat ok':>8}{'false+':>8}{'poor':>6}{'dets':>6}{'cut off':>9}{'secs':>8}{'VRAM MiB':>10}  check by eye")
    for name, m in rows:
        if m is None:
            print(f"{name:<18}  failed (see above)")
            continue
        sc = m["score"]
        n = sc["truth_parts_counted"]
        print(f"{name:<18}{str(sc['found']) + '/' + str(n):>8}{round(sc['recall_box_and_category'] * n):>8}{len(sc['false_positives']):>8}"
              f"{len(sc['poor_boxes']):>6}{m['observations']:>6}{str(m['reply_cut_off']):>9}{m['wall_s']:>8}{str(m['peak_vram_mib']):>10}  "
              f"{len(sc['marking_claims_on_unreadable'])} marking claim(s)")
    print("\nfound = truth parts with a box at IoU >= 0.3. cat ok = of those, with the right category. false+ = boxes touching nothing.")
    print("Open each <run>/boxes.jpg before deciding. A run that finds more but scatters boxes is not better.")
    Path(args.out).mkdir(parents=True, exist_ok=True)
    (Path(args.out) / "summary.json").write_text(json.dumps({n: m for n, m in rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
