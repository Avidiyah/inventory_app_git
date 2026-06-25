"""HTTP routes for the `/mass-stages` resource (truck planning).

Layer: routers (FastAPI). Thin handlers: parse via a Pydantic schema, delegate
to `app.services.mass_staging`, translate `DomainError` via `to_http`. Every
route is Supervisor+.

A stage references standalone work orders through ordered slots
(`mass_stage_work_orders`); response bodies are assembled by the builders below
because a slot's `work_order_number` / unit / status come from the joined
`WorkOrder` and a planned item's `item_name` from the joined `Item`.
"""

import uuid
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth_deps import require_min_role
from app.database import get_db
from app.domain import roles
from app.domain.errors import DomainError, StageItemNotFoundError
from app.models import MassStage, MassStageItem, MassStageWorkOrder, User
from app.routers._errors import to_http
from app.schemas.mass_stages import (
    LoadRequest,
    MassStageCreate,
    MassStageDetail,
    MassStageSummary,
    MassStageUpdate,
    MergedItem,
    ReturnRequest,
    StageItemCreate,
    StageItemDetail,
    StageItemUpdate,
    StageWorkOrderCreate,
    StageWorkOrderDetail,
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


def _slot_detail(slot: MassStageWorkOrder) -> StageWorkOrderDetail:
    w = slot.work_order
    return StageWorkOrderDetail(
        id=slot.id,
        work_order_id=slot.work_order_id,
        work_order_number=w.number,
        unit_number=w.unit_number,
        status=w.status,
        sort_order=slot.sort_order,
        assigned_to_id=w.assigned_to_id,
        assigned_to_username=w.assignee.username if w.assignee else None,
        items=[_item_detail(si) for si in slot.items],
    )


def _merged_items(stage: MassStage) -> list[MergedItem]:
    """Roll the stage's planned items up by item_id (the unit the supervisor
    loads). First-seen order is preserved across slots."""
    agg: dict = {}
    order: list = []
    for slot in stage.work_order_slots:
        for si in slot.items:
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
        community=stage.community,
        building_name=stage.building_name,
        status=stage.status,
        created_at=stage.created_at,
        work_orders=[_slot_detail(s) for s in stage.work_order_slots],
        merged_items=_merged_items(stage),
    )


def _stage_summary(stage: MassStage) -> MassStageSummary:
    item_ids = {si.item_id for slot in stage.work_order_slots for si in slot.items}
    return MassStageSummary(
        id=stage.id,
        community=stage.community,
        building_name=stage.building_name,
        status=stage.status,
        unit_count=len(stage.work_order_slots),
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
    """Create a planning stage for a community + building. Supervisor+."""
    try:
        stage = ms_service.create_stage(
            db,
            community=payload.community,
            building_name=payload.building_name,
            created_by_id=user.id,
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


@router.get(
    "/{stage_id}",
    response_model=MassStageDetail,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def get_stage(stage_id: uuid.UUID, db: Session = Depends(get_db)):
    """Full stage detail (slots + planned items). Supervisor+. 404 if unknown."""
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
    """Rename (community/building) and/or change status. Supervisor+."""
    try:
        stage = ms_service.update_stage(
            db,
            stage_id,
            community=payload.community,
            building_name=payload.building_name,
            status=payload.status,
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
    """Delete a stage (slots/items cascade; referenced work orders untouched).
    Supervisor+."""
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
    """Start a fresh planning stage for the same community + building as a
    completed one. Supervisor+. 400 if the source is not completed or the
    building already has an active stage."""
    try:
        stage = ms_service.reuse_stage(db, stage_id, created_by_id=user.id)
        return _stage_summary(stage)
    except DomainError as exc:
        raise to_http(exc)


# --- work-order slots ----------------------------------------------------

@router.post(
    "/{stage_id}/work-orders",
    response_model=StageWorkOrderDetail,
    status_code=201,
)
def add_work_order(
    stage_id: uuid.UUID,
    payload: StageWorkOrderCreate,
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Add a work order to the stage's truck plan (find-or-create by number,
    community/building enforced to match the stage). Supervisor+, planning only.
    400 if the work order belongs to a different building or the assignee is not
    a technician."""
    try:
        slot = ms_service.add_work_order_to_stage(
            db,
            stage_id,
            work_order_number=payload.work_order_number,
            unit_number=payload.unit_number,
            assigned_to_id=payload.assigned_to_id,
            created_by_id=user.id,
        )
        # Re-fetch the stage so the slot's joined work order is loaded.
        stage = ms_service.get_stage(db, stage_id)
        slot = next(s for s in stage.work_order_slots if s.id == slot.id)
        return _slot_detail(slot)
    except DomainError as exc:
        raise to_http(exc)


@router.delete(
    "/{stage_id}/work-orders/{slot_id}",
    status_code=204,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def delete_work_order(
    stage_id: uuid.UUID,
    slot_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Remove a work order from the stage's plan (its planned items cascade).
    Supervisor+, planning only."""
    try:
        ms_service.delete_slot(db, stage_id, slot_id)
    except DomainError as exc:
        raise to_http(exc)


# --- planned items -------------------------------------------------------

@router.post(
    "/{stage_id}/work-orders/{slot_id}/items",
    response_model=StageItemDetail,
    status_code=201,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def add_item(
    stage_id: uuid.UUID,
    slot_id: uuid.UUID,
    payload: StageItemCreate,
    db: Session = Depends(get_db),
):
    """Plan an item for a slot (estimate, not a transaction). Supervisor+,
    planning only. Upserts by (slot, item)."""
    try:
        stage_item = ms_service.add_item(
            db,
            stage_id,
            slot_id,
            item_id=payload.item_id,
            planned_quantity=payload.planned_quantity,
        )
        return _item_detail(stage_item)
    except DomainError as exc:
        raise to_http(exc)


@router.patch(
    "/{stage_id}/work-orders/{slot_id}/items/{stage_item_id}",
    response_model=StageItemDetail,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def update_item(
    stage_id: uuid.UUID,
    slot_id: uuid.UUID,
    stage_item_id: uuid.UUID,
    payload: StageItemUpdate,
    db: Session = Depends(get_db),
):
    """Edit a planned item's quantity. Supervisor+, planning only."""
    try:
        stage_item = ms_service.update_item(
            db, stage_id, stage_item_id, planned_quantity=payload.planned_quantity
        )
        return _item_detail(stage_item)
    except DomainError as exc:
        raise to_http(exc)


@router.delete(
    "/{stage_id}/work-orders/{slot_id}/items/{stage_item_id}",
    status_code=204,
    dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))],
)
def delete_item(
    stage_id: uuid.UUID,
    slot_id: uuid.UUID,
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
    for merged in _merged_items(stage):
        if merged.item_id == item_id:
            return merged
    raise StageItemNotFoundError("This item is not planned in this stage.")


@router.post("/{stage_id}/load", response_model=MergedItem)
def load_item(
    stage_id: uuid.UUID,
    payload: LoadRequest,
    user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """Stage an item onto the truck: split into per-slot dispenses on each slot's
    work order. Supervisor+, loading only."""
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
    Supervisor+, loading only."""
    try:
        ms_service.return_item(
            db, stage_id, item_id=payload.item_id, quantity=payload.quantity
        )
        stage = ms_service.get_stage(db, stage_id)
        return _merged_for(stage, payload.item_id)
    except DomainError as exc:
        raise to_http(exc)
