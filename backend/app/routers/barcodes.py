"""HTTP routes for the `/barcodes` resource.

Layer: routers (FastAPI). Thin handler only -- it reads the uploaded
image bytes, delegates decoding to `app.services.barcodes`, and
translates any `DomainError` via the shared `to_http` translator. No
business logic, no persistence: the image is decoded in memory and
discarded when the request ends.

Gated at supervisor-or-above to match the Transaction page (the only
surface that uses scanning) and its sibling `POST /transactions/`.

Mounted by `app/main.py` under the root prefix.
"""

from fastapi import APIRouter, Depends, File, UploadFile

from app.auth_deps import require_min_role
from app.domain import roles
from app.domain.errors import DomainError
from app.routers._errors import to_http
from app.schemas.barcodes import BarcodeDecodeResponse
from app.services import barcodes as barcodes_service

router = APIRouter(prefix="/barcodes", tags=["barcodes"])


@router.post(
    "/decode",
    response_model=BarcodeDecodeResponse,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
async def decode_barcode(file: UploadFile = File(...)):
    """Decode an uploaded image and return the barcodes found.

    Supervisor or above. The image is read into memory and never
    persisted. A readable image with no supported barcode returns
    `200 {"barcodes": []}`; an unreadable file returns 400."""
    data = await file.read()
    try:
        matches = barcodes_service.decode_image(data)
    except DomainError as exc:
        raise to_http(exc)
    return BarcodeDecodeResponse(barcodes=matches)
