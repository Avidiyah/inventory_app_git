"""Mass-staging (truck planning) service.

Layer: services. A Mass Stage groups a building's work orders into ordered
truck-load slots. It no longer owns work orders -- each slot references a
standalone `WorkOrder` (resolved through `services.work_orders`). Planning never
moves stock; loading writes real per-slot `dispense` rows carrying that slot's
work order; returns add stock back through the slot tables without ledger rows.

Editability is gated by the stage's status via `domain.mass_staging`: slots /
items may only change while `planning`; status changes are policed by
`validate_transition`.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain import mass_staging as ms
from app.domain import roles
from app.domain.errors import (
    DuplicateBuildingStageError,
    ItemNotFoundError,
    NegativeQuantityError,
    RoomNotFoundError,
    StageItemNotFoundError,
    StageNotFoundError,
    StageStateError,
    WorkOrderStateError,
)
from app.domain.quantity import apply_delta
from app.models import (
    Item,
    MassStage,
    MassStageItem,
    MassStageWorkOrder,
    Transaction,
    WorkOrder,
)
from app.services import work_orders as wo_service


# --- internal helpers ----------------------------------------------------

def _active_stage_exists(db: Session, community: str, building_name: str) -> bool:
    """Is there already a non-completed stage for this community + building?
    Mirrors the partial unique index."""
    return bool(
        db.query(MassStage.id)
        .filter(
            MassStage.community == community,
            MassStage.building_name == building_name,
            MassStage.status != ms.STATUS_COMPLETED,
        )
        .first()
    )


def _get_stage_row(db: Session, stage_id: uuid.UUID) -> MassStage:
    stage = db.query(MassStage).filter(MassStage.id == stage_id).first()
    if stage is None:
        raise StageNotFoundError("Stage not found.")
    return stage


def _get_slot(
    db: Session, stage: MassStage, slot_id: uuid.UUID
) -> MassStageWorkOrder:
    slot = (
        db.query(MassStageWorkOrder)
        .filter(
            MassStageWorkOrder.id == slot_id,
            MassStageWorkOrder.stage_id == stage.id,
        )
        .first()
    )
    if slot is None:
        raise RoomNotFoundError("Work order not found in this stage.")
    return slot


def _get_stage_item(
    db: Session, stage: MassStage, stage_item_id: uuid.UUID
) -> MassStageItem:
    stage_item = (
        db.query(MassStageItem)
        .join(
            MassStageWorkOrder,
            MassStageItem.stage_work_order_id == MassStageWorkOrder.id,
        )
        .filter(
            MassStageItem.id == stage_item_id,
            MassStageWorkOrder.stage_id == stage.id,
        )
        .first()
    )
    if stage_item is None:
        raise StageItemNotFoundError("Planned item not found.")
    return stage_item


def _require_editable(stage: MassStage) -> None:
    if not ms.can_edit_plan(stage.status):
        raise StageStateError(
            "The plan can only be edited while the stage is in planning."
        )


# --- stages --------------------------------------------------------------

def create_stage(
    db: Session,
    *,
    community: str,
    building_name: str,
    created_by_id: Optional[uuid.UUID],
) -> MassStage:
    """Create a `planning` stage for a community + building (`building_name`
    holds the building number). Raises `DuplicateBuildingStageError` if an
    active stage already exists for it."""
    if _active_stage_exists(db, community, building_name):
        raise DuplicateBuildingStageError(
            f"An active stage already exists for {community} building {building_name}."
        )
    stage = MassStage(
        community=community,
        building_name=building_name,
        status=ms.STATUS_PLANNING,
        created_by_id=created_by_id,
    )
    db.add(stage)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateBuildingStageError(
            f"An active stage already exists for {community} building {building_name}."
        ) from exc
    db.refresh(stage)
    return stage


def list_stages(
    db: Session, *, status: Optional[str] = None, user=None
) -> Sequence[MassStage]:
    """Stages newest-first, optionally filtered by status. Slots/items are
    eager-loaded for the summary counts. Scoped: a supervisor sees only stages
    they created; admin/owner (and `None`) see all."""
    q = db.query(MassStage).options(
        selectinload(MassStage.work_order_slots).selectinload(
            MassStageWorkOrder.items
        )
    )
    if status is not None:
        q = q.filter(MassStage.status == status)
    if user is not None and not roles.role_at_least(user.role, roles.ROLE_ADMIN):
        q = q.filter(MassStage.created_by_id == user.id)
    return q.order_by(MassStage.created_at.desc()).all()


def get_stage(db: Session, stage_id: uuid.UUID) -> MassStage:
    """Full stage with slots -> work_order + items -> item eager-loaded."""
    stage = (
        db.query(MassStage)
        .options(
            selectinload(MassStage.work_order_slots)
            .joinedload(MassStageWorkOrder.work_order)
            .joinedload(WorkOrder.assignee),
            selectinload(MassStage.work_order_slots)
            .selectinload(MassStageWorkOrder.items)
            .joinedload(MassStageItem.item),
        )
        .filter(MassStage.id == stage_id)
        .first()
    )
    if stage is None:
        raise StageNotFoundError("Stage not found.")
    return stage


def update_stage(
    db: Session,
    stage_id: uuid.UUID,
    *,
    community: Optional[str] = None,
    building_name: Optional[str] = None,
    status: Optional[str] = None,
) -> MassStage:
    """Rename (community/building) and/or transition a stage. Status changes are
    forward-only (`domain.mass_staging.validate_transition`); reaching
    `completed` stamps `completed_at`. A rename colliding with another active
    stage raises `DuplicateBuildingStageError`."""
    stage = _get_stage_row(db, stage_id)

    if status is not None and status != stage.status:
        ms.validate_transition(stage.status, status)
        stage.status = status
        if status == ms.STATUS_COMPLETED:
            stage.completed_at = datetime.now(timezone.utc)

    new_community = community if community is not None else stage.community
    new_building = building_name if building_name is not None else stage.building_name
    if new_community != stage.community or new_building != stage.building_name:
        if stage.status != ms.STATUS_COMPLETED and _active_stage_exists(
            db, new_community, new_building
        ):
            raise DuplicateBuildingStageError(
                f"An active stage already exists for {new_community} building {new_building}."
            )
        stage.community = new_community
        stage.building_name = new_building

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateBuildingStageError(
            "An active stage already exists for that building."
        ) from exc
    db.refresh(stage)
    return stage


def delete_stage(db: Session, stage_id: uuid.UUID) -> None:
    """Delete a stage; its slots and planned items cascade away. Does NOT touch
    the referenced work orders (they are independent) or reverse dispenses."""
    stage = _get_stage_row(db, stage_id)
    db.delete(stage)
    db.commit()


def reuse_stage(
    db: Session, stage_id: uuid.UUID, *, created_by_id: Optional[uuid.UUID]
) -> MassStage:
    """Start a fresh `planning` stage for the same community + building as a
    completed one (no slots copied -- the old work orders are done). Raises
    `StageStateError` if the source is not completed, and
    `DuplicateBuildingStageError` if the building already has an active stage."""
    source = _get_stage_row(db, stage_id)
    if source.status != ms.STATUS_COMPLETED:
        raise StageStateError("Only a completed stage can be reused.")
    return create_stage(
        db,
        community=source.community,
        building_name=source.building_name,
        created_by_id=created_by_id,
    )


# --- work-order slots ----------------------------------------------------

def add_work_order_to_stage(
    db: Session,
    stage_id: uuid.UUID,
    *,
    work_order_number: str,
    unit_number: Optional[str] = None,
    assigned_to_id: Optional[uuid.UUID] = None,
    created_by_id: Optional[uuid.UUID] = None,
) -> MassStageWorkOrder:
    """Add a work order to a stage's truck plan. Find-or-creates the `WorkOrder`
    by number (community/building taken from the stage and **enforced to match**
    a pre-existing one), records its unit/assignee, and links it as a slot.

    Raises `StageStateError` if the stage is not planning, `WorkOrderStateError`
    if the work order belongs to a different community/building, and
    `InvalidAssigneeError` (from the work-order service) if the assignee is not a
    technician."""
    stage = _get_stage_row(db, stage_id)
    _require_editable(stage)

    # Enforce-match before mutating: a pre-existing work order's non-blank
    # community/building must match this stage's.
    existing = wo_service.find_by_number(db, work_order_number)
    if existing is not None and existing.archived_at is None:
        if (existing.community and existing.community != stage.community) or (
            existing.building_number
            and existing.building_number != stage.building_name
        ):
            raise WorkOrderStateError(
                f"Work order {work_order_number} belongs to a different "
                f"community/building."
            )

    work_order = wo_service.get_or_create_work_order(
        db,
        number=work_order_number,
        community=stage.community,
        building_number=stage.building_name,
        unit_number=unit_number,
        assigned_to_id=assigned_to_id,
        created_by_id=created_by_id,
    )

    sort_order = (
        db.query(MassStageWorkOrder)
        .filter(MassStageWorkOrder.stage_id == stage.id)
        .count()
    )
    slot = MassStageWorkOrder(
        stage_id=stage.id, work_order_id=work_order.id, sort_order=sort_order
    )
    db.add(slot)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise StageStateError(
            f"Work order {work_order_number} is already in this stage."
        ) from exc
    db.refresh(slot)
    return slot


def delete_slot(db: Session, stage_id: uuid.UUID, slot_id: uuid.UUID) -> None:
    """Remove a work order from the stage's plan (its planned items cascade).
    Planning only; the work order itself is untouched."""
    stage = _get_stage_row(db, stage_id)
    _require_editable(stage)
    slot = _get_slot(db, stage, slot_id)
    db.delete(slot)
    db.commit()


# --- planned items -------------------------------------------------------

def add_item(
    db: Session,
    stage_id: uuid.UUID,
    slot_id: uuid.UUID,
    *,
    item_id: uuid.UUID,
    planned_quantity: Decimal,
) -> MassStageItem:
    """Add (or update) the planned quantity of an item on a slot. Upsert by
    `(slot, item)`. Raises `ItemNotFoundError` if the item is unknown/archived."""
    stage = _get_stage_row(db, stage_id)
    _require_editable(stage)
    slot = _get_slot(db, stage, slot_id)

    item = (
        db.query(Item)
        .filter(Item.id == item_id, Item.archived_at.is_(None))
        .first()
    )
    if item is None:
        raise ItemNotFoundError("Item not found.")

    stage_item = (
        db.query(MassStageItem)
        .filter(
            MassStageItem.stage_work_order_id == slot.id,
            MassStageItem.item_id == item_id,
        )
        .first()
    )
    if stage_item is not None:
        stage_item.planned_quantity = planned_quantity
    else:
        stage_item = MassStageItem(
            stage_work_order_id=slot.id,
            item_id=item_id,
            planned_quantity=planned_quantity,
        )
        db.add(stage_item)
    db.commit()
    db.refresh(stage_item)
    return stage_item


def update_item(
    db: Session,
    stage_id: uuid.UUID,
    stage_item_id: uuid.UUID,
    *,
    planned_quantity: Decimal,
) -> MassStageItem:
    stage = _get_stage_row(db, stage_id)
    _require_editable(stage)
    stage_item = _get_stage_item(db, stage, stage_item_id)
    stage_item.planned_quantity = planned_quantity
    db.commit()
    db.refresh(stage_item)
    return stage_item


def delete_item(
    db: Session, stage_id: uuid.UUID, stage_item_id: uuid.UUID
) -> None:
    stage = _get_stage_row(db, stage_id)
    _require_editable(stage)
    stage_item = _get_stage_item(db, stage, stage_item_id)
    db.delete(stage_item)
    db.commit()


# --- loading + returns (stock-touching) ----------------------------------

def _item_slots(db: Session, stage_id: uuid.UUID, item_id: uuid.UUID):
    """The (stage_item, slot, work_order) triples for one item across a stage,
    ordered by slot `sort_order` -- the input to the load/return allocators."""
    return (
        db.query(MassStageItem, MassStageWorkOrder, WorkOrder)
        .join(
            MassStageWorkOrder,
            MassStageItem.stage_work_order_id == MassStageWorkOrder.id,
        )
        .join(WorkOrder, MassStageWorkOrder.work_order_id == WorkOrder.id)
        .filter(
            MassStageWorkOrder.stage_id == stage_id,
            MassStageItem.item_id == item_id,
        )
        .order_by(MassStageWorkOrder.sort_order)
        .all()
    )


def load_item(
    db: Session,
    stage_id: uuid.UUID,
    *,
    item_id: uuid.UUID,
    quantity: Decimal,
    user_id: Optional[uuid.UUID],
) -> None:
    """Stage `quantity` of one item onto the truck: split across the slots that
    planned it (fill in `sort_order`, overflow to the last) and write one real
    `dispense` per slice carrying that slot's work order (number + id),
    incrementing each slot's `loaded_quantity`. All slices commit atomically
    under one `SELECT ... FOR UPDATE` on the item row.

    Raises `StageStateError` unless loading, `ItemNotFoundError` if unknown,
    `StageItemNotFoundError` if no slot planned it, and `NegativeQuantityError`
    (rolled back) on overdraft."""
    stage = _get_stage_row(db, stage_id)
    if not ms.can_load(stage.status):
        raise StageStateError("Items can only be loaded while the stage is loading.")

    item = db.query(Item).filter(Item.id == item_id).with_for_update().first()
    if item is None:
        raise ItemNotFoundError("Item not found.")

    rows = _item_slots(db, stage.id, item_id)
    if not rows:
        raise StageItemNotFoundError("This item is not planned in this stage.")

    allocations = ms.allocate_load(
        [
            ms.RoomPlan(key=si.id, planned=si.planned_quantity, loaded=si.loaded_quantity)
            for si, _slot, _w in rows
        ],
        quantity,
    )
    by_id = {si.id: (si, slot, w) for si, slot, w in rows}

    try:
        for alloc in allocations:
            si, _slot, work_order = by_id[alloc.key]
            item.quantity = apply_delta(item.quantity, "dispense", alloc.quantity)
            db.add(
                Transaction(
                    item_id=item.id,
                    user_id=user_id,
                    transaction_type="dispense",
                    quantity=alloc.quantity,
                    unit_price=item.price,
                    work_order_number=work_order.number,
                    work_order_id=work_order.id,
                    reason=None,
                )
            )
            si.loaded_quantity = si.loaded_quantity + alloc.quantity
        db.commit()
    except NegativeQuantityError:
        db.rollback()
        raise


def return_item(
    db: Session,
    stage_id: uuid.UUID,
    *,
    item_id: uuid.UUID,
    quantity: Decimal,
) -> None:
    """Return `quantity` of one item to stock as "unused materials": add it back
    under the item row lock WITHOUT a transaction row, reverse-filling each
    slot's `returned_quantity` (last-loaded first).

    Raises `StageStateError` unless loading, `ItemNotFoundError` /
    `StageItemNotFoundError` as for load, and `ReturnExceedsLoadedError` if
    `quantity` exceeds net loaded."""
    stage = _get_stage_row(db, stage_id)
    if not ms.can_load(stage.status):
        raise StageStateError("Items can only be returned while the stage is loading.")

    item = db.query(Item).filter(Item.id == item_id).with_for_update().first()
    if item is None:
        raise ItemNotFoundError("Item not found.")

    rows = _item_slots(db, stage.id, item_id)
    if not rows:
        raise StageItemNotFoundError("This item is not planned in this stage.")

    allocations = ms.allocate_return(
        [
            ms.RoomLoaded(key=si.id, loaded=si.loaded_quantity, returned=si.returned_quantity)
            for si, _slot, _w in rows
        ],
        quantity,
    )
    by_id = {si.id: si for si, _slot, _w in rows}
    for alloc in allocations:
        by_id[alloc.key].returned_quantity = (
            by_id[alloc.key].returned_quantity + alloc.quantity
        )

    item.quantity = item.quantity + quantity
    db.commit()
