"""Witness sign-off on a work order (spec 2026-09-30).

Layer: services (SQLAlchemy session in, ORM rows out). One row per work
order, locked once saved; Supervisor+ may clear it. Sibling of
`work_orders.py`, which is past its size budget.

Visibility is the Work Orders page rule (`get_visible_work_order`): a caller
who cannot see the work order gets not-found, never 403. The Supervisor+ gate
on `clear_signature` is the router's `require_min_role`; the service trusts
it, as `restore_work_order` does.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import work_orders as wo
from app.domain.errors import WorkOrderAlreadySignedError, WorkOrderNotFoundError
from app.models import User, WorkOrder, WorkOrderSignature
from app.services.work_orders import get_visible_work_order


def _locked_visible(db: Session, work_order_id: uuid.UUID, user: User) -> WorkOrder:
    get_visible_work_order(db, work_order_id, user)  # 404 if archived / not visible
    # Row lock: `notes` is read-modify-write, same as every other note append.
    return (
        db.query(WorkOrder)
        .populate_existing()
        .filter(WorkOrder.id == work_order_id)
        .with_for_update()
        .one()
    )


def _already_signed(db: Session, work_order_id: uuid.UUID) -> bool:
    return (
        db.query(WorkOrderSignature.id).filter_by(work_order_id=work_order_id).first()
        is not None
    )


def save_signature(
    db: Session,
    work_order_id: uuid.UUID,
    *,
    user: User,
    image_data_url: str,
    witness_name: str,
    witness_phone: str,
) -> WorkOrder:
    """Capture the sign-off (S1-S3). Validates before touching the row so a bad
    payload writes nothing; the unique constraint is the backstop for two
    devices saving at once."""
    png = wo.decode_signature_png(image_data_url)
    name = wo.normalize_witness_name(witness_name)
    phone = wo.normalize_witness_phone(witness_phone)
    work_order = _locked_visible(db, work_order_id, user)
    if _already_signed(db, work_order.id):
        raise WorkOrderAlreadySignedError("This work order is already signed.")
    now = datetime.now(timezone.utc)
    db.add(
        WorkOrderSignature(
            work_order_id=work_order.id,
            image_png=png,
            witness_name=name,
            witness_phone=phone,
            captured_by_id=user.id,
            captured_at=now,
        )
    )
    work_order.notes = wo.append_note_log(
        work_order.notes,
        wo.NOTE_SIGNED_OFF.format(name=name),
        author_name=user.full_name,
        occurred_at=now,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise WorkOrderAlreadySignedError("This work order is already signed.")
    return work_order


def clear_signature(db: Session, work_order_id: uuid.UUID, *, user: User) -> WorkOrder:
    """Delete the sign-off so it can be recaptured (S5); not-found when unsigned."""
    work_order = _locked_visible(db, work_order_id, user)
    row = db.query(WorkOrderSignature).filter_by(work_order_id=work_order.id).first()
    if row is None:
        raise WorkOrderNotFoundError("This work order has no signature.")
    db.delete(row)
    work_order.notes = wo.append_note_log(
        work_order.notes,
        wo.NOTE_SIGNATURE_CLEARED,
        author_name=user.full_name,
        occurred_at=datetime.now(timezone.utc),
    )
    db.commit()
    return work_order


def get_signature_png(db: Session, work_order_id: uuid.UUID, *, user: User) -> bytes:
    get_visible_work_order(db, work_order_id, user)
    png = (
        db.query(WorkOrderSignature.image_png)
        .filter_by(work_order_id=work_order_id)
        .scalar()
    )
    if png is None:
        raise WorkOrderNotFoundError("This work order has no signature.")
    return png
