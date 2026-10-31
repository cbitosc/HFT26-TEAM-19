"""Coordinate spaces and box transforms for VisionGuard.

Contract (see docs/coordinates.md):

* The ORIGINAL space is the uploaded image after EXIF rotation, in pixels.
  Every box that leaves the backend is in this space (``bbox_space = "original_px"``).
* Any image handed to the model is described by an :class:`ImageView`: its pixel size
  plus where it sits in original space. The mapping is::

      original = view_pixel / scale + (origin_x, origin_y)

  - the whole image resized for analysis: origin (0, 0), scale = analysis_w / original_w
  - a crop: origin = crop top-left in original px, scale = crop_px_per_original_px
* Qwen3-VL style models return ``bbox_2d`` normalised to 0-1000 of the image they were
  given. :func:`model_box_to_original` converts model output straight to original px.
* Display space (browser) is computed only in the frontend; the helpers here mirror the
  same maths so it can be tested.

All functions validate: finite numbers, x1 < x2, y1 < y2, inside the image after clamping.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

Box = tuple[float, float, float, float]  # x1, y1, x2, y2

NORM_MAX = 1000.0


class GeometryError(ValueError):
    """Raised for non-finite, mis-ordered, degenerate or out-of-range boxes."""


@dataclass(frozen=True)
class ImageView:
    """An image as the model sees it, positioned inside original space."""

    width: int
    height: int
    origin_x: float = 0.0
    origin_y: float = 0.0
    scale: float = 1.0  # view pixels per original pixel

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise GeometryError("view size must be positive")
        if not math.isfinite(self.scale) or self.scale <= 0:
            raise GeometryError("view scale must be a positive finite number")
        if not (math.isfinite(self.origin_x) and math.isfinite(self.origin_y)):
            raise GeometryError("view origin must be finite")

    @classmethod
    def resized(cls, original_w: int, original_h: int, analysis_w: int, analysis_h: int) -> "ImageView":
        """Whole original image resized to analysis size (aspect ratio preserved by caller)."""
        sx = analysis_w / original_w
        sy = analysis_h / original_h
        if abs(sx - sy) > 0.01 * max(sx, sy):
            raise GeometryError("analysis image changes aspect ratio; resize with a single scale")
        return cls(analysis_w, analysis_h, 0.0, 0.0, sx)

    @classmethod
    def crop(cls, crop_box_original: Box, crop_w: int, crop_h: int) -> "ImageView":
        """A crop taken from original space and sent to the model at crop_w x crop_h."""
        x1, y1, x2, y2 = _check_finite_ordered(crop_box_original)
        sx = crop_w / (x2 - x1)
        sy = crop_h / (y2 - y1)
        if abs(sx - sy) > 0.02 * max(sx, sy):
            raise GeometryError("crop resized with a different scale per axis")
        return cls(crop_w, crop_h, x1, y1, sx)


def _check_finite_ordered(box: Sequence[float]) -> Box:
    if len(box) != 4:
        raise GeometryError("box must have 4 numbers")
    vals = tuple(float(v) for v in box)
    if not all(math.isfinite(v) for v in vals):
        raise GeometryError("box contains a non-finite value")
    x1, y1, x2, y2 = vals
    if x2 <= x1 or y2 <= y1:
        raise GeometryError(f"box is not ordered or has no area: {vals}")
    return vals  # type: ignore[return-value]


def clamp_box(box: Sequence[float], width: float, height: float) -> Box:
    """Validate then clamp to [0,width] x [0,height]; reject if nothing remains."""
    x1, y1, x2, y2 = _check_finite_ordered(box)
    cx1, cy1 = min(max(x1, 0.0), width), min(max(y1, 0.0), height)
    cx2, cy2 = min(max(x2, 0.0), width), min(max(y2, 0.0), height)
    if cx2 <= cx1 or cy2 <= cy1:
        raise GeometryError("box lies outside the image")
    return (cx1, cy1, cx2, cy2)


def is_whole_image(box: Box, width: float, height: float, tolerance: float = 0.01) -> bool:
    x1, y1, x2, y2 = box
    return (
        x1 <= tolerance * width
        and y1 <= tolerance * height
        and x2 >= (1 - tolerance) * width
        and y2 >= (1 - tolerance) * height
    )


def view_to_original(box: Sequence[float], view: ImageView) -> Box:
    """Pixels of ``view`` -> original pixels (not yet clamped)."""
    x1, y1, x2, y2 = _check_finite_ordered(box)
    s = view.scale
    return (x1 / s + view.origin_x, y1 / s + view.origin_y, x2 / s + view.origin_x, y2 / s + view.origin_y)


def original_to_view(box: Sequence[float], view: ImageView) -> Box:
    x1, y1, x2, y2 = _check_finite_ordered(box)
    s = view.scale
    return ((x1 - view.origin_x) * s, (y1 - view.origin_y) * s, (x2 - view.origin_x) * s, (y2 - view.origin_y) * s)


def normalized_to_view(box: Sequence[float], view: ImageView) -> Box:
    """Model 0-1000 coordinates -> pixels of the image the model was given."""
    x1, y1, x2, y2 = _check_finite_ordered(box)
    return (x1 / NORM_MAX * view.width, y1 / NORM_MAX * view.height, x2 / NORM_MAX * view.width, y2 / NORM_MAX * view.height)


def model_box_to_original(
    box: Sequence[float],
    view: ImageView,
    original_w: int,
    original_h: int,
    *,
    allow_pixel_fallback: bool = True,
) -> tuple[Box, str]:
    """Convert one model ``bbox_2d`` to clamped original pixels.

    Returns ``(box, convention)`` where convention is ``"normalized_0_1000"`` or, only if
    ``allow_pixel_fallback`` and a value exceeds 1000, ``"view_pixels_fallback"``. Callers
    should log the fallback: it means the model/runtime is not using the documented convention.
    """
    ordered = _check_finite_ordered(box)
    if max(ordered) <= NORM_MAX:
        in_view = normalized_to_view(ordered, view)
        convention = "normalized_0_1000"
    elif allow_pixel_fallback:
        in_view = ordered
        convention = "view_pixels_fallback"
    else:
        raise GeometryError("coordinates exceed the 0-1000 range")
    # A fallback box can still lie outside the view; clamp to the view first.
    in_view = clamp_box(in_view, view.width, view.height)
    original = view_to_original(in_view, view)
    return clamp_box(original, original_w, original_h), convention


# ---- display helpers (mirrored in frontend/src/lib/geometry.js) -------------------------


@dataclass(frozen=True)
class DisplayTransform:
    """Original px -> CSS px: fit scale, then user zoom, then pan (CSS px)."""

    fit: float
    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0

    def __post_init__(self) -> None:
        for v in (self.fit, self.zoom):
            if not math.isfinite(v) or v <= 0:
                raise GeometryError("fit and zoom must be positive and finite")

    @property
    def k(self) -> float:
        return self.fit * self.zoom


def original_to_display(box: Sequence[float], t: DisplayTransform) -> Box:
    x1, y1, x2, y2 = _check_finite_ordered(box)
    k = t.k
    return (x1 * k + t.pan_x, y1 * k + t.pan_y, x2 * k + t.pan_x, y2 * k + t.pan_y)


def display_to_original(box: Sequence[float], t: DisplayTransform) -> Box:
    x1, y1, x2, y2 = _check_finite_ordered(box)
    k = t.k
    return ((x1 - t.pan_x) / k, (y1 - t.pan_y) / k, (x2 - t.pan_x) / k, (y2 - t.pan_y) / k)


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, ay1, ax2, ay2 = _check_finite_ordered(a)
    bx1, by1, bx2, by2 = _check_finite_ordered(b)
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def pad_box(box: Sequence[float], frac: float, width: float, height: float) -> Box:
    """Grow a box by ``frac`` of its size on each side (for detail crops), clamped."""
    x1, y1, x2, y2 = _check_finite_ordered(box)
    dx, dy = (x2 - x1) * frac, (y2 - y1) * frac
    return clamp_box((x1 - dx, y1 - dy, x2 + dx, y2 + dy), width, height)


def iter_boxes(boxes: Iterable[Sequence[float]]) -> list[Box]:
    return [_check_finite_ordered(b) for b in boxes]
