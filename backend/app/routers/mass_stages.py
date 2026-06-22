"""HTTP routes for the `/mass-stages` resource (planning).

Layer: routers (FastAPI). Thin handlers: parse via a Pydantic schema,
delegate to `app.services.mass_staging`, and translate any `DomainError`
through the shared `to_http`. Every route is Supervisor+.

Response bodies are assembled by the builder helpers below (not
`from_attributes`), because a planned item's `item_name` / `item_barcode`
come from the joined `Item`. Mirrors `routers/items.py::_item_response`.

Mounted by `app/main.py` under the root prefix.
"""

import uuid
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth_deps import get_current_user, require_min_role
from app.database import get_db
from app.domain import roles
from app.domain.errors import DomainError, StageItemNotFoundError
from app.models import MassStage, MassStageItem, MassStageRoom, User
from app.routers._errors import to_http
from app.schemas.mass_stages import (
    ActiveRoom,
    LoadRequest,
    MassStageCreate,
    MassStageDetail,
    MassStageSummary,
    MassStageUpdate,
    MergedItem,
    QuickRoomCreate,
    ReturnRequest,
    RoomAssign,
    RoomCreate,
    RoomDetail,
    RoomUpdate,
    StageItemCreate,
    StageItemDetail,
    StageItemUpdate,
)
from app.services import mass_staging as ms_service

router = APIRouter(prefix="/mass-stages", tags=["mass-stages"])


# --- response builders ---------------------------------------------------

def _item_detail(stage_item: MassStageItem) -> StageItemDetail:
    return StageItemDetail(
        id=stage_item.id,
        item_id=stage_item.item_id,
        item_name=stage_item.item.name,
        item_barcode=stage_item.item.barcode,
        item_quantity=stage_item.item.quantity,
        planned_quantity=stage_item.planned_quantity,
        loaded_quantity=stage_item.loaded_quantity,
        returned_quantity=stage_item.returned_quantity,
    )


def _room_detail(room: MassStageRoom) -> RoomDetail:
    return RoomDetail(
        id=room.id,
        room_number=room.room_number,
        work_order_number=room.work_order_number,
        sort_order=room.sort_order,
        assigned_to_id=room.assigned_to_id,
        assigned_to_username=room.assignee.username if room.assignee else None,
        items=[_item_detail(si) for si in room.items],
    )


def _merged_items(stage: MassStage) -> list[MergedItem]:
    """Roll the stage's planned items up by item_id (the unit the supervisor
    loads). First-seen order is preserved across rooms."""
    agg: dict = {}
    order: list = []
    for room in stage.rooms:
        for si in room.items:
            if si.item_id not in agg:
                agg[si.item_id] = {
                    "name": si.item.name,
                    "barcode": si.item.barcode,
                    "on_hand": si.item.quantity,
                    "planned": Decimal(0),
                    "loaded": Decimal(0),
                    "returned": Decimal(0),
                }
                order.append(si.item_id)
            a = agg[si.item_id]
            a["planned"] += si.planned_quantity
            a["loaded"] += si.loaded_quantity
            a["returned"] += si.returned_quantity

    merged = []
    for item_id in order:
        a = agg[item_id]
        planned, loaded, returned = a["planned"], a["loaded"], a["returned"]
        merged.append(
            MergedItem(
                item_id=item_id,
                item_name=a["name"],
                item_barcode=a["barcode"],
                on_hand=a["on_hand"],
                planned_total=planned,
                loaded_total=loaded,
                returned_total=returned,
                overflow=max(Decimal(0), loaded - planned),
                net_consumed=loaded - returned,
                remaining_to_load=max(Decimal(0), planned - loaded),
            )
        )
    return merged


def _stage_detail(stage: MassStage) -> MassStageDetail:
    return MassStageDetail(
        id=stage.id,
        building_name=stage.building_name,
        status=stage.status,
        created_at=stage.created_at,
        rooms=[_room_detail(r) for r in stage.rooms],
        merged_items=_merged_items(stage),
    )


def _stage_summary(stage: MassStage) -> MassStageSummary:
    item_ids = {si.item_id for room in stage.rooms for si in room.items}
    return MassStageSummary(
        id=stage.id,
        building_name=stage.building_name,
        status=stage.status,
        room_count=len(stage.rooms),
        item_count=len(item_ids),
        created_at=stage.created_at,
    )


# --- stages --------------------------------------------------------------

