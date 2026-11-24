"""Pure tests for work-order photo handling (no DB)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io
from datetime import date

import pytest
from PIL import Image

from app.domain.photos import PREVIEW_EDGE, prepare

TODAY = date(2026, 11, 24)


def _image_bytes(fmt: str, size=(1600, 1200), taken: str = None) -> bytes:
    img = Image.new("RGB", size, (200, 30, 30))
    exif = Image.Exif()
    if taken:
        exif.get_ifd(0x8769)[36867] = taken
    buf = io.BytesIO()
    img.save(buf, fmt, exif=exif.tobytes())
    return buf.getvalue()


def test_jpeg_keeps_bytes_and_exif_date():
    raw = _image_bytes("JPEG", taken="2026:10:31 08:15:00")
    original, preview, taken_on = prepare(raw, TODAY)
    assert original == raw
    assert taken_on == date(2026, 10, 31)
    assert max(Image.open(io.BytesIO(preview)).size) <= PREVIEW_EDGE


def test_no_exif_date_falls_back_to_today():
    _, _, taken_on = prepare(_image_bytes("JPEG"), TODAY)
    assert taken_on == TODAY


def test_garbage_rejected():
    with pytest.raises(ValueError):
        prepare(b"not an image at all", TODAY)


def test_heic_becomes_jpeg_with_date():
    raw = _image_bytes("HEIF", size=(900, 600), taken="2026:09:01 12:00:00")
    original, preview, taken_on = prepare(raw, TODAY)
    converted = Image.open(io.BytesIO(original))
    assert converted.format == "JPEG"
    assert converted.size == (900, 600)
    assert taken_on == date(2026, 9, 1)
    assert prepare(original, TODAY)[2] == date(2026, 9, 1)  # EXIF survives conversion
    assert Image.open(io.BytesIO(preview)).format == "JPEG"
