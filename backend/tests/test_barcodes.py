"""Tests for the barcode decode service.

Two layers, both DB-free (consistent with the rest of this suite):

1. Logic tests with `pyzbar.decode` monkeypatched -- exercise the
   format mapping, raw pass-through of uncatalogued formats, dedupe,
   and the unreadable-image error without depending on the native decoder.
2. End-to-end tests against committed PNG fixtures under
   `tests/fixtures/` -- exercise the real pyzbar pipeline (and so also
   confirm the native zbar library is wired up correctly).
"""

import os
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PIL import Image

from app.services import barcodes
from app.domain.errors import UnreadableImageError

FIXTURES = Path(__file__).parent / "fixtures"


class FakeSymbol:
    """Stand-in for a pyzbar `Decoded` result: only `.type`/`.data` used."""

    def __init__(self, type_, data):
        self.type = type_
        self.data = data


def _valid_png_bytes():
    """A real (blank) PNG so `decode_image` gets past `Image.open`; the
    monkeypatched `pyzbar.decode` ignores the pixels."""
    buf = BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, format="PNG")
    return buf.getvalue()


def _patch_decode(monkeypatch, fake_results):
    # The service calls `pyzbar.decode(image, symbols=...)`; ignore that
    # kwarg and return the closed-over fakes (don't name the lambda param
    # `symbols` -- it would shadow `fake_results`).
    monkeypatch.setattr(
        barcodes.pyzbar, "decode", lambda image, symbols=None: fake_results
    )


# --- Logic tests (monkeypatched decoder) -----------------------------

def test_maps_native_types_to_canonical(monkeypatch):
    _patch_decode(monkeypatch, [
        FakeSymbol("UPCA", b"036000291452"),
        FakeSymbol("EAN13", b"5901234123457"),
        FakeSymbol("CODE128", b"ABC12345"),
    ])
    out = barcodes.decode_image(_valid_png_bytes())
    assert [(m.text, m.format) for m in out] == [
        ("036000291452", "UPC_A"),
        ("5901234123457", "EAN_13"),
        ("ABC12345", "CODE_128"),
    ]


def test_maps_extended_formats_to_canonical(monkeypatch):
    # Formats beyond the original five now decode, mapped to the
    # ZXing-consistent canonical names.
    _patch_decode(monkeypatch, [
        FakeSymbol("CODE39", b"PART-001"),
        FakeSymbol("CODE93", b"PART-002"),
        FakeSymbol("CODABAR", b"A1234B"),
        FakeSymbol("I25", b"1234567890"),
        FakeSymbol("DATABAR", b"0100000000000017"),
        FakeSymbol("QRCODE", b"https://example.com"),
    ])
    out = barcodes.decode_image(_valid_png_bytes())
    assert [(m.text, m.format) for m in out] == [
        ("PART-001", "CODE_39"),
        ("PART-002", "CODE_93"),
        ("A1234B", "CODABAR"),
        ("1234567890", "ITF"),
        ("0100000000000017", "RSS_14"),
        ("https://example.com", "QR_CODE"),
    ]


def test_uncatalogued_type_passes_through_raw(monkeypatch):
    # A symbology with no _FORMAT_MAP entry is reported under its raw
    # zbar name rather than dropped.
    _patch_decode(monkeypatch, [
        FakeSymbol("SQCODE", b"SQ-PAYLOAD"),
        FakeSymbol("CODE128", b"KEEP"),
    ])
    out = barcodes.decode_image(_valid_png_bytes())
    assert [(m.text, m.format) for m in out] == [
        ("SQ-PAYLOAD", "SQCODE"),
        ("KEEP", "CODE_128"),
    ]


def test_dedupes_repeated_symbols(monkeypatch):
    _patch_decode(monkeypatch, [
        FakeSymbol("EAN13", b"5901234123457"),
        FakeSymbol("EAN13", b"5901234123457"),
    ])
    out = barcodes.decode_image(_valid_png_bytes())
    assert len(out) == 1
    assert (out[0].text, out[0].format) == ("5901234123457", "EAN_13")


def test_readable_image_no_barcode_returns_empty(monkeypatch):
    _patch_decode(monkeypatch, [])
    assert barcodes.decode_image(_valid_png_bytes()) == []


def test_unreadable_bytes_raise():
    with pytest.raises(UnreadableImageError):
        barcodes.decode_image(b"this is not an image")


# --- End-to-end tests (real pyzbar + committed fixtures) -------------

@pytest.mark.parametrize("filename,expected", [
    ("code128.png", ("ABC12345", "CODE_128")),
    ("ean13.png", ("5901234123457", "EAN_13")),
    ("ean8.png", ("96385074", "EAN_8")),
    ("upca.png", ("036000291452", "UPC_A")),
])
def test_real_fixture_decodes(filename, expected):
    data = (FIXTURES / filename).read_bytes()
    out = barcodes.decode_image(data)
    assert expected in [(m.text, m.format) for m in out]


def test_multi_barcode_fixture_returns_two():
    data = (FIXTURES / "multi.png").read_bytes()
    out = barcodes.decode_image(data)
    found = {(m.text, m.format) for m in out}
    assert ("MULTI-A-001", "CODE_128") in found
    assert ("4006381333931", "EAN_13") in found
