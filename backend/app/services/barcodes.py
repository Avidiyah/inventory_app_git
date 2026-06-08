"""Barcode decoding service.

Layer: services. Called by `app/routers/barcodes.py`. Decodes an
uploaded image entirely in memory and returns the barcodes found --
nothing is written to disk or to the database.

Decoder: `pyzbar` (a ctypes wrapper around the native `zbar` library).
The warehouse uses many barcode symbologies, so this service reads
*every* symbology the installed `zbar` supports (not a fixed five) and
normalises `zbar`'s native type names (e.g. `"UPCA"`) to a canonical wire
vocabulary (e.g. `"UPC_A"`). The canonical names match the live-capture
decoder's (ZXing) names where the two overlap, so both scan paths report
the same `format` string for the same symbology.

Capability gap (accepted): `zbar` cannot read 2D matrix codes like
DataMatrix, and its PDF417/QR support is weaker than the live (ZXing)
path. So the upload fallback does **not** reach full format parity with
live capture; live is the primary path. See docs/plan-scan-tuning.md.

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

# zbar native type name -> canonical wire format. Names align with the
# live-capture decoder (ZXing) so both paths speak the same vocabulary.
# Any symbology zbar reads that is NOT in this map passes through under
# its raw zbar name rather than being dropped -- the warehouse may use
# formats we have not catalogued, and item lookup is by text, not format.
_FORMAT_MAP: dict[str, str] = {
    "UPCA": "UPC_A",
    "UPCE": "UPC_E",
    "EAN13": "EAN_13",
    "EAN8": "EAN_8",
    "ISBN13": "EAN_13",  # an ISBN-13 is physically an EAN-13
    "CODE128": "CODE_128",
    "CODE39": "CODE_39",
    "CODE93": "CODE_93",
    "CODABAR": "CODABAR",
    "I25": "ITF",  # Interleaved 2 of 5 (ZXing calls this ITF)
    "DATABAR": "RSS_14",
    "DATABAR_EXP": "RSS_EXPANDED",
    "QRCODE": "QR_CODE",
    "PDF417": "PDF_417",
}

# Enable every symbology the installed zbar knows. zbar disables some
# formats (I25, CODE93, DataBar, ...) by default, so to actually read
# "all formats" we must enable them explicitly. Building the list by
# iterating ZBarSymbol (minus the non-symbol sentinels) is version-proof:
# it picks up exactly what this zbar build supports, no more.
_ALL_SYMBOLS = [s for s in ZBarSymbol if s.name not in ("NONE", "PARTIAL")]


def decode_image(data: bytes) -> list[BarcodeMatch]:
    """Decode every barcode zbar can read in the image bytes `data`.

    Returns a list of `BarcodeMatch` (possibly empty if the image is
    readable but contains no decodable symbol). Raises
    `UnreadableImageError` if the bytes are not a decodable image.

    Every symbology the installed zbar supports is enabled; a decoded
    type with no entry in `_FORMAT_MAP` is reported under its raw zbar
    name rather than dropped.

    Duplicate detections of the same `(text, format)` are collapsed --
    zbar can report the same symbol more than once -- while preserving
    first-seen order so a chooser in the UI stays stable.
    """
    try:
        image = Image.open(BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise UnreadableImageError("The uploaded file is not a readable image.") from exc

    results = pyzbar.decode(image, symbols=_ALL_SYMBOLS)

    matches: list[BarcodeMatch] = []
    seen: set[tuple[str, str]] = set()
    for symbol in results:
        canonical = _FORMAT_MAP.get(symbol.type, symbol.type)
        text = symbol.data.decode("utf-8", errors="replace")
        key = (text, canonical)
        if key in seen:
            continue
        seen.add(key)
        matches.append(BarcodeMatch(text=text, format=canonical))

    return matches
