"""Repetition guard and tiled pass. The two raw replies are the real outputs of the first laptop run
(RTX 4060 laptop GPU, temperature 0.1, 1024-token cap) on the AI-generated photo kept in tests/fixtures/ai_board/. Both were cut off at
the token limit and ended in a loop."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from app.adapters import AdapterError, MockAdapter
from app.adapters.ollama import OllamaAdapter
from app.adapters.base import InferenceRequest
from app.evaluation import score
from app.guards import drop_repeated_boxes, drop_repetition_runs
from app.intake import prepare_image
from app.pipeline import run_overview
from app.schemas import Category, Observation
from app.tiles import (
    Tile, _cut_by_tile, merge, parse_grid, plan_tiles, run_overview_tiled,
)

HERE = Path(__file__).resolve().parent
SAMPLES = HERE / "fixtures" / "ai_board"  # the first sample photo; the recorded replies are for it
RAW_ABL = (HERE / "fixtures" / "board_01.abliterated.raw.txt").read_text()
RAW_BASE = (HERE / "fixtures" / "board_01.base.raw.txt").read_text()
RAW_ABL_PP0 = (HERE / "fixtures" / "board_01.abliterated_pp0.raw.txt").read_text()


@pytest.fixture(scope="module")
def photo():
    return prepare_image((SAMPLES / "board_01.png").read_bytes())


def O(i, cat, box):
    return Observation(id=f"o{i}", image_id="x", category=cat, bbox=box)


def column(n, cat=Category.capacitor, x=100, y0=100, w=60, h=60, step=50):
    return [O(i, cat, (x, y0 + i * step, x + w, y0 + i * step + h)) for i in range(n)]


# ---- the guard on the real replies ------------------------------------------------------------


def test_real_abliterated_reply_loses_the_capacitor_loop_and_keeps_the_real_parts(photo):
    r = run_overview(photo, MockAdapter(lambda q: RAW_ABL, done_reason="length"), image_id="x")
    assert Counter(o.category.value for o in r.observations) == {"microcontroller_module": 1, "usb_port": 2, "gpio_header": 2, "connector": 2}
    assert any("8 'capacitor' boxes" in d and "repetition loop" in d for d in r.dropped)
    assert r.truncated and "cut off" in r.warnings[0]


def test_real_base_reply_loses_the_connector_loop_and_keeps_the_chip_and_ports(photo):
    r = run_overview(photo, MockAdapter(lambda q: RAW_BASE, done_reason="length"), image_id="x")
    cats = Counter(o.category.value for o in r.observations)
    assert cats["ic_package"] == 1 and cats["usb_port"] == 2
    assert any("10 'connector' boxes" in d for d in r.dropped)


def test_dropping_the_loop_removes_every_false_positive_without_losing_a_match(photo):
    truth = json.loads((SAMPLES / "board_01.truth.json").read_text())
    r = run_overview(photo, MockAdapter(lambda q: RAW_ABL, done_reason="length"), image_id="x")
    s = score(truth, [o.model_dump(mode="json") for o in r.observations]).summary()
    assert s["false_positives"] == [] and s["found"] == 6  # was 6 found with 8 false positives


def test_a_reply_that_finished_normally_still_loses_a_long_loop(photo):
    r = run_overview(photo, MockAdapter(lambda q: RAW_ABL), image_id="x")
    assert not r.truncated and r.warnings == [] and not any(o.category.value == "capacitor" for o in r.observations)


# ---- the alternating loop from the second real run (presence penalty 0) --------------------------


def test_real_alternating_loop_keeps_one_copy_of_each_box(photo):
    # 32 items, 24 of them the same two boxes (a tall one and a short one) written 12 times each.
    r = run_overview(photo, MockAdapter(lambda q: RAW_ABL_PP0, done_reason="length"), image_id="x")
    boxes = [tuple(round(v) for v in o.bbox) for o in r.observations]
    assert len(boxes) == len(set(boxes))
    assert len(r.observations) <= 10
    assert any("repeated 'connector' box" in d for d in r.dropped)
    truth = json.loads((SAMPLES / "board_01.truth.json").read_text())
    s = score(truth, [o.model_dump(mode="json") for o in r.observations]).summary()
    assert s["found"] >= 7  # the run found 7 before the repeats were removed


def test_repeated_boxes_only_drop_the_same_category_at_the_same_place():
    a = O(0, Category.connector, (100, 100, 200, 200))
    same = O(1, Category.connector, (101, 101, 201, 201))
    other_cat = O(2, Category.capacitor, (100, 100, 200, 200))
    nearby = O(3, Category.connector, (150, 100, 250, 200))  # half overlap is a different part
    kept, reasons = drop_repeated_boxes([a, same, other_cat, nearby])
    assert [o.id for o in kept] == ["o0", "o2", "o3"] and len(reasons) == 1


# ---- guard thresholds -------------------------------------------------------------------------


def test_short_runs_are_kept_so_real_rows_of_identical_parts_survive():
    obs = column(4)
    kept, reasons = drop_repetition_runs(obs, truncated=True)
    assert len(kept) == 4 and reasons == []


def test_five_in_a_truncated_reply_is_dropped_but_five_in_a_complete_reply_is_kept():
    assert drop_repetition_runs(column(5), truncated=True)[0] == []
    assert len(drop_repetition_runs(column(5), truncated=False)[0]) == 5
    assert drop_repetition_runs(column(8), truncated=False)[0] == []


def test_parts_spaced_apart_are_not_a_run():
    spaced = column(8, step=200)  # 140 px gaps between 60 px boxes
    assert len(drop_repetition_runs(spaced, truncated=True)[0]) == 8


def test_a_row_is_detected_too_and_other_categories_in_between_break_the_run():
    row = [O(i, Category.resistor, (100 + i * 50, 100, 160 + i * 50, 140)) for i in range(6)]
    assert drop_repetition_runs(row, truncated=True)[0] == []
    mixed = column(6)
    mixed[3] = O(99, Category.led, mixed[3].bbox)
    assert len(drop_repetition_runs(mixed, truncated=True)[0]) == 6  # runs of 3 and 2 are below the limit


# ---- sampling reaches the model ---------------------------------------------------------------


def test_default_sampling_is_the_documented_one_and_can_be_overridden(photo):
    seen = []
    run_overview(photo, MockAdapter(lambda q: seen.append(q) or "[]"), image_id="x")
    q = seen[0]
    assert (q.temperature, q.top_p, q.top_k, q.presence_penalty, q.max_tokens) == (0.7, 0.8, 20, 1.5, 2048)
    seen.clear()
    run_overview(photo, MockAdapter(lambda q: seen.append(q) or "[]"), image_id="x", sampling={"presence_penalty": 1.5, "temperature": 0.3})
    assert (seen[0].presence_penalty, seen[0].temperature) == (1.5, 0.3)


def test_ollama_receives_the_sampling_options(monkeypatch):
    sent = {}

    def fake_post(self, path, payload, timeout=None):
        sent.update(payload)
        return {"message": {"content": "[]"}, "done_reason": "length"}

    monkeypatch.setattr(OllamaAdapter, "_post", fake_post)
    res = OllamaAdapter("m").analyze(InferenceRequest(prompt="p", images=[], presence_penalty=1.5))
    o = sent["options"]
    assert (o["temperature"], o["top_p"], o["top_k"], o["presence_penalty"], o["num_predict"]) == (0.7, 0.8, 20, 1.5, 2048)
    assert res.truncated is True


# ---- tiles ------------------------------------------------------------------------------------


def test_grid_parsing():
    assert parse_grid("off") is None and parse_grid("") is None and parse_grid(None) is None
    assert parse_grid("3x2") == (3, 2) and parse_grid("2X2") == (2, 2)
    for bad in ("3", "axb", "0x2", "9x9", "4x4"):
        with pytest.raises(ValueError):
            parse_grid(bad)


@pytest.mark.parametrize("w,h,cols,rows", [(2752, 1536, 3, 2), (2752, 1536, 2, 2), (4032, 3024, 3, 3), (1000, 600, 1, 1), (800, 800, 2, 1)])
def test_tiles_cover_the_image_and_overlap_a_quarter(w, h, cols, rows):
    tiles = plan_tiles(w, h, cols, rows)
    assert len(tiles) == cols * rows
    assert min(t.box[0] for t in tiles) == 0 and min(t.box[1] for t in tiles) == 0
    assert max(t.box[2] for t in tiles) == w and max(t.box[3] for t in tiles) == h
    covered = [[False] * 50 for _ in range(50)]
    for t in tiles:
        for i in range(50):
            for j in range(50):
                if t.box[0] <= (i + .5) * w / 50 < t.box[2] and t.box[1] <= (j + .5) * h / 50 < t.box[3]:
                    covered[i][j] = True
    assert all(all(row) for row in covered)
    if cols > 1:
        a, b = tiles[0], tiles[1]
        assert (a.box[2] - b.box[0]) / (a.box[2] - a.box[0]) == pytest.approx(0.25, abs=0.02)
        assert a.inner_right and b.inner_left and not a.inner_left


def test_boxes_touching_an_inner_edge_are_cut_off_but_image_borders_are_not():
    t = Tile(0, (0, 0, 1000, 800), False, False, True, True)
    assert _cut_by_tile(O(1, Category.led, (900, 100, 1000, 150)), t)  # touches inner right
    assert _cut_by_tile(O(2, Category.led, (100, 750, 150, 800)), t)  # touches inner bottom
    assert not _cut_by_tile(O(3, Category.led, (0, 0, 50, 50)), t)  # image corner
    assert not _cut_by_tile(O(4, Category.led, (400, 300, 450, 340)), t)


def test_merge_drops_same_category_duplicates_and_contained_boxes_but_keeps_other_categories():
    kept = [O(1, Category.gpio_header, (100, 100, 1000, 200))]
    new = [
        O(2, Category.gpio_header, (110, 105, 990, 195)),  # duplicate (IoU)
        O(3, Category.gpio_header, (300, 120, 400, 180)),  # inside the kept header
        O(4, Category.resistor, (300, 120, 400, 180)),  # different category: kept
        O(5, Category.gpio_header, (2000, 100, 2100, 200)),  # elsewhere: kept
    ]
    merged, dupes = merge(kept, new)
    assert dupes == 2 and [o.id for o in merged] == ["o1", "o4", "o5"]


def tile_responder(calls):
    def respond(req):
        calls.append(req.prompt)
        if "zoomed section" in req.prompt:
            # a small resistor at the middle of whichever tile it is shown, and one cut by the left edge
            return json.dumps([
                {"label": "resistor", "category": "resistor", "bbox_2d": [480, 480, 520, 520], "readable": False},
                {"label": "cut part", "category": "led", "bbox_2d": [0, 400, 30, 450], "readable": False},
            ])
        return json.dumps([{"label": "chip", "category": "ic_package", "bbox_2d": [454, 408, 553, 574], "readable": False}])
    return respond


def test_tiled_pass_adds_small_parts_in_original_coordinates_and_drops_edge_cuts(photo):
    calls = []
    r = run_overview_tiled(photo, MockAdapter(tile_responder(calls)), image_id="x", grid=(3, 2))
    assert len(calls) == 1 + 6 and r.tiles["ok"] == 6 and r.tiles["failed"] == 0
    res = [o for o in r.observations if o.category.value == "resistor"]
    # The tile centres are far apart, so none are duplicates. This photo has a flat patch where one
    # synthetic box lands; the blank-area guard drops it and says so.
    blank = sum(int(d.split()[0]) for d in r.dropped if "over a blank area" in d)
    assert len(res) + blank == 6 and blank <= 1
    t4 = plan_tiles(2752, 1536, 3, 2)[4].box
    cx, cy = (t4[0] + t4[2]) / 2, (t4[1] + t4[3]) / 2
    assert blank or any(abs((o.bbox[0] + o.bbox[2]) / 2 - cx) < 3 and abs((o.bbox[1] + o.bbox[3]) / 2 - cy) < 3 for o in res)
    leds = [o for o in r.observations if o.category.value == "led"]
    assert len(leds) == 2  # only tiles whose left edge is the image border keep the box at x=0
    assert r.tiles["cut_by_edge"] == 4 and r.observations[0].category.value == "ic_package"
    assert [o.id for o in r.observations] == [f"obs_{i:03d}" for i in range(len(r.observations))]


def test_a_tile_that_gives_junk_is_skipped_with_a_warning_and_the_overview_survives(photo):
    def respond(req):
        return "no json here" if "zoomed section" in req.prompt else json.dumps([{"label": "chip", "category": "ic_package", "bbox_2d": [454, 408, 553, 574], "readable": False}])

    r = run_overview_tiled(photo, MockAdapter(respond), image_id="x", grid=(2, 2))
    assert len(r.observations) == 1 and r.tiles["failed"] == 4
    assert sum("was skipped" in w for w in r.warnings) == 4


def test_model_server_dying_mid_tiles_stops_the_pass_but_keeps_the_overview(photo):
    n = {"i": 0}

    def respond(req):
        n["i"] += 1
        if n["i"] >= 3:
            raise AdapterError("model_unavailable", "The local model server is not reachable.")
        return json.dumps([{"label": "chip", "category": "ic_package", "bbox_2d": [454, 408, 553, 574], "readable": False}])

    r = run_overview_tiled(photo, MockAdapter(respond), image_id="x", grid=(2, 2))
    # overview + the first tile succeeded, the second tile hit the dead server and the rest were skipped
    assert r.tiles["stopped"] and r.tiles["ok"] == 1 and r.tiles["failed"] == 1 and len(r.observations) == 2
    assert any("remaining sections were skipped" in w for w in r.warnings)


def test_tiled_pass_stops_when_asked(photo):
    r = run_overview_tiled(photo, MockAdapter(tile_responder([])), image_id="x", grid=(2, 2), should_stop=lambda: True)
    assert r.tiles["stopped"] and r.tiles["ok"] == 0


# ---- through the API --------------------------------------------------------------------------


def test_api_reports_tiles_and_warnings(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    from .test_api import analyze, upload, wait

    st = Settings(adapter="mock", data_dir=tmp_path, frontend_dist=None, tiles="2x2", detail_pass=False)
    with TestClient(create_app(st, MockAdapter(tile_responder([]), done_reason="length"))) as c:
        done = wait(c, analyze(c, upload(c)["image_id"]), timeout=15)
        assert done["tiles"]["planned"] == 4 and done["tiles"]["ok"] == 4
        assert any("cut off" in w for w in done["warnings"])


def test_blank_and_double_chip_guards_on_the_real_tiled_output():
    """The 2x2 tiled run on samples/test_a_closeup.jpg (laptop, v7): one capacitor drawn on the white banner and
    four chips boxed under two categories."""
    from PIL import Image
    from app.guards import drop_blank_boxes, merge_same_chip

    photo = Image.open(HERE.parents[1] / "samples" / "test_a_closeup.jpg").convert("RGB")
    obs = [O(0, Category.capacitor, (239, 36, 261, 68)), O(1, Category.capacitor, (239, 100, 261, 131)),
           O(2, Category.ic_package, (225, 325, 269, 376)), O(3, Category.microcontroller_module, (226, 325, 267, 377)),
           O(4, Category.ic_package, (117, 128, 199, 203))]
    kept, reasons = drop_blank_boxes(obs, photo)
    assert [o.id for o in kept] == ["o1", "o2", "o3", "o4"] and "blank area" in reasons[0]
    kept, reasons = merge_same_chip(kept)
    assert [o.id for o in kept] == ["o1", "o2", "o4"] and "twice" in reasons[0]
