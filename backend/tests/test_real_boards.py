"""Regressions from the first real-board run on the laptop (samples/ref_labelled.jpg).

The model wrote one marking, then got stuck in a repeated-digit string, ran out of tokens, and every part after
that was lost. The fixture is that reply, cut off mid-string.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image

from app.adapters import MockAdapter
from app.geometry import view_to_original
from app.intake import IntakeLimits, prepare_image
from app.parsing import RUNAWAY_TEXT
from app.pipeline import run_overview
from app.prompts import NO_TEXT
from app.tiles import MIN_TILE_LONG_SIDE

HERE = Path(__file__).resolve().parent
RUNAWAY = (HERE / "fixtures" / "ref_labelled.runaway.raw.txt").read_text()
SAMPLES = HERE.parents[1] / "samples"


def test_the_real_reply_is_recognised_as_a_runaway():
    assert RUNAWAY_TEXT.search(RUNAWAY)


def test_a_cut_off_runaway_is_asked_again_for_boxes_only():
    photo = prepare_image((SAMPLES / "ref_labelled.jpg").read_bytes())
    prompts = []
    clean = json.dumps([
        {"label": "IC", "category": "ic_package", "bbox_2d": [330, 361, 498, 594], "readable": False},
        {"label": "IC", "category": "ic_package", "bbox_2d": [584, 384, 637, 568], "readable": False},
        {"label": "IC", "category": "ic_package", "bbox_2d": [100, 100, 200, 220], "readable": False},
    ])

    def respond(req):
        prompts.append(req.prompt)
        return RUNAWAY if len(prompts) == 1 else clean

    adapter = MockAdapter(respond, done_reason="length")
    r = run_overview(photo, adapter, image_id="x")
    assert len(prompts) == 2
    assert NO_TEXT not in prompts[0] and NO_TEXT in prompts[1]
    assert len(r.observations) == 3
    assert all(o.marking_text is None for o in r.observations)


def test_a_looping_marking_is_discarded_but_the_box_and_the_good_marking_stay():
    photo = prepare_image((SAMPLES / "ref_labelled.jpg").read_bytes())
    text = json.dumps([
        {"label": "IC", "category": "ic_package", "bbox_2d": [330, 361, 498, 594], "readable": True, "marking_text": "MT1379GE"},
        {"label": "IC", "category": "ic_package", "bbox_2d": [584, 384, 637, 568], "readable": True, "marking_text": "HYZ" + "08" * 30},
    ])
    r = run_overview(photo, MockAdapter(lambda q: text), image_id="x")
    assert [o.marking_text for o in r.observations] == ["MT1379GE", None]
    assert any("repetition loop" in d for d in r.dropped)


def jpeg(w, h):
    buf = io.BytesIO()
    Image.effect_noise((w, h), 60).convert("RGB").save(buf, format="JPEG")
    return buf.getvalue()


def test_a_small_photo_is_enlarged_for_the_model_and_boxes_map_back():
    p = prepare_image(jpeg(500, 400), IntakeLimits())
    long_side = max(p.analysis.size)
    assert long_side >= IntakeLimits().analysis_min_long_side
    assert p.size == (500, 400)  # the original is untouched
    v = p.analysis_view
    assert v.scale > 1.0
    # a box drawn on the enlarged copy lands back on the original at the same relative place
    ax, ay = p.analysis.size
    box = view_to_original((ax * 0.4, ay * 0.4, ax * 0.6, ay * 0.6), v)
    assert all(abs(a - b) < 1.5 for a, b in zip(box, (200, 160, 300, 240)))


def test_a_photo_already_big_enough_is_not_enlarged():
    p = prepare_image(jpeg(1100, 800), IntakeLimits())
    assert p.analysis.size == (1100, 800)


def test_small_tiles_are_enlarged_before_the_model_sees_them():
    from app.tiles import run_overview_tiled

    seen = []

    def respond(req):
        im = Image.open(io.BytesIO(req.images[0]))
        seen.append(max(im.size))
        return "[]"

    photo = prepare_image(jpeg(500, 500), IntakeLimits(analysis_min_long_side=0))
    run_overview_tiled(photo, MockAdapter(respond), image_id="x", grid=(2, 2))
    tile_sizes = seen[1:]  # the first call is the overview
    assert tile_sizes and all(s >= MIN_TILE_LONG_SIDE for s in tile_sizes)
