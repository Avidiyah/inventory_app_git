"""Mass-staging CRUD service.

Layer: services. Owns the session and translates DB / state violations into
the domain vocabulary so routers stay thin -- mirrors `services/items.py`.

This module covers stages, rooms, planned items, loading, and unused-material
returns. Planning never moves stock; loading writes real `dispense` rows, and
returns add stock back through the stage tables without writing ledger rows.

Editability is gated by the stage's status via `domain.mass_staging`:
rooms/items may only be changed while `planning` (`StageStateError` otherwise),
and status changes are policed by `validate_transition`.
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
    InvalidAssigneeError,
    ItemNotFoundError,
    NegativeQuantityError,
    RoomNotFoundError,
    StageItemNotFoundError,
    StageNotFoundError,
    StageStateError,
)
from app.domain.quantity import apply_delta
from app.models import Item, MassStage, MassStageItem, MassStageRoom, Transaction, User


# --- internal helpers ----------------------------------------------------

def _active_stage_exists(db: Session, building_name: str) -> bool:
    """Is there already a non-completed stage for this building? Mirrors the
    DB partial unique index `uq_mass_stages_active_building`."""
    return bool(
        db.query(MassStage.id)
        .filter(
            MassStage.building_name == building_name,
            MassStage.status != ms.STATUS_COMPLETED,
        )
        .first()
    )


def _has_room_missing_work_order(db: Session, stage_id: uuid.UUID) -> bool:
    """True if any room in the stage has a blank work order. Reused stages start
    with cleared work orders that must be re-entered before the stage can load."""
    rooms = (
        db.query(MassStageRoom.work_order_number)
        .filter(MassStageRoom.stage_id == stage_id)
        .all()
    )
    return any(not (wo or "").strip() for (wo,) in rooms)


def _get_stage_row(db: Session, stage_id: uuid.UUID) -> MassStage:
    stage = db.query(MassStage).filter(MassStage.id == stage_id).first()
    if stage is None:
        raise StageNotFoundError("Stage not found.")
    return stage


def _get_room(db: Session, stage: MassStage, room_id: uuid.UUID) -> MassStageRoom:
    room = (
        db.query(MassStageRoom)
        .filter(MassStageRoom.id == room_id, MassStageRoom.stage_id == stage.id)
        .first()
    )
    if room is None:
        raise RoomNotFoundError("Room not found.")
    return room


def _get_stage_item(
    db: Session, stage: MassStage, stage_item_id: uuid.UUID
) -> MassStageItem:
    stage_item = (
        db.query(MassStageItem)
        .join(MassStageRoom, MassStageItem.room_id == MassStageRoom.id)
        .filter(MassStageItem.id == stage_item_id, MassStageRoom.stage_id == stage.id)
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


def _validate_assignee(db: Session, assigned_to_id: Optional[uuid.UUID]) -> None:
    """A work order may be unassigned (`None`), but if assigned the target must
    exist and be a technician -- you assign work orders to technicians. Raises
    `InvalidAssigneeError` otherwise."""
    if assigned_to_id is None:
        return
    user = db.query(User).filter(User.id == assigned_to_id).first()
    if user is None or user.role != roles.ROLE_TECHNICIAN:
        raise InvalidAssigneeError(
            "Work orders can only be assigned to a technician."
        )


def _room_visible_to(room: MassStageRoom, user: Optional[User]) -> bool:
    """Visibility rule for a work order (room): admin/owner see all; a
    supervisor sees only rooms they created; a technician sees only rooms
    assigned to them. `None` user (internal/script) sees all."""
    if user is None or roles.role_at_least(user.role, roles.ROLE_ADMIN):
        return True
    if user.role == roles.ROLE_SUPERVISOR:
        return room.created_by_id == user.id
    return room.assigned_to_id == user.id


# --- stages --------------------------------------------------------------

def create_stage(
    db: Session, *, building_name: str, created_by_id: Optional[uuid.UUID]
) -> MassStage:
    """Create a `planning` stage for a building. Raises
    `DuplicateBuildingStageError` if an active stage already exists for it
    (pre-check + IntegrityError catch, race-safe like `create_item`)."""
    if _active_stage_exists(db, building_name):
        raise DuplicateBuildingStageError(
            f"An active stage already exists for {building_name}."
        )
    stage = MassStage(
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
            f"An active stage already exists for {building_name}."
        ) from exc
    db.refresh(stage)
    return stage


def add_room_to_building(
    db: Session,
    *,
    building_name: str,
    room_number: str,
    work_order_number: str,
    created_by_id: Optional[uuid.UUID],
    assigned_to_id: Optional[uuid.UUID] = None,
) -> MassStage:
    """Quick-add a work order from the scan gate: find the building's active
    (non-completed) stage or create one, then append the room. This is the
    "save a work order with a room" entry point -- it writes the SAME
    `mass_stages`/`mass_stage_rooms` data the Mass Stage page edits, so a
    quick-added room and a planned one are one model (see
    `docs/current-state.md`).

    The stage is left in `planning` so the room is immediately scannable
    (the by-room dispense works on any non-completed stage) without forcing the
    truck-load workflow. Returns the parent stage (so the caller learns the new
    `room_count` -- a 2nd room makes the building a card on the Mass Stage page).

    Raises `StageStateError` if the building's active stage is already loading
    (its plan is read-only) or the room number is already used, reusing
    `add_room`'s guards, and `InvalidAssigneeError` if `assigned_to_id` is not a
    technician (checked before any stage is created).
    """
    _validate_assignee(db, assigned_to_id)  # fail before creating a stage
    stage = (
        db.query(MassStage)
        .filter(
            MassStage.building_name == building_name,
            MassStage.status != ms.STATUS_COMPLETED,
        )
        .first()
    )
    if stage is None:
        stage = create_stage(
            db, building_name=building_name, created_by_id=created_by_id
        )
    add_room(
        db,
        stage.id,
        room_number=room_number,
        work_order_number=work_order_number,
        created_by_id=created_by_id,
        assigned_to_id=assigned_to_id,
    )
    db.refresh(stage)
    return stage


def list_active_rooms(db: Session, *, user: Optional[User] = None) -> list[dict]:
    """Flat list of work-order rooms across non-completed stages -- the data
    source for the scan gate's tappable cards. Rooms with a blank work order
    (reused stages clear them until re-entered) are skipped, and the list is
    **scoped to what `user` may see** (`_room_visible_to`): a technician sees
    only rooms assigned to them, a supervisor only rooms they created,
    admin/owner all. Ordered building, then room sort_order."""
    stages = (
        db.query(MassStage)
        .options(
            selectinload(MassStage.rooms).joinedload(MassStageRoom.creator),
            selectinload(MassStage.rooms).joinedload(MassStageRoom.assignee),
        )
        .filter(MassStage.status != ms.STATUS_COMPLETED)
        .order_by(MassStage.building_name, MassStage.created_at.desc())
        .all()
    )
    rooms: list[dict] = []
    for stage in stages:
        for room in sorted(stage.rooms, key=lambda r: r.sort_order):
            if not (room.work_order_number or "").strip():
                continue
            if not _room_visible_to(room, user):
                continue
            rooms.append(
                {
                    "stage_id": stage.id,
                    "building_name": stage.building_name,
                    "status": stage.status,
                    "room_id": room.id,
                    "room_number": room.room_number,
                    "work_order_number": room.work_order_number,
                    "sort_order": room.sort_order,
                    "created_by_id": room.created_by_id,
                    "created_by_username": room.creator.username if room.creator else None,
                    "assigned_to_id": room.assigned_to_id,
                    "assigned_to_username": room.assignee.username if room.assignee else None,
                }
            )
    return rooms


def list_stages(
    db: Session, *, status: Optional[str] = None, user: Optional[User] = None
) -> Sequence[MassStage]:
    """Stages newest-first, optionally filtered by status. Rooms/items are
    eager-loaded so the summary's room/item counts need no extra queries.

    Scoped for the Mass Stage page: admin/owner (and `None`/internal) see every
    stage; a supervisor sees only stages they created. (Technicians never reach
    this page; the same created_by filter would show them nothing.)"""
    q = db.query(MassStage).options(
        selectinload(MassStage.rooms).selectinload(MassStageRoom.items)
    )
    if status is not None:
        q = q.filter(MassStage.status == status)
    if user is not None and not roles.role_at_least(user.role, roles.ROLE_ADMIN):
        q = q.filter(MassStage.created_by_id == user.id)
    return q.order_by(MassStage.created_at.desc()).all()


def get_stage(db: Session, stage_id: uuid.UUID) -> MassStage:
    """Full stage with rooms -> items -> item eager-loaded. Raises
    `StageNotFoundError` if unknown."""
    stage = (
        db.query(MassStage)
        .options(
            selectinload(MassStage.rooms).joinedload(MassStageRoom.assignee),
            selectinload(MassStage.rooms)
            .selectinload(MassStageRoom.items)
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
    building_name: Optional[str] = None,
    status: Optional[str] = None,
) -> MassStage:
    """Rename and/or transition a stage. A status change is validated by
    `domain.mass_staging.validate_transition` (forward-only); reaching
    `completed` stamps `completed_at`. A rename that collides with another
    active stage for the new building raises `DuplicateBuildingStageError`."""
    stage = _get_stage_row(db, stage_id)

    if status is not None and status != stage.status:
        ms.validate_transition(stage.status, status)
        if status == ms.STATUS_LOADING and _has_room_missing_work_order(db, stage.id):
            # Reused stages start with cleared work orders; every room must have
            # one before loading so the per-room dispenses are attributed.
            raise StageStateError(
                "Set a work order for every room before saving."
            )
        stage.status = status
        if status == ms.STATUS_COMPLETED:
            stage.completed_at = datetime.now(timezone.utc)

    if building_name is not None and building_name != stage.building_name:
        if stage.status != ms.STATUS_COMPLETED and _active_stage_exists(
            db, building_name
        ):
            raise DuplicateBuildingStageError(
                f"An active stage already exists for {building_name}."
            )
        stage.building_name = building_name

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
    """Delete a stage; its rooms and planned items cascade away (ORM
    delete-orphan + DB `ON DELETE CASCADE`). Does NOT reverse any dispenses
    already written by loading. Raises `StageNotFoundError` if unknown."""
    stage = _get_stage_row(db, stage_id)
    db.delete(stage)
    db.commit()


def reuse_stage(
    db: Session, stage_id: uuid.UUID, *, created_by_id: Optional[uuid.UUID]
) -> MassStage:
    """Spin off a fresh `planning` stage from a completed one: same building and
    rooms (room numbers kept, work orders **cleared** to empty strings) with
    empty item lists. The source stage is left untouched as the saved record, so
    buildings/rooms are reused without re-typing them each job.

    Raises `StageStateError` if the source is not completed, and
    `DuplicateBuildingStageError` if the building already has an active stage.
    """
    source = _get_stage_row(db, stage_id)
    if source.status != ms.STATUS_COMPLETED:
        raise StageStateError("Only a completed stage can be reused.")
    if _active_stage_exists(db, source.building_name):
        raise DuplicateBuildingStageError(
            f"An active stage already exists for {source.building_name}."
        )

    new_stage = MassStage(
        building_name=source.building_name,
        status=ms.STATUS_PLANNING,
        created_by_id=created_by_id,
    )
    db.add(new_stage)
    db.flush()  # assign new_stage.id before copying rooms

    source_rooms = (
        db.query(MassStageRoom)
        .filter(MassStageRoom.stage_id == source.id)
        .order_by(MassStageRoom.sort_order)
        .all()
    )
    for room in source_rooms:
        db.add(
            MassStageRoom(
                stage_id=new_stage.id,
                room_number=room.room_number,
                work_order_number="",  # cleared; re-entered for the new job
                sort_order=room.sort_order,
                created_by_id=created_by_id,  # the reusing user owns the new rooms
                # assignment is not carried over; re-assign for the new job
            )
        )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateBuildingStageError(
            f"An active stage already exists for {source.building_name}."
        ) from exc
    db.refresh(new_stage)
    return new_stage


# --- rooms ---------------------------------------------------------------

def add_room(
    db: Session,
    stage_id: uuid.UUID,
    *,
    room_number: str,
    work_order_number: str,
    created_by_id: Optional[uuid.UUID] = None,
    assigned_to_id: Optional[uuid.UUID] = None,
) -> MassStageRoom:
    """Append a room (one work order) to a planning stage. `sort_order` is the
    current room count, so rooms keep entry order (drives load fill order).
    `created_by_id` records the author (drives supervisor visibility);
    `assigned_to_id` optionally assigns the work order to a technician
    (validated via `_validate_assignee`)."""
    stage = _get_stage_row(db, stage_id)
    _require_editable(stage)
    _validate_assignee(db, assigned_to_id)
    sort_order = (
        db.query(MassStageRoom).filter(MassStageRoom.stage_id == stage.id).count()
    )
    room = MassStageRoom(
        stage_id=stage.id,
        room_number=room_number,
        work_order_number=work_order_number,
        sort_order=sort_order,
        created_by_id=created_by_id,
        assigned_to_id=assigned_to_id,
    )
    db.add(room)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # UNIQUE(stage_id, room_number) -- surfaced through the generic state
        # guard with a specific message (400).
        raise StageStateError(
            f"Room {room_number} already exists in this stage."
        ) from exc
    db.refresh(room)
    return room


def update_room(
    db: Session,
    stage_id: uuid.UUID,
    room_id: uuid.UUID,
    *,
    room_number: Optional[str] = None,
    work_order_number: Optional[str] = None,
) -> MassStageRoom:
    stage = _get_stage_row(db, stage_id)
    _require_editable(stage)
    room = _get_room(db, stage, room_id)
    if room_number is not None:
        room.room_number = room_number
    if work_order_number is not None:
        room.work_order_number = work_order_number
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise StageStateError(
            f"Room {room_number} already exists in this stage."
        ) from exc
    db.refresh(room)
    return room


def delete_room(db: Session, stage_id: uuid.UUID, room_id: uuid.UUID) -> None:
    stage = _get_stage_row(db, stage_id)
    _require_editable(stage)
    room = _get_room(db, stage, room_id)
    db.delete(room)
    db.commit()


def assign_room(
    db: Session,
    stage_id: uuid.UUID,
    room_id: uuid.UUID,
    *,
    assigned_to_id: Optional[uuid.UUID],
) -> MassStageRoom:
    """Assign a work order (room) to a technician, or clear it (`None`).
    Unlike plan edits this is allowed in `planning` and `loading` (assignment
    is management, not plan editing) but not on a `completed` stage. Raises
    `InvalidAssigneeError` if the target is not a technician."""
    stage = _get_stage_row(db, stage_id)
    if stage.status == ms.STATUS_COMPLETED:
        raise StageStateError("A completed stage is read-only.")
    room = _get_room(db, stage, room_id)
    _validate_assignee(db, assigned_to_id)
    room.assigned_to_id = assigned_to_id
    db.commit()
    db.refresh(room)
    return room


# --- planned items -------------------------------------------------------

def add_item(
    db: Session,
    stage_id: uuid.UUID,
    room_id: uuid.UUID,
    *,
    item_id: uuid.UUID,
    planned_quantity: Decimal,
) -> MassStageItem:
    """Add (or update) the planned quantity of an item on a room. Upsert by
    `(room_id, item_id)`: re-adding the same item sets its planned quantity
    rather than erroring, which suits the search-and-add UI. Raises
    `ItemNotFoundError` if the item is unknown or archived."""
    stage = _get_stage_row(db, stage_id)
    _require_editable(stage)
    room = _get_room(db, stage, room_id)

    item = (
        db.query(Item)
        .filter(Item.id == item_id, Item.archived_at.is_(None))
        .first()
    )
    if item is None:
        raise ItemNotFoundError("Item not found.")

    stage_item = (
        db.query(MassStageItem)
        .filter(MassStageItem.room_id == room.id, MassStageItem.item_id == item_id)
        .first()
    )
    if stage_item is not None:
        stage_item.planned_quantity = planned_quantity
    else:
        stage_item = MassStageItem(
            room_id=room.id, item_id=item_id, planned_quantity=planned_quantity
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

def _item_rooms(db: Session, stage_id: uuid.UUID, item_id: uuid.UUID):
    """The (stage_item, room) pairs for one item across a stage, ordered by
    room `sort_order` -- the input to the load/return allocators."""
    return (
        db.query(MassStageItem, MassStageRoom)
        .join(MassStageRoom, MassStageItem.room_id == MassStageRoom.id)
        .filter(MassStageRoom.stage_id == stage_id, MassStageItem.item_id == item_id)
        .order_by(MassStageRoom.sort_order)
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
    """Stage `quantity` of one item onto the truck.

    Splits the quantity across the rooms that planned the item (fill in
    `sort_order`, overflow to the last room) and writes one real `dispense`
    transaction per room slice carrying that room's work order, incrementing
    each room's `loaded_quantity`. All slices commit atomically under a single
    `SELECT ... FOR UPDATE` on the item row, mirroring
    `services.transactions.apply_transaction`.

    Raises `StageStateError` unless the stage is loading, `ItemNotFoundError`
    if the item is unknown, `StageItemNotFoundError` if no room planned it, and
    `NegativeQuantityError` (rolled back) if the dispenses would overdraw stock.
    """
    stage = _get_stage_row(db, stage_id)
    if not ms.can_load(stage.status):
        raise StageStateError("Items can only be loaded while the stage is loading.")

    # Lock the item row first so concurrent loads/dispenses of this item
    # serialise (and the loaded_quantity read below is fresh under the lock).
    item = db.query(Item).filter(Item.id == item_id).with_for_update().first()
    if item is None:
        raise ItemNotFoundError("Item not found.")

    rows = _item_rooms(db, stage.id, item_id)
    if not rows:
        raise StageItemNotFoundError("This item is not planned in this stage.")

    allocations = ms.allocate_load(
        [
            ms.RoomPlan(key=si.id, planned=si.planned_quantity, loaded=si.loaded_quantity)
            for si, _room in rows
        ],
        quantity,
    )
    by_id = {si.id: (si, room) for si, room in rows}

    try:
        for alloc in allocations:
            si, room = by_id[alloc.key]
            item.quantity = apply_delta(item.quantity, "dispense", alloc.quantity)
            db.add(
                Transaction(
                    item_id=item.id,
                    user_id=user_id,
                    transaction_type="dispense",
                    quantity=alloc.quantity,
                    # Snapshot the price under the item row lock, matching
                    # the ordinary stock/dispense path in
                    # `services.transactions.apply_transaction`.
                    unit_price=item.price,
                    work_order_number=room.work_order_number,
                    reason=None,
                )
            )
            si.loaded_quantity = si.loaded_quantity + alloc.quantity
        db.commit()
    except NegativeQuantityError:
        # Overdraft: leave stock and the audit log untouched.
        db.rollback()
        raise


def return_item(
    db: Session,
    stage_id: uuid.UUID,
    *,
    item_id: uuid.UUID,
    quantity: Decimal,
) -> None:
    """Return `quantity` of one item to stock as "unused materials".

    Adds the quantity back to the item under the same item row lock, WITHOUT
    writing a transaction row (the deliberate, isolated exception -- see
    `docs/current-state.md`), and reverse-fills
    the per-room `returned_quantity` (last-loaded room first).

    Raises `StageStateError` unless loading, `ItemNotFoundError` /
    `StageItemNotFoundError` as for load, and `ReturnExceedsLoadedError` if
    `quantity` exceeds net loaded (raised before any mutation)."""
    stage = _get_stage_row(db, stage_id)
    if not ms.can_load(stage.status):
        raise StageStateError("Items can only be returned while the stage is loading.")

    item = db.query(Item).filter(Item.id == item_id).with_for_update().first()
    if item is None:
        raise ItemNotFoundError("Item not found.")

    rows = _item_rooms(db, stage.id, item_id)
    if not rows:
        raise StageItemNotFoundError("This item is not planned in this stage.")

    allocations = ms.allocate_return(
        [
            ms.RoomLoaded(key=si.id, loaded=si.loaded_quantity, returned=si.returned_quantity)
            for si, _room in rows
        ],
        quantity,
    )
    by_id = {si.id: si for si, _room in rows}
    for alloc in allocations:
        by_id[alloc.key].returned_quantity = by_id[alloc.key].returned_quantity + alloc.quantity

    # Silent stock-add: on-hand goes back up with NO ledger row.
    item.quantity = item.quantity + quantity
    db.commit()
