from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.adapters import MockAdapter, ModelUnavailable
from app.config import Settings
from app.detail import (
    CLOSE_UP_CONTRADICTS,
    CLOSE_UP_UNREADABLE,
    DetailRead,
    MAX_PARTS,
    merge_detail,
    read_detail,
    run_detail_pass,
    select_for_detail,
)
from app.intake import prepare_image
from app.main import create_app
from app.parsing import ModelOutputError
from app.schemas import Candidate, IdStatus, Observation, Source

from .test_api import analyze, make_jpeg, upload, wait


def O(i="o1", cat="ic_package", box=(100, 100, 300, 260), **kw):
    kw.setdefault("evidence", ["Model saw: chip"])
    return Observation(id=i, image_id="img", category=cat, bbox=box, **kw)


def tentative(marking="OLD123"):
    return O(marking_text=marking, status=IdStatus.tentative, candidates=[Candidate(identity="Old part")],
             evidence=["Model saw: chip", f"Marking read by the model (unverified): {marking}"])


def prepared():
    return prepare_image(make_jpeg(1600, 1200))


def reply(marking=None, readable=False, guess=None, box=(0, 0, 1000, 1000)):
    return json.dumps([{"label": "chip", "category": "ic_package", "bbox_2d": list(box),
                        "marking_text": marking, "identity_guess": guess, "readable": readable}])


# ---- selection ------------------------------------------------------------------------------


def test_only_chips_big_enough_to_read_are_selected_largest_first_and_capped():
    obs = [O("a", box=(0, 0, 40, 40)), O("b", box=(0, 0, 300, 300)), O("tiny", box=(0, 0, 10, 80)),
           O("cap", cat="capacitor", box=(0, 0, 300, 300)), O("c", cat="microcontroller_module", box=(0, 0, 100, 100))]
    assert [o.id for o in select_for_detail(obs)] == ["b", "c", "a"]
    many = [O(f"x{i}", box=(0, 0, 100 + i, 100 + i)) for i in range(MAX_PARTS + 4)]
    assert len(select_for_detail(many)) == MAX_PARTS
    assert select_for_detail([O("u", source=Source.user)]) == []


# ---- merge rules ----------------------------------------------------------------------------


def test_readable_close_up_gives_a_tentative_unverified_marking_and_keeps_the_box():
    o = merge_detail(O(), DetailRead(True, "STM32F407VGT6", "STM32F407", None, 1.0))
    assert o.status == IdStatus.tentative and o.marking_text == "STM32F407VGT6"
    assert o.reference_ids == [] and o.source == Source.vlm and o.bbox == (100, 100, 300, 260)
    assert o.candidates[0].identity == "STM32F407" and o.candidates[0].reference_id is None
    assert any("close-up by the model (unverified): STM32F407VGT6" in e for e in o.evidence)


def test_close_up_replaces_the_first_pass_marking_and_says_they_differed():
    o = merge_detail(tentative("OLD123"), DetailRead(True, "NEW456", None, None, 1.0))
    assert o.marking_text == "NEW456" and o.candidates == []
    assert not any(e.startswith("Marking read by the model") for e in o.evidence)
    assert any("'OLD123'" in m and "'NEW456'" in m for m in o.limitations)


def test_unreadable_close_up_drops_a_first_pass_marking():
    o = merge_detail(tentative("OLD123"), DetailRead(False, None, None, None, 1.0))
    assert o.status == IdStatus.unknown and o.marking_text is None and o.candidates == []
    assert CLOSE_UP_CONTRADICTS in o.limitations and CLOSE_UP_UNREADABLE in o.limitations
    assert not any("OLD123" in e for e in o.evidence)


def test_unreadable_close_up_on_an_unknown_part_only_adds_the_limitation():
    o = merge_detail(O(), DetailRead(False, None, None, None, 1.0))
    assert o.status == IdStatus.unknown and o.limitations == [CLOSE_UP_UNREADABLE]


def test_a_close_up_can_never_confirm_a_part():
    o = merge_detail(O(), DetailRead(True, "LM358", "LM358", None, 1.0))
    assert o.status != IdStatus.confirmed


# ---- reading --------------------------------------------------------------------------------


def test_crop_sent_to_the_model_is_one_scaled_crop_of_the_original_not_the_overview():
    seen = []

    def responder(req):
        seen.append(Image.open(io.BytesIO(req.images[0])).size)
        return reply("LM358", True)

    read = read_detail(prepared(), MockAdapter(responder), O(box=(200, 200, 500, 380)))
    assert read.marking == "LM358" and len(seen) == 1
    assert max(seen[0]) == 768  # normalised to the crop size, from the 1600 px original


def test_box_in_the_close_up_reply_is_ignored():
    o = merge_detail(O(), read_detail(prepared(), MockAdapter(lambda r: reply("LM358", True, box=(5, 5, 20, 20))), O()))
    assert o.bbox == (100, 100, 300, 260)


