"""Work-order photos: upload, list, preview, export zip, clear (spec 2026-11-24).

Layer: services (SQLAlchemy session in, dicts/ORM rows out). Byte handling and
thresholds live in `app.domain.photos`; folder rules in `app.domain.photo_paths`.

Visibility follows the signature service: a caller who can't see the work
order gets not-found; a Technician off the crew can view but not upload.
Uploads lock the work order row, so `seq` (the `_n` filename suffix) is
assigned one upload at a time per order and never collides.
"""

import csv
import io
import logging
import uuid
import zipfile
from datetime import datetime, timezone
from typing import BinaryIO

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.database import engine
from app.domain import labor_day, photos
from app.domain.errors import WorkOrderNotFoundError
from app.domain.photo_paths import photo_path
from app.models import User, WorkOrder, WorkOrderPhoto
from app.services.work_orders import get_visible_work_order, require_crew_for_technician

logger = logging.getLogger(__name__)


def database_size(db: Session) -> int:
    return int(db.execute(text("SELECT pg_database_size(current_database())")).scalar())


def storage_status(db: Session) -> dict:
    """Whole-database usage against the disk setting, plus photo counts."""
    status = photos.storage_flags(database_size(db), photos.disk_bytes())
    waiting, waiting_bytes = db.query(
        func.count(WorkOrderPhoto.id), func.coalesce(func.sum(WorkOrderPhoto.size_bytes), 0)
    ).filter(WorkOrderPhoto.exported_at.is_(None)).one()
    exported = (
        db.query(func.count(WorkOrderPhoto.id))
        .filter(WorkOrderPhoto.exported_at.isnot(None))
        .scalar()
    )
    status.update(
        waiting_photos=int(waiting), waiting_bytes=int(waiting_bytes), exported_photos=int(exported)
    )
    return status


def _filename(photo: WorkOrderPhoto, work_order: WorkOrder) -> tuple[str, str]:
    return photo_path(
        work_order.service_type, work_order.number, work_order.location, photo.taken_on, photo.seq
    )


def add_photo(db: Session, work_order_id: uuid.UUID, *, user: User, raw: bytes) -> WorkOrderPhoto:
    """Store one photo. Raises ValueError (not an image) before any write."""
    get_visible_work_order(db, work_order_id, user)
    work_order = (
        db.query(WorkOrder).filter(WorkOrder.id == work_order_id).with_for_update().one()
    )
    require_crew_for_technician(work_order, user)
    now = datetime.now(timezone.utc)
    original, preview, taken_on = photos.prepare(raw, labor_day.central_date_of(now))
    seq = (
        db.query(func.coalesce(func.max(WorkOrderPhoto.seq) + 1, 0))
        .filter_by(work_order_id=work_order.id, taken_on=taken_on)
        .scalar()
    )
    photo = WorkOrderPhoto(
        work_order_id=work_order.id,
        original=original,
        original_type="image/jpeg",
        preview_jpeg=preview,
        size_bytes=len(original),
        taken_on=taken_on,
        seq=seq,
        uploaded_by_id=user.id,
        uploaded_at=now,
    )
    db.add(photo)
    db.commit()
    return photo


def list_photos(db: Session, work_order_id: uuid.UUID, *, user: User) -> list[dict]:
    work_order = get_visible_work_order(db, work_order_id, user)
    rows = (
        db.query(WorkOrderPhoto)
        .filter_by(work_order_id=work_order.id)
        .order_by(WorkOrderPhoto.taken_on, WorkOrderPhoto.seq)
        .all()
    )
    return [
        {"id": p.id, "filename": _filename(p, work_order)[1], "taken_on": p.taken_on}
        for p in rows
    ]


def get_preview(db: Session, photo_id: uuid.UUID, *, user: User) -> bytes:
    work_order_id = db.query(WorkOrderPhoto.work_order_id).filter_by(id=photo_id).scalar()
    if work_order_id is None:
        raise WorkOrderNotFoundError("Photo not found.")
    get_visible_work_order(db, work_order_id, user)
    return db.query(WorkOrderPhoto.preview_jpeg).filter_by(id=photo_id).scalar()


def export_zip(db: Session, out: BinaryIO) -> int:
    """Write every photo still in the table (new + exported-not-cleared) to `out`
    as a zip of originals under `<Service-Type>/…`, plus manifest.csv; then
    stamp `exported_at` on the new ones. One original in memory at a time."""
    rows = (
        db.query(WorkOrderPhoto, WorkOrder)
        .join(WorkOrder, WorkOrder.id == WorkOrderPhoto.work_order_id)
        .order_by(WorkOrder.number, WorkOrderPhoto.taken_on, WorkOrderPhoto.seq)
        .all()
    )
    manifest = io.StringIO()
    writer = csv.writer(manifest)
    writer.writerow(["path", "work_order", "service_type", "location"])
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as zf:
        for photo, work_order in rows:
            folder, name = _filename(photo, work_order)
            path = f"{folder}/{name}"
            original = db.query(WorkOrderPhoto.original).filter_by(id=photo.id).scalar()
            zf.writestr(path, original)
            writer.writerow([path, work_order.number, work_order.service_type or "", work_order.location or ""])
        zf.writestr("manifest.csv", manifest.getvalue())
    new_ids = [p.id for p, _ in rows if p.exported_at is None]
    if new_ids:
        db.query(WorkOrderPhoto).filter(WorkOrderPhoto.id.in_(new_ids)).update(
            {WorkOrderPhoto.exported_at: datetime.now(timezone.utc)}, synchronize_session=False
        )
    db.commit()
    return len(rows)


def export_filename(now: datetime) -> str:
    local = now.astimezone(labor_day.CENTRAL)
    return f"export_{local:%Y-%m-%d_%H%M}.zip"


def vacuum_photos() -> None:
    """Give freed space back to the disk. Own autocommit connection (VACUUM can't
    run in a transaction); a short lock timeout so a busy table skips it rather
    than hanging the request -- the space is reclaimed on the next clear."""
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("SET lock_timeout = '5s'"))
            conn.execute(text("VACUUM FULL work_order_photos"))
    except Exception:
        logger.warning("VACUUM FULL work_order_photos skipped", exc_info=True)


def clear_exported(db: Session) -> int:
    deleted = (
        db.query(WorkOrderPhoto)
        .filter(WorkOrderPhoto.exported_at.isnot(None))
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted
