"""Barcode decoding service.

Layer: services. Called by `app/routers/barcodes.py`. Decodes an
uploaded image entirely in memory and returns the barcodes found --
nothing is written to disk or to the database.

Decoder: `pyzbar` (a ctypes wrapper around the native `zbar` library).
`zbar` reads many symbologies; this service deliberately restricts to
the five formats supported for v1 and normalises `zbar`'s native type
names (e.g. `"UPCA"`) to the canonical wire vocabulary (e.g. `"UPC_A"`)
so the API contract does not leak the decoder choice.

Note for operators: on Windows, `pyzbar` needs the Visual C++ 2013
runtime (`msvcr120.dll`); without it the import fails with a missing
`libiconv.dll`/`libzbar-64.dll`. See `docs/reference.md`.
"""

from io import BytesIO

from PIL import Image, UnidentifiedImageError
from pyzbar import pyzbar
from pyzbar.pyzbar import ZBarSymbol

from app.domain.errors import UnreadableImageError
from app.schemas.barcodes import BarcodeMatch

# zbar native type name -> canonical wire format. Only these five are
# supported in v1; any other symbology zbar happens to read (QR, Code39,
# ITF, Codabar, ...) is dropped because it is not in this map.
_FORMAT_MAP: dict[str, str] = {
    "UPCA": "UPC_A",
    "UPCE": "UPC_E",
    "EAN13": "EAN_13",
    "EAN8": "EAN_8",
    "CODE128": "CODE_128",
}

# Restrict the decoder to the supported symbologies up front. This both
# speeds up decoding and avoids spending effort on symbols we would only
# discard afterwards.
_SUPPORTED_SYMBOLS = [
    ZBarSymbol.UPCA,
    ZBarSymbol.UPCE,
    ZBarSymbol.EAN13,
    ZBarSymbol.EAN8,
    ZBarSymbol.CODE128,
]


def decode_image(data: bytes) -> list[BarcodeMatch]:
    """Decode every supported barcode in the image bytes `data`.

    Returns a list of `BarcodeMatch` (possibly empty if the image is
    readable but contains no supported symbol). Raises
    `UnreadableImageError` if the bytes are not a decodable image.

    Duplicate detections of the same `(text, format)` are collapsed --
    zbar can report the same symbol more than once -- while preserving
    first-seen order so a chooser in the UI stays stable.
    """
    try:
        image = Image.open(BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise UnreadableImageError("The uploaded file is not a readable image.") from exc

    results = pyzbar.decode(image, symbols=_SUPPORTED_SYMBOLS)

    matches: list[BarcodeMatch] = []
    seen: set[tuple[str, str]] = set()
    for symbol in results:
        canonical = _FORMAT_MAP.get(symbol.type)
        if canonical is None:
            continue
        text = symbol.data.decode("utf-8", errors="replace")
        key = (text, canonical)
        if key in seen:
            continue
        seen.add(key)
        matches.append(BarcodeMatch(text=text, format=canonical))

    return matches
