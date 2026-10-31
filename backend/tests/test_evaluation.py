import json
from pathlib import Path

from app.evaluation import score

TRUTH = {
    "parts": [
        {"name": "chip", "category": "ic_package", "bbox": [100, 100, 200, 200], "ambiguous": False, "marking": None},
        {"name": "jack", "category": "connector", "bbox": [300, 100, 400, 200], "ambiguous": False, "marking": None},
        {"name": "caps", "category": "capacitor", "bbox": [500, 100, 600, 200], "ambiguous": True, "marking": None},
    ]
}


def obs(i, cat, box, marking=None):
    return {"id": i, "category": cat, "bbox": box, "marking_text": marking, "status": "tentative" if marking else "unknown"}


def test_found_missed_false_positive_and_poor_box():
    s = score(
        TRUTH,
        [
            obs("a", "ic_package", [105, 105, 195, 195]),  # good
            obs("b", "other", [330, 100, 400, 150]),  # overlaps jack at IoU 0.35, wrong category
            obs("c", "led", [800, 800, 850, 850]),  # touches nothing
            obs("d", "resistor", [360, 100, 460, 200]),  # IoU 0.25 with the jack: poor box
        ],
    ).summary()
    assert s["found"] == 2 and s["recall_box"] == 1.0 and s["recall_box_and_category"] == 0.5
    assert s["missed"] == [] and s["false_positives"] == ["c led"] and s["poor_boxes"] == ["d resistor"]


def test_ambiguous_parts_are_never_counted_as_missed():
    s = score(TRUTH, [obs("a", "ic_package", [100, 100, 200, 200])]).summary()
    assert s["missed"] == ["jack"] and s["truth_parts_counted"] == 2


def test_detections_are_matched_one_to_one():
    s = score(TRUTH, [obs("a", "ic_package", [100, 100, 200, 200]), obs("b", "ic_package", [102, 102, 198, 198])]).summary()
    assert s["found"] == 1 and s["poor_boxes"] + s["false_positives"] != []


def test_marking_on_an_unreadable_part_is_flagged_for_a_human_check():
    s = score(TRUTH, [obs("a", "ic_package", [100, 100, 200, 200], marking="STM32F407")]).summary()
    assert s["marking_claims_on_unreadable"][0]["claimed"] == "STM32F407"


def test_shipped_truth_file_is_consistent_with_the_photo_size():
    truth = json.loads((Path(__file__).resolve().parent / "fixtures" / "ai_board" / "board_01.truth.json").read_text())
    for p in truth["parts"]:
        x1, y1, x2, y2 = p["bbox"]
        assert 0 <= x1 < x2 <= truth["width"] and 0 <= y1 < y2 <= truth["height"], p["name"]
