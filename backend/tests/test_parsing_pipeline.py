import io
import json

import pytest
from PIL import Image
from pydantic import ValidationError

from app.adapters import MockAdapter
from app.geometry import ImageView
from app.intake import prepare_image
from app.parsing import ModelOutputError, parse_detections
from app.pipeline import AnalysisFailed, run_overview
from app.schemas import IdStatus, Observation, Source

VIEW = ImageView(1000, 800)


def item(**kw):
    base = {"label": "chip", "category": "ic_package", "bbox_2d": [100, 100, 300, 300], "readable": False}
    base.update(kw)
    return base


def parse(items, **kw):
    return parse_detections(json.dumps(items), view=VIEW, original_w=1000, original_h=800, image_id="img1", **kw)


def test_boxes_become_original_pixels_with_ids():
    r = parse([item()])
    o = r.observations[0]
    assert o.bbox == pytest.approx((100, 80, 300, 240))
    assert o.bbox_space == "original_px"
    assert o.id == "obs_000" and o.image_id == "img1"
    assert o.model_score_note == "uncalibrated"


def test_unreadable_marking_stays_unknown_even_if_model_made_one_up():
    r = parse([item(marking_text="STM32F103", identity_guess="STM32F103C8", readable=False)])
    o = r.observations[0]
    assert o.marking_text is None
    assert o.status == IdStatus.unknown
    assert o.candidates == []
    assert any("not readable" in x.lower() for x in o.limitations)


def test_readable_marking_is_tentative_never_confirmed():
    r = parse([item(marking_text="ESP32-D0WDQ6", identity_guess="Espressif ESP32", readable=True)])
    o = r.observations[0]
    assert o.status == IdStatus.tentative
    assert o.candidates[0].identity == "Espressif ESP32"
    assert o.candidates[0].reference_id is None  # only reference matching may set this


def test_model_observation_cannot_be_confirmed_without_reference():
    with pytest.raises(ValidationError):
        Observation(id="o", image_id="i", category="ic_package", bbox=(0, 0, 5, 5),
                    status="confirmed", source=Source.vlm)
    Observation(id="o", image_id="i", category="ic_package", bbox=(0, 0, 5, 5),
                status="confirmed", source=Source.user)  # a user may confirm


def test_bad_items_are_dropped_not_invented():
    r = parse([
        item(),
        item(bbox_2d=[300, 300, 100, 100]),        # mis-ordered
        item(bbox_2d=[0, 0, 1000, 1000]),          # whole image
        {"label": "x"},                            # missing fields
        item(bbox_2d=[2000, 2000, 3000, 3000]),    # outside the image
    ])
    assert len(r.observations) == 1
    assert len(r.dropped) == 4


def test_unknown_category_becomes_other():
    assert parse([item(category="flux_capacitor")]).observations[0].category.value == "other"


def test_fenced_and_wrapped_json_accepted():
    text = "```json\n" + json.dumps({"detections": [item()]}) + "\n```"
    r = parse_detections(text, view=VIEW, original_w=1000, original_h=800, image_id="i")
    assert len(r.observations) == 1


def test_truncated_json_salvages_complete_items_only():
    text = json.dumps([item(label="a"), item(label="b")])[:-30]  # cut mid second object
    r = parse_detections(text, view=VIEW, original_w=1000, original_h=800, image_id="i")
    assert [o.evidence[0] for o in r.observations] == ["Model saw: a"]


def test_garbage_raises():
    with pytest.raises(ModelOutputError):
        parse_detections("I cannot help with that.", view=VIEW, original_w=1000, original_h=800, image_id="i")
    with pytest.raises(ModelOutputError):
        parse([item(bbox_2d=[5, 5, 1, 1])])  # nothing usable


def make_prepared():
    img = Image.new("RGB", (2000, 1500), (40, 90, 50))
    px = img.load()
    for x in range(0, 2000, 6):
        for y in range(0, 1500, 6):
            if (x // 6 + y // 6) % 2:
                px[x, y] = (220, 220, 220)
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return prepare_image(buf.getvalue())


def test_pipeline_with_mock_is_labelled_and_in_original_space():
    res = run_overview(make_prepared(), MockAdapter(), image_id="t")
    assert res.is_mock and res.model == "MOCK"
    assert len(res.observations) == 2
    # canned header box [60,40,940,120] on a 2000x1500 original
    hdr = [o for o in res.observations if o.category.value == "gpio_header"][0]
    assert hdr.bbox == pytest.approx((120, 60, 1880, 180))


def test_pipeline_repairs_then_succeeds():
    calls = []

    def responder(req):
        calls.append(req.prompt)
        return "nope" if len(calls) == 1 else json.dumps([item()])

    res = run_overview(make_prepared(), MockAdapter(responder), image_id="t")
    assert res.attempts == 2
    assert "could not be used" in calls[1]


def test_pipeline_fails_visibly_after_bounded_retries():
    calls = []

    def responder(req):
        calls.append(1)
        return "still not json"

    with pytest.raises(AnalysisFailed) as e:
        run_overview(make_prepared(), MockAdapter(responder), image_id="t", max_retries=2)
    assert len(calls) == 3  # 1 try + 2 repairs, then stop
    assert len(e.value.attempts) == 3
