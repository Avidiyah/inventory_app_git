"""Work-order photos: storage figures (spec 2026-11-24 photo export).

Layer: services (SQLAlchemy session in, dicts/ORM rows out). Byte handling and
thresholds live in `app.domain.photos`; folder rules in `app.domain.photo_paths`.
"""

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.domain import photos
from app.models import WorkOrderPhoto


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
