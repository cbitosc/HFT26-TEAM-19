"""Image intake: decode, validate, orient, quality-check, derive analysis copies.

* Validation is by decoding content with Pillow, never by file extension.
* The original bytes are kept untouched by the caller; this module returns an
  EXIF-oriented RGB copy plus a downscaled analysis copy and the matching ImageView.
* Quality checks use OpenCV when available and fall back to numpy, so tests run anywhere.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .geometry import ImageView

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "BMP", "MPO"}


class IntakeError(ValueError):
    """Upload rejected; ``code`` is stable for the API and tests."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class IntakeLimits:
    max_bytes: int = 25 * 1024 * 1024
    max_pixels: int = 60_000_000  # decoded size cap, guards decompression bombs
    min_side: int = 320
    analysis_long_side: int = 1280
    analysis_min_long_side: int = 1024  # small photos are enlarged for the model; boxes still map to the original


@dataclass
class QualityReport:
    sharpness: float
    brightness: float
    clipped_dark: float
    clipped_bright: float
    ok: bool
    problems: list[str] = field(default_factory=list)  # user-facing retake advice


@dataclass
class PreparedImage:
    original: Image.Image  # EXIF-oriented RGB, original pixel space
    analysis: Image.Image  # downscaled copy for the overview pass
    analysis_view: ImageView
    original_format: str
    exif_orientation: int
    quality: QualityReport

    @property
    def size(self) -> tuple[int, int]:
        return self.original.size


def _laplacian_variance(gray: np.ndarray) -> float:
    try:
        import cv2  # type: ignore

        return float(cv2.Laplacian(gray, cv2.CV_64F).var())
    except Exception:  # pragma: no cover - numpy fallback
        g = gray.astype(np.float64)
        lap = (
            -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
        )
        return float(lap.var())


def assess_quality(img: Image.Image, *, blur_threshold: float = 60.0) -> QualityReport:
    """Cheap heuristics; thresholds are starting points to tune on real photos."""
    # Measure sharpness on a fixed-size copy so the score does not depend on resolution.
    small = ImageOps.contain(img.convert("L"), (800, 800))
    gray = np.asarray(small)
    sharp = _laplacian_variance(gray)
    brightness = float(gray.mean())
    dark = float((gray < 10).mean())
    bright = float((gray > 245).mean())
    problems: list[str] = []
    if sharp < blur_threshold:
        problems.append("Image looks blurry: hold the camera steady or tap to focus, then retake.")
    if brightness < 50 or dark > 0.4:
        problems.append("Image is too dark: add light (a desk lamp helps) and retake.")
    if brightness > 215 or bright > 0.3:
        problems.append("Image is overexposed or has strong glare: tilt the board or soften the light.")
    return QualityReport(
        sharpness=round(sharp, 2),
        brightness=round(brightness, 1),
        clipped_dark=round(dark, 4),
        clipped_bright=round(bright, 4),
        ok=not problems,
        problems=problems,
    )


def prepare_image(data: bytes, limits: IntakeLimits = IntakeLimits()) -> PreparedImage:
    if not data:
        raise IntakeError("empty", "The upload is empty.")
    if len(data) > limits.max_bytes:
        raise IntakeError("too_large", f"File is larger than {limits.max_bytes // (1024 * 1024)} MB.")
    try:
        probe = Image.open(io.BytesIO(data))
        fmt = (probe.format or "").upper()
        probe.verify()  # structural check; image must be re-opened afterwards
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise IntakeError("not_an_image", "The file could not be decoded as an image.") from exc
    if fmt not in ALLOWED_FORMATS:
        raise IntakeError("unsupported_format", f"Format {fmt or 'unknown'} is not supported. Use JPEG or PNG.")

    img = Image.open(io.BytesIO(data))
    w0, h0 = img.size
    if w0 * h0 > limits.max_pixels:
        raise IntakeError("too_many_pixels", f"Image is {w0}x{h0}; the limit is {limits.max_pixels:,} pixels.")
    try:
        orientation = int(img.getexif().get(0x0112, 1))
        img = ImageOps.exif_transpose(img)  # applies and strips the orientation tag
        img = img.convert("RGB")
        img.load()
    except (OSError, ValueError) as exc:
        raise IntakeError("decode_failed", "The image data is corrupt.") from exc

    w, h = img.size
    if min(w, h) < limits.min_side:
        raise IntakeError("too_small", f"Image is {w}x{h}; at least {limits.min_side}px on the short side is needed.")

    long_side = max(w, h)
    if long_side > limits.analysis_long_side:
        s = limits.analysis_long_side / long_side
        aw, ah = max(1, round(w * s)), max(1, round(h * s))
        analysis = img.resize((aw, ah), Image.LANCZOS)
        view = ImageView(aw, ah, 0.0, 0.0, aw / w)
    elif long_side < limits.analysis_min_long_side:
        # A 500 px photo gives a 4B model only a few image tokens per part, so enlarge it first.
        s = limits.analysis_min_long_side / long_side
        aw, ah = max(1, round(w * s)), max(1, round(h * s))
        analysis = img.resize((aw, ah), Image.LANCZOS)
        view = ImageView(aw, ah, 0.0, 0.0, aw / w)
    else:
        analysis = img.copy()
        view = ImageView(w, h, 0.0, 0.0, 1.0)

    return PreparedImage(
        original=img,
        analysis=analysis,
        analysis_view=view,
        original_format=fmt,
        exif_orientation=orientation,
        quality=assess_quality(img),
    )


def encode_jpeg(img: Image.Image, quality: int = 90) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def make_crop(prepared: PreparedImage, box_original, out_long_side: int = 768) -> tuple[Image.Image, ImageView]:
    """Crop ``box_original`` (original px) and resize to ``out_long_side`` with ONE scale."""
    from .geometry import clamp_box

    x1, y1, x2, y2 = clamp_box(box_original, *prepared.original.size)
    ix1, iy1, ix2, iy2 = int(x1), int(y1), int(np.ceil(x2)), int(np.ceil(y2))
    crop = prepared.original.crop((ix1, iy1, ix2, iy2))
    cw, ch = crop.size
    s = out_long_side / max(cw, ch)
    if s < 1.0 or s > 1.0:  # always normalise crop to out_long_side so small markings get upscaled
        crop = crop.resize((max(1, round(cw * s)), max(1, round(ch * s))), Image.LANCZOS)
    view = ImageView(crop.size[0], crop.size[1], float(ix1), float(iy1), crop.size[0] / cw)
    return crop, view