def test_marking_the_model_says_it_could_not_read_is_discarded():
    read = read_detail(prepared(), MockAdapter(lambda r: reply("ZZ99", False)), O())
    assert read.marking is None and read.readable is False


def test_unusable_reply_gets_one_repair_then_raises():
    calls = []

    def junk(req):
        calls.append(req.prompt)
        return "it says LM358"

    with pytest.raises(ModelOutputError):
        read_detail(prepared(), MockAdapter(junk), O())
    assert len(calls) == 2 and "could not be used" in calls[1]


def test_pass_keeps_overview_results_when_a_close_up_fails_and_stops_if_the_model_is_gone():
    obs = [O("a", box=(0, 0, 300, 300)), O("b", box=(0, 0, 200, 200))]
    out, s = run_detail_pass(prepared(), MockAdapter(lambda r: "junk"), obs)
    assert s["failed"] == 2 and s["attempted"] == 2 and [o.id for o in out] == ["a", "b"]
    assert all("close-up read failed" in o.limitations[-1] for o in out)

    def down(req):
        raise ModelUnavailable()

    _, s = run_detail_pass(prepared(), MockAdapter(down), obs)
    assert s["attempted"] == 1 and s["failed"] == 1 and s["stopped"] is True


def test_pass_stops_when_asked():
    _, s = run_detail_pass(prepared(), MockAdapter(lambda r: reply("A", True)), [O("a")], should_stop=lambda: True)
    assert s["stopped"] is True and s["attempted"] == 0


# ---- through the API ------------------------------------------------------------------------


def chip_overview():
    return json.dumps([{"label": "chip", "category": "ic_package", "bbox_2d": [400, 300, 620, 520], "readable": False}])


def serve(tmp_path, responder, **kw):
    st = Settings(adapter="mock", data_dir=tmp_path, frontend_dist=None, **kw)
    return TestClient(create_app(st, MockAdapter(responder)))


def test_analysis_runs_the_close_up_and_reports_it(tmp_path):
    prompts = []

    def responder(req):
        prompts.append(req.prompt[:20])
        return reply("LM358", True, "LM358") if req.prompt.startswith("This is a close-up") else chip_overview()

    with serve(tmp_path, responder) as c:
        done = wait(c, analyze(c, upload(c)["image_id"]))
        o = done["observations"][0]
        assert o["marking_text"] == "LM358" and o["status"] == "tentative" and o["reference_ids"] == []
        assert done["detail_pass"]["read"] == 1 and len(prompts) == 2


def test_close_up_pass_can_be_turned_off(tmp_path):
    prompts = []

    def responder(req):
        prompts.append(req.prompt[:20])
        return chip_overview()

    with serve(tmp_path, responder, detail_pass=False) as c:
        done = wait(c, analyze(c, upload(c)["image_id"]))
        assert len(prompts) == 1 and done["detail_pass"] is None and done["observations"][0]["marking_text"] is None


def test_failed_close_up_does_not_fail_the_analysis(tmp_path):
    def responder(req):
        return "nonsense" if req.prompt.startswith("This is a close-up") else chip_overview()

    with serve(tmp_path, responder) as c:
        done = wait(c, analyze(c, upload(c)["image_id"]))
        assert done["status"] == "done" and done["detail_pass"]["failed"] == 1
        assert done["observations"][0]["status"] == "unknown"


def test_default_mock_answers_close_ups_as_not_readable(tmp_path):
    with TestClient(create_app(Settings(adapter="mock", data_dir=tmp_path, frontend_dist=None), MockAdapter())) as c:
        done = wait(c, analyze(c, upload(c)["image_id"]))
        chip = next(o for o in done["observations"] if o["category"] == "ic_package")
        assert chip["marking_text"] is None and done["is_mock"] is True


# ---- the real sample photo ------------------------------------------------------------------

SAMPLES = Path(__file__).resolve().parent / "fixtures" / "ai_board"


def test_sample_photo_crop_for_the_main_chip_comes_from_the_original_resolution():
    truth = json.loads((SAMPLES / "board_01.truth.json").read_text())
    mcu = next(p for p in truth["parts"] if p["name"] == "mcu_qfp100")
    p = prepare_image((SAMPLES / "board_01.png").read_bytes())
    assert p.size == (truth["width"], truth["height"])
    obs = O("mcu", box=tuple(mcu["bbox"]))
    seen = []

    def responder(req):
        seen.append(Image.open(io.BytesIO(req.images[0])).size)
        return reply(None, False)

    read_detail(p, MockAdapter(responder), obs)
    chip_w = mcu["bbox"][2] - mcu["bbox"][0]
    assert chip_w > 250 and max(seen[0]) == 768
