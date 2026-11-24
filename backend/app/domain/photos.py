"""Work-order photo bytes: validate, date, HEIC -> JPEG, preview (pure, no DB)."""

import io
from datetime import date, datetime
from typing import Optional

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()

PREVIEW_EDGE = 800
_DATETIME_ORIGINAL = 36867  # EXIF sub-IFD tag
_EXIF_IFD = 0x8769


def _taken_on(img: Image.Image) -> Optional[date]:
    try:
        raw = img.getexif().get_ifd(_EXIF_IFD).get(_DATETIME_ORIGINAL)
        return datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S").date()
    except (TypeError, ValueError, AttributeError):
        return None


def prepare(raw: bytes, today: date) -> tuple[bytes, bytes, date]:
    """Return (original_jpeg, preview_jpeg, taken_on). Raises ValueError if not an image."""
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:  # Pillow raises several types for bad input
        raise ValueError("Not a readable image.") from exc

    taken_on = _taken_on(img) or today

    if img.format == "JPEG":
        original = raw
    else:
        # HEIC (or PNG etc.): convert once at full resolution, keep EXIF and orientation tag.
        buf = io.BytesIO()
        exif = img.info.get("exif") or img.getexif().tobytes()
        img.convert("RGB").save(buf, "JPEG", quality=95, exif=exif)
        original = buf.getvalue()

    preview_img = ImageOps.exif_transpose(img).convert("RGB")
    preview_img.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE))
    buf = io.BytesIO()
    preview_img.save(buf, "JPEG", quality=75)
    return original, buf.getvalue(), taken_on
