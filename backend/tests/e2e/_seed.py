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
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    AttendancePunch,
    Item,
    MassStage,
    MassStageItem,
    MassStageWorkOrder,
    Tool,
    ToolTransaction,
    Transaction,
    User,
    UserRequest,
    WorkOrder,
    WorkOrderItem,
)
from app.services import attendance as attendance_service
from app.services import auth as auth_service
from app.services import items as items_service
from app.services import mass_staging
from app.services import tools as tools_service
from app.services import transactions as transactions_service
from app.services import user_requests as user_requests_service
from app.services import users as users_service
from app.services import work_order_signature
from app.services import work_orders as wo_service

RUN_PREFIX = f"E2E-{uuid.uuid4().hex[:8]}"
SEED_PASSWORD = "e2e-password-1"
# A 1x1 PNG; scripts/memprobe_routes.py repeats the literal (it must not
# import app.* at module level) and tests/test_memprobe.py asserts equality.
SIGNATURE_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@dataclass
class Seed:
    """UUIDs are stored as `str` so `vars(seed)` is a ready token dict for
    the memory sweep. The four positional fields are what the e2e suite uses;
    the rest default empty so `build` can assign them incrementally."""

    prefix: str
    owner_username: str
    work_order_number: str
    item_barcode: str
    owner_id: str = ""
    user_id: str = ""
    technician_username: str = ""
    work_order_id: str = ""
    signed_work_order_id: str = ""
    signed_work_order_number: str = ""
    active_work_order_id: str = ""
    active_work_order_number: str = ""
    item_id: str = ""
    item2_id: str = ""
    tool_id: str = ""
    tool_barcode: str = ""
    transaction_id: str = ""
    stage_id: str = ""
    slot_id: str = ""
    stage_item_id: str = ""
    loading_stage_id: str = ""
    completed_stage_id: str = ""
    request_id: str = ""
    punch_id: str = ""
    labor_id: str = ""
    wo_item_id: str = ""


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
    tool_ids = db.scalars(select(Tool.id).where(Tool.barcode.like(pattern))).all()
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
        # Item lines and requests reference transactions without cascade, so
        # they go before the Transaction delete.
        _run(delete(WorkOrderItem).where(WorkOrderItem.work_order_id.in_(work_order_ids)))
        _run(delete(UserRequest).where(UserRequest.work_order_id.in_(work_order_ids)))
        _run(delete(Transaction).where(Transaction.work_order_id.in_(work_order_ids)))
        _run(
            delete(ToolTransaction).where(
                ToolTransaction.work_order_id.in_(work_order_ids)
            )
        )
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
        # Starting a labor clock auto-punches the owner in (D3).
        _run(delete(AttendancePunch).where(AttendancePunch.user_id.in_(user_ids)))

    if work_order_ids:
        _run(delete(WorkOrder).where(WorkOrder.id.in_(work_order_ids)))
    if item_ids:
        _run(delete(Item).where(Item.id.in_(item_ids)))
    if tool_ids:
        _run(delete(ToolTransaction).where(ToolTransaction.tool_id.in_(tool_ids)))
        _run(delete(Tool).where(Tool.id.in_(tool_ids)))
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
    # The Owner cannot track time, so the Begin Charging journey needs an
    # Admin; `admin_page` logs in as `<prefix>-admin`.
    admin = User(
        username=f"{seed.prefix}-admin",
        first_name="Eetoo",
        last_name="Admin",
        password_hash=auth_service.hash_password(SEED_PASSWORD),
        role="admin",
    )
    db.add_all([owner, admin])
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
    work_order = wo_service.get_or_create_work_order(
        db,
        number=seed.work_order_number,
        community=f"{RUN_PREFIX} community",
        description=f"{RUN_PREFIX} smoke work order",
        created_by_id=owner.id,
    )
    db.commit()
    seed.owner_id = str(owner.id)
    seed.work_order_id = str(work_order.id)

    # Everything below exists for scripts/memprobe.py sweep. The seed work
    # order above must stay `created` and unassigned (test_work_orders.py
    # asserts it), so rows that would advance a work order go on WO3.
    tech = users_service.create_user(
        db, username=f"{RUN_PREFIX}-tech", first_name="Eetoo", last_name="Tech",
        password_hash=auth_service.hash_password(SEED_PASSWORD), role="technician")
    seed.user_id, seed.technician_username = str(tech.id), tech.username

    item = items_service.get_item_by_barcode(db, seed.item_barcode)
    seed.item_id = str(item.id)
    item2 = items_service.create_item(db, barcode=f"{RUN_PREFIX}-ITEM2", name=f"{RUN_PREFIX} gadget",
                                      quantity=Decimal("5"), location=f"{RUN_PREFIX}-shelf")
    seed.item2_id = str(item2.id)

    community = f"{RUN_PREFIX} community"
    signed = wo_service.get_or_create_work_order(db, number=f"{RUN_PREFIX}-WO2", community=community,
                                                 description=f"{RUN_PREFIX} signed", created_by_id=owner.id)
    active = wo_service.get_or_create_work_order(db, number=f"{RUN_PREFIX}-WO3", community=community,
                                                 description=f"{RUN_PREFIX} active", created_by_id=owner.id)
    seed.signed_work_order_id, seed.signed_work_order_number = str(signed.id), signed.number
    seed.active_work_order_id, seed.active_work_order_number = str(active.id), active.number
    db.commit()

    work_order_signature.save_signature(db, signed.id, user=owner, image_data_url=SIGNATURE_PNG,
                                        witness_name="Eetoo Witness", witness_phone="5555555555")
    # Labor can only be recorded for an assigned technician.
    wo_service.update_work_order(db, active.id, user=owner, fields={"assigned_to_ids": [tech.id]})
    labor =wo_service.add_work_order_labor(db, active.id, user=owner, technician_id=tech.id, minutes=30)
    line = wo_service.add_work_order_item(db, active.id, user=owner, item_id=item.id, quantity=Decimal("1"))
    seed.labor_id, seed.wo_item_id = str(labor.id), str(line.id)

    tool = tools_service.create_tool(db, barcode=f"{RUN_PREFIX}-TOOL", name=f"{RUN_PREFIX} drill",
                                     quantity=Decimal("5"))
    seed.tool_id, seed.tool_barcode = str(tool.id), tool.barcode

    txn = transactions_service.apply_transaction(db, item_id=item.id, transaction_type="stock",
                                                 quantity=Decimal("1"), user_id=owner.id,
                                                 work_order_number=None)
    seed.transaction_id = str(txn.id)

    planning = mass_staging.create_stage(db, community=community, building_name="1", created_by_id=owner.id)
    slot = mass_staging.add_work_order_to_stage(db, planning.id, work_order_number=seed.work_order_number)
    stage_item = mass_staging.add_item(db, planning.id, slot.id, item_id=item.id, planned_quantity=Decimal("2"))
    loading = mass_staging.create_stage(db, community=community, building_name="2", created_by_id=owner.id)
    loading_slot = mass_staging.add_work_order_to_stage(db, loading.id, work_order_number=active.number)
    mass_staging.add_item(db, loading.id, loading_slot.id, item_id=item.id, planned_quantity=Decimal("100"))
    mass_staging.update_stage(db, loading.id, status="loading")
    completed = mass_staging.create_stage(db, community=community, building_name="3", created_by_id=owner.id)
    mass_staging.update_stage(db, completed.id, status="loading")
    mass_staging.update_stage(db, completed.id, status="completed")
    seed.stage_id, seed.slot_id, seed.stage_item_id = str(planning.id), str(slot.id), str(stage_item.id)
    seed.loading_stage_id, seed.completed_stage_id = str(loading.id), str(completed.id)

    request = user_requests_service.create_catalogue_request(
        db, searched_text=f"{RUN_PREFIX} thing", quantity=Decimal("1"), note=None,
        work_order_id=active.id, work_order_number=active.number, source="find_item",
        created_by_id=owner.id)
    db.flush()  # the service only adds; the id is assigned at flush
    seed.request_id = str(request.id)

    day = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0) - timedelta(days=2)
    punch = attendance_service.admin_add_punch(db, actor=owner, user_id=tech.id,
                                               started_at=day, ended_at=day + timedelta(hours=1))
    seed.punch_id = str(punch.id)
    db.commit()
    return seed


def destroy(db: Session, seed: Seed) -> None:
    """Remove exactly what `build` created, plus anything the run attached to
    it -- a labor session, for one: the Task 6 journey starts a clock."""
    _purge(db, f"{seed.prefix}%")
