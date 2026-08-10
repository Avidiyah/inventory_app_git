"""HTTP routes for the `/barcodes` resource.

Layer: routers (FastAPI). Thin handler only -- it reads the uploaded
image bytes, delegates decoding to `app.services.barcodes`, and
translates any `DomainError` via the shared `to_http` translator. No
business logic, no persistence: the image is decoded in memory and
discarded when the request ends.

Open to any authenticated user. Lookup and mutation gates downstream
(`GET /items/{barcode}`, `POST /transactions/`) still enforce the
real authorisation; this endpoint only turns bytes into strings.

Mounted by `app/main.py` under the root prefix.
"""

from fastapi import APIRouter, Depends, File, UploadFile

from app.auth_deps import get_current_user
from app.domain.errors import DomainError
from app.routers._errors import to_http
from app.routers._uploads import MAX_IMAGE_UPLOAD_BYTES, read_capped
from app.schemas.barcodes import BarcodeDecodeResponse
from app.services import barcodes as barcodes_service

router = APIRouter(prefix="/barcodes", tags=["barcodes"])


@router.post(
    "/decode",
    response_model=BarcodeDecodeResponse,
    dependencies=[Depends(get_current_user)],
    responses={413: {"description": "Image exceeds the upload size cap."}},
)
def decode_barcode(file: UploadFile = File(...)):
    """Decode an uploaded image and return the barcodes found.

    Any authenticated user. The image is read into memory and never
    persisted. A readable image with no supported barcode returns
    `200 {"barcodes": []}`; an unreadable file returns 400; one over
    `MAX_IMAGE_UPLOAD_BYTES` returns 413 without being decoded.

    Deliberately `def`, not `async def`: `decode_image` is blocking,
    CPU-bound native work (Pillow decode + zbar across every symbology).
    On the event loop it would stall *every* concurrent request for its
    whole duration; as a sync handler FastAPI runs it in the threadpool,
    like the rest of this app's routes. `read_capped` is the sync
    equivalent of `await file.read()` on the same spooled upload, with a
    ceiling -- Pillow parses attacker-supplied bytes here (it is why B4
    outranked N1 on exposure), so the size it is handed is worth
    bounding."""
    data = read_capped(file, limit=MAX_IMAGE_UPLOAD_BYTES, what="Image")
    try:
        matches = barcodes_service.decode_image(data)
    except DomainError as exc:
        raise to_http(exc)
    return BarcodeDecodeResponse(barcodes=matches)
