"""Committed seed data for the E2E suite, and its removal.

These rows go into the database `DATABASE_URL` points at -- locally the
developer's own dev Postgres, by decision. They are therefore visible in the
running app for the length of a session. Three safeguards make that
acceptable:

1. Every record carries `RUN_PREFIX` in the column a human reads.
2. Teardown deletes by prefix, children before parents.
3. `sweep_debris` removes anything a crashed earlier run left behind, before
   a new one starts, so debris cannot accumulate.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    Item,
    MassStage,
    MassStageItem,
    MassStageWorkOrder,
    ToolTransaction,
    Transaction,
    User,
    UserRequest,
    WorkOrder,
)
from app.services import auth as auth_service
from app.services import items as items_service
from app.services import work_orders as wo_service

RUN_PREFIX = f"E2E-{uuid.uuid4().hex[:8]}"
SEED_PASSWORD = "e2e-password-1"


@dataclass
class Seed:
    prefix: str
    owner_username: str
    work_order_number: str
    item_barcode: str


def _purge(db: Session, pattern: str) -> int:
    """Delete every row whose human-readable column matches `pattern`.

    The work-order labor/technician/item children carry `ondelete=CASCADE`, so
    deleting the work order takes them with it. These four do NOT, and would
    block the parent delete instead -- a scan journey writes a Transaction, a
    tool journey a ToolTransaction. Clear them by tracked id first.
    """
    work_order_ids = db.scalars(
        select(WorkOrder.id).where(WorkOrder.number.like(pattern))
    ).all()
    item_ids = db.scalars(select(Item.id).where(Item.barcode.like(pattern))).all()
    user_ids = db.scalars(select(User.id).where(User.username.like(pattern))).all()
    removed = 0

    def _run(statement) -> None:
        nonlocal removed
        removed += db.execute(statement).rowcount or 0

    if work_order_ids:
        _run(
            delete(MassStageWorkOrder).where(
                MassStageWorkOrder.work_order_id.in_(work_order_ids)
            )
        )
        _run(delete(Transaction).where(Transaction.work_order_id.in_(work_order_ids)))
        _run(
            delete(ToolTransaction).where(
                ToolTransaction.work_order_id.in_(work_order_ids)
            )
        )
        _run(delete(UserRequest).where(UserRequest.work_order_id.in_(work_order_ids)))
    if item_ids:
        _run(delete(MassStageItem).where(MassStageItem.item_id.in_(item_ids)))
        _run(delete(Transaction).where(Transaction.item_id.in_(item_ids)))
        _run(delete(UserRequest).where(UserRequest.item_id.in_(item_ids)))
    if user_ids:
        _run(delete(Transaction).where(Transaction.user_id.in_(user_ids)))
        _run(
            delete(ToolTransaction).where(
                ToolTransaction.performed_by_id.in_(user_ids)
            )
        )
        _run(
            delete(ToolTransaction).where(ToolTransaction.assigned_to_id.in_(user_ids))
        )
        _run(delete(MassStage).where(MassStage.created_by_id.in_(user_ids)))

    if work_order_ids:
        _run(delete(WorkOrder).where(WorkOrder.id.in_(work_order_ids)))
    if item_ids:
        _run(delete(Item).where(Item.id.in_(item_ids)))
    if user_ids:
        _run(delete(User).where(User.id.in_(user_ids)))
    db.commit()
    return removed


def sweep_debris(db: Session) -> int:
    """Remove what any earlier E2E run left behind."""
    return _purge(db, "E2E-%")


def build(db: Session) -> Seed:
    """Create one owner, one item and one `created` work order."""
    seed = Seed(
        prefix=RUN_PREFIX,
        owner_username=f"{RUN_PREFIX}-owner",
        work_order_number=f"{RUN_PREFIX}-WO",
        item_barcode=f"{RUN_PREFIX}-ITEM",
    )

    owner = User(
        username=seed.owner_username,
        first_name="Eetoo",
        last_name="Ee",
        password_hash=auth_service.hash_password(SEED_PASSWORD),
        role="owner",
    )
    db.add(owner)
    db.commit()

    items_service.create_item(
        db,
        barcode=seed.item_barcode,
        name=f"{RUN_PREFIX} widget",
        quantity=Decimal("5"),
        location=f"{RUN_PREFIX}-shelf",
    )

    # `get_or_create_work_order` is the only path that brings a work order into
    # existence (see its docstring). With no assignee it starts `created`,
    # which is the status the Task 6 journey transitions out of.
    wo_service.get_or_create_work_order(
        db,
        number=seed.work_order_number,
        community=f"{RUN_PREFIX} community",
        description=f"{RUN_PREFIX} smoke work order",
        created_by_id=owner.id,
    )
    db.commit()
    return seed


def destroy(db: Session, seed: Seed) -> None:
    """Remove exactly what `build` created, plus anything the run attached to
    it -- a labor session, for one: the Task 6 journey starts a clock."""
    _purge(db, f"{seed.prefix}%")