@router.post("/", response_model=MassStageSummary, status_code=201)
def create_stage(
    payload: MassStageCreate,
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Create a planning stage for a building. Supervisor+. 400 if an active
    stage already exists for that building."""
    try:
        stage = ms_service.create_stage(
            db, building_name=payload.building_name, created_by_id=user.id
        )
        return _stage_summary(stage)
    except DomainError as exc:
        raise to_http(exc)


@router.get("/", response_model=list[MassStageSummary])
def list_stages(
    status: Optional[str] = Query(None),
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """List stages newest-first, optionally filtered by `status`. Supervisor+.
    Scoped: a supervisor sees only stages they created; admin/owner see all."""
    return [
        _stage_summary(s) for s in ms_service.list_stages(db, status=status, user=user)
    ]


# Declared before the `/{stage_id}` routes so "quick-room" / "active-rooms"
# are not captured as a stage_id path param.

@router.post("/quick-room", response_model=MassStageSummary, status_code=201)
def quick_room(
    payload: QuickRoomCreate,
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Save a work order with a room from the scan gate: find-or-create the
    building's active stage and append the room. Supervisor+. Returns the parent
    stage summary (the UI reads `room_count` to know when a building becomes a
    Mass Stage card). 400 if the building is already loading or the room number
    is taken."""
    try:
        stage = ms_service.add_room_to_building(
            db,
            building_name=payload.building_name,
            room_number=payload.room_number,
            work_order_number=payload.work_order_number,
            created_by_id=user.id,
            assigned_to_id=payload.assigned_to_id,
        )
        return _stage_summary(stage)
    except DomainError as exc:
        raise to_http(exc)


@router.get("/active-rooms", response_model=list[ActiveRoom])
def list_active_rooms(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Flat list of work-order cards across non-completed stages, **scoped to
    the caller**: a technician sees only rooms assigned to them, a supervisor
    only rooms they created, admin/owner all. Any authenticated user."""
    return [ActiveRoom(**row) for row in ms_service.list_active_rooms(db, user=user)]


@router.get(
    "/{stage_id}",
    response_model=MassStageDetail,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def get_stage(stage_id: uuid.UUID, db: Session = Depends(get_db)):
    """Full stage detail (rooms + planned items). Supervisor+. 404 if unknown."""
    try:
        return _stage_detail(ms_service.get_stage(db, stage_id))
    except DomainError as exc:
        raise to_http(exc)


@router.patch(
    "/{stage_id}",
    response_model=MassStageSummary,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def update_stage(
    stage_id: uuid.UUID,
    payload: MassStageUpdate,
    db: Session = Depends(get_db),
):
    """Rename and/or change status. Supervisor+. 400 on an invalid status
    transition or a building-name collision; 404 if unknown."""
    try:
        stage = ms_service.update_stage(
            db, stage_id, building_name=payload.building_name, status=payload.status
        )
        return _stage_summary(stage)
    except DomainError as exc:
        raise to_http(exc)


@router.delete(
    "/{stage_id}",
    status_code=204,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def delete_stage(stage_id: uuid.UUID, db: Session = Depends(get_db)):
    """Delete a stage (rooms/items cascade). Supervisor+. Does not reverse
    dispenses already written by loading. 404 if unknown."""
    try:
        ms_service.delete_stage(db, stage_id)
    except DomainError as exc:
        raise to_http(exc)


@router.post("/{stage_id}/reuse", response_model=MassStageSummary, status_code=201)
def reuse_stage(
    stage_id: uuid.UUID,
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Spin off a fresh planning stage from a completed one — same building +
    rooms (work orders cleared), empty item lists. Supervisor+. 400 if the
    source is not completed or the building already has an active stage."""
    try:
        stage = ms_service.reuse_stage(db, stage_id, created_by_id=user.id)
        return _stage_summary(stage)
    except DomainError as exc:
        raise to_http(exc)


# --- rooms ---------------------------------------------------------------

@router.post(
    "/{stage_id}/rooms",
    response_model=RoomDetail,
    status_code=201,
)
def add_room(
    stage_id: uuid.UUID,
    payload: RoomCreate,
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Add a room (one work order) to a planning stage. Supervisor+. Records the
    creator and an optional technician assignee. 400 if the stage is not in
    planning, the room number is already used, or the assignee is not a
    technician; 404 if unknown."""
    try:
        room = ms_service.add_room(
            db,
            stage_id,
            room_number=payload.room_number,
            work_order_number=payload.work_order_number,
            created_by_id=user.id,
            assigned_to_id=payload.assigned_to_id,
        )
        return _room_detail(room)
    except DomainError as exc:
        raise to_http(exc)


@router.patch(
    "/{stage_id}/rooms/{room_id}/assign",
    response_model=RoomDetail,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def assign_room(
    stage_id: uuid.UUID,
    room_id: uuid.UUID,
    payload: RoomAssign,
    db: Session = Depends(get_db),
):
    """Assign a work order (room) to a technician, or clear it (null).
    Supervisor+. Allowed while planning or loading, not on a completed stage.
    400 if the assignee is not a technician; 404 if the stage/room is unknown."""
    try:
        room = ms_service.assign_room(
            db, stage_id, room_id, assigned_to_id=payload.assigned_to_id
        )
        return _room_detail(room)
    except DomainError as exc:
        raise to_http(exc)


@router.patch(
    "/{stage_id}/rooms/{room_id}",
    response_model=RoomDetail,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def update_room(
    stage_id: uuid.UUID,
    room_id: uuid.UUID,
    payload: RoomUpdate,
    db: Session = Depends(get_db),
):
    """Edit a room's number/work order. Supervisor+, planning only. 404 if the
    stage or room is unknown."""
    try:
        room = ms_service.update_room(
            db,
            stage_id,
            room_id,
            room_number=payload.room_number,
            work_order_number=payload.work_order_number,
        )
        return _room_detail(room)
    except DomainError as exc:
        raise to_http(exc)


@router.delete(
    "/{stage_id}/rooms/{room_id}",
    status_code=204,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def delete_room(
    stage_id: uuid.UUID,
    room_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Remove a room (its planned items cascade). Supervisor+, planning only."""
    try:
        ms_service.delete_room(db, stage_id, room_id)
    except DomainError as exc:
        raise to_http(exc)


# --- planned items -------------------------------------------------------

@router.post(
    "/{stage_id}/rooms/{room_id}/items",
    response_model=StageItemDetail,
    status_code=201,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def add_item(
    stage_id: uuid.UUID,
    room_id: uuid.UUID,
    payload: StageItemCreate,
    db: Session = Depends(get_db),
):
    """Plan an item for a room (estimate, not a transaction). Supervisor+,
    planning only. Upserts by (room, item). 404 if the stage/room/item is
    unknown (or the item is archived)."""
    try:
        stage_item = ms_service.add_item(
            db,
            stage_id,
            room_id,
            item_id=payload.item_id,
            planned_quantity=payload.planned_quantity,
        )
        return _item_detail(stage_item)
    except DomainError as exc:
        raise to_http(exc)


@router.patch(
    "/{stage_id}/rooms/{room_id}/items/{stage_item_id}",
    response_model=StageItemDetail,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def update_item(
    stage_id: uuid.UUID,
    room_id: uuid.UUID,
    stage_item_id: uuid.UUID,
    payload: StageItemUpdate,
    db: Session = Depends(get_db),
):
    """Edit a planned item's quantity. Supervisor+, planning only. 404 if the
    stage or planned item is unknown."""
    try:
        stage_item = ms_service.update_item(
            db, stage_id, stage_item_id, planned_quantity=payload.planned_quantity
        )
        return _item_detail(stage_item)
    except DomainError as exc:
        raise to_http(exc)


@router.delete(
    "/{stage_id}/rooms/{room_id}/items/{stage_item_id}",
    status_code=204,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def delete_item(
    stage_id: uuid.UUID,
    room_id: uuid.UUID,
    stage_item_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Remove a planned item. Supervisor+, planning only."""
    try:
        ms_service.delete_item(db, stage_id, stage_item_id)
    except DomainError as exc:
        raise to_http(exc)


# --- loading + returns ---------------------------------------------------

def _merged_for(stage: MassStage, item_id: uuid.UUID) -> MergedItem:
    """The merged rollup row for one item (the load/return response). The
    service guarantees the item is planned, so the fallback is defensive."""
    for merged in _merged_items(stage):
        if merged.item_id == item_id:
            return merged
    raise StageItemNotFoundError("This item is not planned in this stage.")


@router.post(
    "/{stage_id}/load",
    response_model=MergedItem,
)
def load_item(
    stage_id: uuid.UUID,
    payload: LoadRequest,
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Stage an item onto the truck: split into per-room dispenses on each
    room's work order. Supervisor+, loading only. 400 if the stage is not
    loading or stock would overdraw; 404 if the item is unknown or not planned.
    Returns the item's updated merged rollup."""
    try:
        ms_service.load_item(
            db, stage_id, item_id=payload.item_id, quantity=payload.quantity, user_id=user.id
        )
        stage = ms_service.get_stage(db, stage_id)
        return _merged_for(stage, payload.item_id)
    except DomainError as exc:
        raise to_http(exc)


@router.post(
    "/{stage_id}/return",
    response_model=MergedItem,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def return_item(
    stage_id: uuid.UUID,
    payload: ReturnRequest,
    db: Session = Depends(get_db),
):
    """Return unused materials to stock (silent stock-add, no ledger row).
    Supervisor+, loading only. 400 if the stage is not loading or the amount
    exceeds net loaded; 404 if the item is unknown or not planned. Returns the
    item's updated merged rollup."""
    try:
        ms_service.return_item(
            db, stage_id, item_id=payload.item_id, quantity=payload.quantity
        )
        stage = ms_service.get_stage(db, stage_id)
        return _merged_for(stage, payload.item_id)
    except DomainError as exc:
        raise to_http(exc)
