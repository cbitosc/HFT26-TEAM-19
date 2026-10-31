"""The sample truth files are hand-made, so check the things a typo would break."""

import json
from pathlib import Path

import pytest
from PIL import Image

from app.evaluation import marking_result, score
from app.schemas import Category

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
TRUTHS = sorted(SAMPLES.glob("*.truth.json"))


def test_there_is_one_reference_and_at_least_two_held_out_boards():
    roles = [json.loads(p.read_text())["role"] for p in TRUTHS]
    assert roles.count("reference") == 1 and roles.count("held_out") >= 2


@pytest.mark.parametrize("path", TRUTHS, ids=lambda p: p.name)
def test_truth_file_matches_its_photo(path):
    truth = json.loads(path.read_text())
    photo = SAMPLES / truth["image"]
    with Image.open(photo) as im:
        assert im.size == (truth["width"], truth["height"])
    names = [p["name"] for p in truth["parts"]]
    assert len(names) == len(set(names))
    for p in truth["parts"]:
        x1, y1, x2, y2 = p["bbox"]
        assert 0 <= x1 < x2 <= truth["width"] and 0 <= y1 < y2 <= truth["height"], p["name"]
        Category(p["category"])
    assert sum(1 for p in truth["parts"] if not p["ambiguous"]) >= 4


def test_the_reference_board_has_readable_markings_and_a_perfect_answer_scores_perfectly():
    truth = json.loads((SAMPLES / "ref_labelled.truth.json").read_text())
    readable = [p for p in truth["parts"] if p["marking"]]
    assert {p["marking"] for p in readable if not p["ambiguous"]} == {"MT1379GE", "MT1336E", "M12L64164A", "HY29LV800BT"}
    perfect = [
        {"id": f"o{i}", "category": p["category"], "bbox": p["bbox"], "marking_text": p["marking_full"] if p.get("marking_full") else p["marking"], "status": "tentative"}
        for i, p in enumerate(truth["parts"])
    ]
    s = score(truth, perfect).summary()
    assert s["missed"] == [] and s["false_positives"] == [] and s["recall_box_and_category"] == 1.0
    assert s["markings"]["wrong"] == [] and s["markings"]["not_read"] == [] and s["markings"]["not_found"] == []


@pytest.mark.parametrize(
    "expected,claimed,result",
    [
        ("MT1379GE", "MT1379GE 0335-CAB3 F30826", "correct"),
        ("MT1379GE", "mt-1379ge", "correct"),
        ("MT1379GE", "MT1379GF", "near"),  # one character off
        ("MT1379GE", "MT1336E", "wrong"),
        ("M12L64164A", "ESMT M12L64164A", "correct"),
        ("HY29LV800BT", None, "not_read"),
        ("HY29LV800BT", "  ", "not_read"),
        ("SCHNEIDER", "Schneider Electric", "correct"),
    ],
)
def test_marking_results(expected, claimed, result):
    assert marking_result(expected, claimed) == result


def test_a_chip_the_model_never_boxed_is_reported_as_not_found():
    truth = {"parts": [{"name": "chip", "category": "ic_package", "bbox": [0, 0, 100, 100], "ambiguous": False, "marking": "ABC123"}]}
    s = score(truth, []).summary()["markings"]
    assert s["not_found"] == ["chip"] and s["readable_parts"] == 1


def test_a_wrong_reading_on_a_matched_chip_is_reported_as_wrong():
    truth = {"parts": [{"name": "chip", "category": "ic_package", "bbox": [0, 0, 100, 100], "ambiguous": False, "marking": "ABC123"}]}
    obs = [{"id": "o", "category": "ic_package", "bbox": [0, 0, 100, 100], "marking_text": "XYZ999", "status": "tentative"}]
    assert score(truth, obs).summary()["markings"]["wrong"] == ["chip"]
