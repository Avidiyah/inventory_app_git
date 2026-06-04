"""Barcode decode response schemas.

Layer: schemas (Pydantic only). Consumed by `app/routers/barcodes.py`
to serialize the result of decoding an uploaded image. There is no
*request* schema here -- the request is a `multipart/form-data` file
upload parsed by FastAPI's `UploadFile`, not a JSON body.

The decoder never persists anything; these types describe a pure,
in-memory image-to-text result.
"""

from pydantic import BaseModel


class BarcodeMatch(BaseModel):
    """One decoded symbol.

    `format` is the canonical format name (e.g. `"UPC_A"`, `"CODE_128"`),
    normalised by the service from the decoder's native vocabulary so the
    wire contract is stable regardless of the underlying library.
    """

    text: str
    format: str


class BarcodeDecodeResponse(BaseModel):
    """Outbound shape for `POST /barcodes/decode`.

    `barcodes` is empty when the image was readable but contained no
    supported symbol -- the frontend treats that as "no barcode found"
    and keeps the manual fallback available. An unreadable image is a
    separate 400 error, not an empty list.
    """

    barcodes: list[BarcodeMatch]
