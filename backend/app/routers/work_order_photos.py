"""Work-order photos (spec 2026-11-24): upload/list/preview on a work order;
storage, export zip and clear for Admin+.

No route serves the original: it leaves only through the export zip.
"""

import asyncio
import tempfile
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.auth_deps import get_current_user, require_min_role
from app.database import get_db
from app.domain import photos, roles
from app.domain.errors import DomainError
from app.models import User
from app.routers._errors import to_http
from app.routers._uploads import read_capped
from app.services import work_order_photos as photo_service

router = APIRouter(tags=["work-order-photos"])

_ADMIN_403 = {403: {"description": f"Requires the {roles.label(roles.ROLE_ADMIN)} role or higher."}}
FULL_MESSAGE = "Photo storage is full — export and clear first."

# Stress test 2026-11-24: 50 phone photos at once filled the 2 GB container
# (each in-flight upload holds its bytes, the preview and the driver's copies).
# Only this many run at a time; the rest wait here on the event loop holding no
# thread, no DB connection and no bytes (the files sit spooled on disk).
# ponytail: per-process gate; a shared limit if the service ever runs >1 worker.
_UPLOAD_SLOTS = asyncio.Semaphore(4)


@router.post("/work-orders/{work_order_id}/photos", status_code=201)
async def upload_work_order_photos(
    work_order_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add photos. 400 not an image, 403 Technician off the crew, 404 unknown,
    413 over 20 MB, 507 storage at 80% of the disk."""
    await run_in_threadpool(db.rollback)  # release the sign-in query's connection
    async with _UPLOAD_SLOTS:
        return await run_in_threadpool(_upload, work_order_id, files, user, db)


def _upload(work_order_id: uuid.UUID, files: list[UploadFile], user: User, db: Session):
    try:
        photo_service.check_can_upload(db, work_order_id, user=user)
        if photo_service.storage_status(db)["full"]:
            raise HTTPException(status_code=507, detail=FULL_MESSAGE)
        db.rollback()  # no connection held through the image step
        prepared = []
        for file in files:
            raw = read_capped(file, limit=photos.MAX_UPLOAD_BYTES, what="Photo")
            try:
                prepared.append(photo_service.prepare_upload(raw))
            except ValueError:
                raise HTTPException(
                    status_code=400, detail=f"{file.filename or 'File'} is not a readable image."
                )
        saved = []
        for item in prepared:
            photo = photo_service.add_photo(db, work_order_id, user=user, prepared=item)
            saved.append({"id": photo.id, "taken_on": photo.taken_on, "seq": photo.seq})
    except DomainError as exc:
        raise to_http(exc)
    return saved


@router.get("/work-orders/{work_order_id}/photos")
def list_work_order_photos(
    work_order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return photo_service.list_photos(db, work_order_id, user=user)
    except DomainError as exc:
        raise to_http(exc)


@router.get("/work-order-photos/storage", responses=_ADMIN_403)
def photo_storage(
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    return photo_service.storage_status(db)


@router.get("/work-order-photos/export.zip", responses=_ADMIN_403)
def export_photos(
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    """Zip of every photo not yet cleared; stamps the new ones exported."""
    out = tempfile.TemporaryFile()
    photo_service.export_zip(db, out)
    out.seek(0)
    name = photo_service.export_filename(datetime.now(timezone.utc))
    return StreamingResponse(
        iter(lambda: out.read(64 * 1024), b""),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
        background=BackgroundTask(out.close),
    )


@router.post("/work-order-photos/clear-exported", responses=_ADMIN_403)
def clear_exported_photos(
    user: User = Depends(require_min_role(roles.ROLE_ADMIN)),
    db: Session = Depends(get_db),
):
    deleted = photo_service.clear_exported(db)
    if deleted:
        photo_service.vacuum_photos()
    return {"deleted": deleted, "storage": photo_service.storage_status(db)}


@router.get("/work-order-photos/{photo_id}/preview")
def photo_preview(
    photo_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        jpeg = photo_service.get_preview(db, photo_id, user=user)
    except DomainError as exc:
        raise to_http(exc)
    return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
