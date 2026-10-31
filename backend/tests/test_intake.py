import io

import pytest
from PIL import Image

from app.geometry import view_to_original
from app.intake import IntakeError, IntakeLimits, make_crop, prepare_image


def jpeg_bytes(size=(1600, 1200), color=(30, 120, 60), orientation=None, fmt="JPEG"):
    img = Image.new("RGB", size, color)
    # texture so the blur heuristic has something to measure
    px = img.load()
    for x in range(0, size[0], 8):
        for y in range(0, size[1], 8):
            if (x // 8 + y // 8) % 2:
                px[x, y] = (200, 200, 200)
    buf = io.BytesIO()
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    img.save(buf, format=fmt, exif=exif if orientation else b"")
    return buf.getvalue()


def test_rejects_garbage_and_empty():
    with pytest.raises(IntakeError) as e:
        prepare_image(b"not an image at all")
    assert e.value.code == "not_an_image"
    with pytest.raises(IntakeError) as e:
        prepare_image(b"")
    assert e.value.code == "empty"


def test_extension_is_irrelevant_content_is_decoded():
    # a PNG is accepted regardless of what the client called it
    prep = prepare_image(jpeg_bytes(fmt="PNG"))
    assert prep.original_format == "PNG"


def test_size_and_pixel_limits():
    with pytest.raises(IntakeError) as e:
        prepare_image(jpeg_bytes(), IntakeLimits(max_bytes=1000))
    assert e.value.code == "too_large"
    with pytest.raises(IntakeError) as e:
        prepare_image(jpeg_bytes(), IntakeLimits(max_pixels=1000))
    assert e.value.code == "too_many_pixels"
    with pytest.raises(IntakeError) as e:
        prepare_image(jpeg_bytes(size=(200, 150)))
    assert e.value.code == "too_small"


@pytest.mark.parametrize("orientation,expected", [(1, (1600, 1200)), (6, (1200, 1600)), (8, (1200, 1600)), (3, (1600, 1200))])
def test_exif_orientation_applied(orientation, expected):
    prep = prepare_image(jpeg_bytes(orientation=orientation))
    assert prep.size == expected
    assert prep.exif_orientation == orientation


def test_analysis_view_maps_back_to_original():
    prep = prepare_image(jpeg_bytes(size=(4000, 3000)), IntakeLimits(analysis_long_side=1000))
    assert prep.analysis.size == (1000, 750)
    full = view_to_original((0, 0, 1000, 750), prep.analysis_view)
    assert full == pytest.approx((0, 0, 4000, 3000))


def test_crop_normalises_and_maps_back():
    prep = prepare_image(jpeg_bytes(size=(2000, 1500)))
    crop, view = make_crop(prep, (500, 400, 700, 500), out_long_side=800)
    assert max(crop.size) == 800
    back = view_to_original((0, 0, crop.size[0], crop.size[1]), view)
    # integer crop bounds + rounding allow a pixel of slack
    assert back == pytest.approx((500, 400, 700, 500), abs=1.5)


def test_quality_flags_flat_dark_image():
    img = Image.new("RGB", (800, 600), (5, 5, 5))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    prep = prepare_image(buf.getvalue())
    assert not prep.quality.ok
    assert any("dark" in p for p in prep.quality.problems)
    assert any("blurry" in p for p in prep.quality.problems)
