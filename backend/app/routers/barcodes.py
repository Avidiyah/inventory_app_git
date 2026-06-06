"""HTTP routes for the `/barcodes` resource.

Layer: routers (FastAPI). Thin handler only -- it reads the uploaded
image bytes, delegates decoding to `app.services.barcodes`, and
translates any `DomainError` via the shared `to_http` translator. No
business logic, no persistence: the image is decoded in memory and
discarded when the request ends.

Open to any authenticated user. Lookup and mutation gates downstream
(`/items/by-barcode/{text}`, `POST /transactions/`) still enforce the
real authorisation; this endpoint only turns bytes into strings.

Mounted by `app/main.py` under the root prefix.
"""

from fastapi import APIRouter, Depends, File, UploadFile

from app.auth_deps import get_current_user
from app.domain.errors import DomainError
from app.routers._errors import to_http
from app.schemas.barcodes import BarcodeDecodeResponse
from app.services import barcodes as barcodes_service

router = APIRouter(prefix="/barcodes", tags=["barcodes"])


@router.post(
    "/decode",
    response_model=BarcodeDecodeResponse,
    dependencies=[Depends(get_current_user)],
)
async def decode_barcode(file: UploadFile = File(...)):
    """Decode an uploaded image and return the barcodes found.

    Any authenticated user. The image is read into memory and never
    persisted. A readable image with no supported barcode returns
    `200 {"barcodes": []}`; an unreadable file returns 400."""
    data = await file.read()
    try:
        matches = barcodes_service.decode_image(data)
    except DomainError as exc:
        raise to_http(exc)
    return BarcodeDecodeResponse(barcodes=matches)
