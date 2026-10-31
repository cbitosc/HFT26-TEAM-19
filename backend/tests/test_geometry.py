import math

import pytest

from app.geometry import (
    DisplayTransform,
    GeometryError,
    ImageView,
    clamp_box,
    display_to_original,
    iou,
    is_whole_image,
    model_box_to_original,
    normalized_to_view,
    original_to_display,
    original_to_view,
    pad_box,
    view_to_original,
)


def close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_rejects_non_finite_and_misordered():
    for bad in [(0, 0, math.nan, 5), (0, 0, math.inf, 5), (5, 5, 5, 10), (10, 0, 5, 5), (0, 0, 1)]:
        with pytest.raises(GeometryError):
            clamp_box(bad, 100, 100)


def test_clamp_inside_and_outside():
    assert clamp_box((-10, -10, 50, 50), 100, 100) == (0, 0, 50, 50)
    with pytest.raises(GeometryError):
        clamp_box((120, 120, 150, 150), 100, 100)


def test_resized_view_round_trip():
    view = ImageView.resized(4000, 3000, 1280, 960)
    box = (400, 300, 1600, 1200)
    assert close(view_to_original(original_to_view(box, view), view), box)


def test_crop_view_round_trip_and_offsets():
    view = ImageView.crop((1000, 500, 1400, 800), 800, 600)  # 2x upscale
    assert view.scale == pytest.approx(2.0)
    # a box at crop pixels (0,0)-(800,600) is the whole crop in original space
    assert close(view_to_original((0, 0, 800, 600), view), (1000, 500, 1400, 800))
    box = (1100, 550, 1200, 650)
    assert close(view_to_original(original_to_view(box, view), view), box)


def test_crop_with_unequal_axis_scales_rejected():
    with pytest.raises(GeometryError):
        ImageView.crop((0, 0, 400, 300), 800, 900)


def test_model_normalised_to_original_on_analysis_image():
    view = ImageView.resized(4000, 3000, 1280, 960)
    box, conv = model_box_to_original((250, 250, 750, 500), view, 4000, 3000)
    assert conv == "normalized_0_1000"
    assert close(box, (1000, 750, 3000, 1500))


def test_model_normalised_on_crop():
    view = ImageView.crop((1000, 500, 1400, 800), 800, 600)
    # whole-crop box maps to the crop rectangle in original px
    box, _ = model_box_to_original((0, 0, 1000, 1000), view, 4000, 3000)
    assert close(box, (1000, 500, 1400, 800))
    # centre quarter
    box, _ = model_box_to_original((250, 250, 750, 750), view, 4000, 3000)
    assert close(box, (1100, 575, 1300, 725))


def test_pixel_fallback_flagged_and_can_be_disabled():
    view = ImageView(1280, 960)
    box, conv = model_box_to_original((100, 100, 640, 480), view, 1280, 960)
    # 640 <= 1000 so treated as normalised: documents the ambiguity rather than hiding it
    assert conv == "normalized_0_1000"
    box, conv = model_box_to_original((100, 100, 1200, 900), view, 1280, 960)
    assert conv == "view_pixels_fallback"
    assert close(box, (100, 100, 1200, 900))
    with pytest.raises(GeometryError):
        model_box_to_original((100, 100, 1200, 900), view, 1280, 960, allow_pixel_fallback=False)


def test_whole_image_detection():
    assert is_whole_image((0, 0, 1000, 800), 1000, 800)
    assert not is_whole_image((100, 100, 900, 700), 1000, 800)


def test_display_round_trip_with_zoom_and_pan():
    t = DisplayTransform(fit=0.25, zoom=3.0, pan_x=-120.0, pan_y=40.0)
    box = (800, 600, 1200, 900)
    assert close(display_to_original(original_to_display(box, t), t), box, 1e-9)
    # zoom changes size, not identity
    t2 = DisplayTransform(fit=0.25, zoom=1.0)
    w1 = original_to_display(box, t)[2] - original_to_display(box, t)[0]
    w2 = original_to_display(box, t2)[2] - original_to_display(box, t2)[0]
    assert w1 == pytest.approx(3 * w2)


def test_display_rejects_bad_scale():
    with pytest.raises(GeometryError):
        DisplayTransform(fit=0.0)


def test_iou_and_pad():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(1 / 3)
    assert pad_box((10, 10, 20, 20), 0.5, 100, 100) == (5, 5, 25, 25)
    assert pad_box((0, 0, 20, 20), 0.5, 100, 100)[0] == 0
