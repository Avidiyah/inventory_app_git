"""Database integration tests for mass-staging load + return (slot model).

A stage references standalone work orders through ordered slots; loading splits
a merged item into per-slot dispenses carrying that slot's work order (number +
id), and returning adds stock back silently. Also covers enforce-match on
add-work-order and the simplified reuse. Skip if no DB.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from decimal import Decimal

import pytest

from app.domain.errors import (
    DuplicateBuildingStageError,
    NegativeQuantityError,
    ReturnExceedsLoadedError,
    StageItemNotFoundError,
    StageStateError,
    WorkOrderStateError,
)
from app.models import Item, MassStageItem, Transaction, User, WorkOrder, WorkOrderItem
from app.routers.mass_stages import _merged_items
from app.services import auth
from app.services import work_orders as wo_service
from app.services.mass_staging import (
    add_item,
    add_work_order_to_stage,
    create_stage,
    get_stage,
    list_stages,
    load_item,
    return_item,
    reuse_stage,
    update_stage,
)


# --- seed helpers --------------------------------------------------------

def _seed_item(db, qty):
    item = Item(
        barcode=f"BC-{uuid.uuid4().hex[:10]}",
        name="Spray Paint",
        quantity=Decimal(qty),
        location="Bay 1",
    )
    db.add(item)
    db.flush()
    return item


def _seed_user(db, role):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _building():
    return f"B-{uuid.uuid4().hex[:6]}"


def _seed_loading_stage(db, item, planned1=10, planned2=5):
    """A loading-status stage with the item planned in two slots (n1, n2)."""
    stage = create_stage(db, community="Scholars", building_name=_building(), created_by_id=None)
    n1 = f"WO-A-{uuid.uuid4().hex[:5]}"
    n2 = f"WO-B-{uuid.uuid4().hex[:5]}"
    s1 = add_work_order_to_stage(db, stage.id, work_order_number=n1, created_by_id=None)
    s2 = add_work_order_to_stage(db, stage.id, work_order_number=n2, created_by_id=None)
    add_item(db, stage.id, s1.id, item_id=item.id, planned_quantity=Decimal(planned1))
    add_item(db, stage.id, s2.id, item_id=item.id, planned_quantity=Decimal(planned2))
    update_stage(db, stage.id, status="loading")
    return stage, s1, s2, n1, n2


def _dispenses(db, item_id):
    return (
        db.query(Transaction)
        .filter(
            Transaction.item_id == item_id,
            Transaction.transaction_type == "dispense",
        )
        .all()
    )


def _stage_item(db, slot_id, item_id):
    return (
        db.query(MassStageItem)
        .filter(
            MassStageItem.stage_work_order_id == slot_id,
            MassStageItem.item_id == item_id,
        )
        .one()
    )


def _wo_line(db, work_order_id, item_id):
    return (
        db.query(WorkOrderItem)
        .filter(
            WorkOrderItem.work_order_id == work_order_id,
            WorkOrderItem.item_id == item_id,
        )
        .first()
    )


# --- load ----------------------------------------------------------------

def test_load_splits_across_slots_with_work_orders(db):
    item = _seed_item(db, 100)
    stage, s1, s2, n1, n2 = _seed_loading_stage(db, item)  # planned 10 + 5

    load_item(db, stage.id, item_id=item.id, quantity=Decimal(16), user_id=None)

    txns = _dispenses(db, item.id)
    assert {(t.work_order_number, t.quantity) for t in txns} == {
        (n1, Decimal(10)),
        (n2, Decimal(6)),  # 5 + 1 overflow on the last slot
    }
    assert all(t.work_order_id is not None for t in txns)
    db.refresh(item)
    assert item.quantity == Decimal(84)
    assert _stage_item(db, s1.id, item.id).loaded_quantity == Decimal(10)
    assert _stage_item(db, s2.id, item.id).loaded_quantity == Decimal(6)


def test_load_overdraft_refused_leaves_db_clean(db):
    item = _seed_item(db, 5)
    stage, *_ = _seed_loading_stage(db, item)
    with pytest.raises(NegativeQuantityError):
        load_item(db, stage.id, item_id=item.id, quantity=Decimal(16), user_id=None)
    assert _dispenses(db, item.id) == []
    db.refresh(item)
    assert item.quantity == Decimal(5)


def test_load_refused_when_not_loading(db):
    item = _seed_item(db, 100)
    stage = create_stage(db, community="Scholars", building_name=_building(), created_by_id=None)
    s1 = add_work_order_to_stage(db, stage.id, work_order_number=f"WO-{uuid.uuid4().hex[:5]}", created_by_id=None)
    add_item(db, stage.id, s1.id, item_id=item.id, planned_quantity=Decimal(10))
    with pytest.raises(StageStateError):
        load_item(db, stage.id, item_id=item.id, quantity=Decimal(1), user_id=None)


def test_load_item_not_planned(db):
    item = _seed_item(db, 100)
    other = _seed_item(db, 100)
    stage, *_ = _seed_loading_stage(db, item)
    with pytest.raises(StageItemNotFoundError):
        load_item(db, stage.id, item_id=other.id, quantity=Decimal(1), user_id=None)


# --- return --------------------------------------------------------------

def test_return_adds_stock_without_transaction(db):
    item = _seed_item(db, 100)
    stage, s1, s2, *_ = _seed_loading_stage(db, item)
    load_item(db, stage.id, item_id=item.id, quantity=Decimal(16), user_id=None)  # -> 84
    before = len(_dispenses(db, item.id))

    return_item(db, stage.id, item_id=item.id, quantity=Decimal(4))

    db.refresh(item)
    assert item.quantity == Decimal(88)
    assert len(_dispenses(db, item.id)) == before
    assert _stage_item(db, s2.id, item.id).returned_quantity == Decimal(4)
    assert _stage_item(db, s1.id, item.id).returned_quantity == Decimal(0)


def test_load_appears_on_each_work_order(db):
    item = _seed_item(db, 100)
    stage, s1, s2, n1, n2 = _seed_loading_stage(db, item)  # planned 10 + 5

    load_item(db, stage.id, item_id=item.id, quantity=Decimal(16), user_id=None)

    # Each slot's work order shows the units loaded against it.
    assert _wo_line(db, s1.work_order_id, item.id).quantity == Decimal(10)
    assert _wo_line(db, s2.work_order_id, item.id).quantity == Decimal(6)


def test_return_walks_back_work_order_line(db):
    item = _seed_item(db, 100)
    stage, s1, s2, *_ = _seed_loading_stage(db, item)
    load_item(db, stage.id, item_id=item.id, quantity=Decimal(16), user_id=None)  # s1=10, s2=6

    # Returns reverse-fill last-loaded first, so 4 comes off slot 2's work order.
    return_item(db, stage.id, item_id=item.id, quantity=Decimal(4))

    assert _wo_line(db, s1.work_order_id, item.id).quantity == Decimal(10)
    assert _wo_line(db, s2.work_order_id, item.id).quantity == Decimal(2)  # 6 - 4


def test_return_exceeds_loaded_refused(db):
    item = _seed_item(db, 100)
    stage, *_ = _seed_loading_stage(db, item)
    load_item(db, stage.id, item_id=item.id, quantity=Decimal(10), user_id=None)
    with pytest.raises(ReturnExceedsLoadedError):
        return_item(db, stage.id, item_id=item.id, quantity=Decimal(11))


# --- merged rollup -------------------------------------------------------

def test_merged_rollup_reflects_overflow(db):
    item = _seed_item(db, 100)
    stage, *_ = _seed_loading_stage(db, item)  # planned 15
    load_item(db, stage.id, item_id=item.id, quantity=Decimal(16), user_id=None)

    merged = _merged_items(get_stage(db, stage.id))
    assert len(merged) == 1
    m = merged[0]
    assert m.planned_total == Decimal(15)
    assert m.loaded_total == Decimal(16)
    assert m.overflow == Decimal(1)
    assert m.net_consumed == Decimal(16)
    assert m.remaining_to_load == Decimal(0)


# --- add work order: enforce-match + assignment --------------------------

def test_add_work_order_records_location_and_assignee(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    building = _building()
    stage = create_stage(db, community="Scholars", building_name=building, created_by_id=sup.id)
    slot = add_work_order_to_stage(
        db, stage.id, work_order_number="WO-ASSIGN", unit_number="1101",
        assigned_to_id=tech.id, created_by_id=sup.id,
    )
    w = db.get(WorkOrder, slot.work_order_id)
    assert w.community == "Scholars"
    assert w.building_number == building
    assert w.unit_number == "1101"
    assert w.assigned_to_id == tech.id


def test_add_work_order_enforces_community_building_match(db):
    sup = _seed_user(db, "supervisor")
    # A work order already filed under a different building.
    wo_service.get_or_create_work_order(
        db, number="WO-ELSEWHERE", community="Centennial", building_number="9",
        created_by_id=sup.id,
    )
    stage = create_stage(db, community="Scholars", building_name="19", created_by_id=sup.id)
    with pytest.raises(WorkOrderStateError):
        add_work_order_to_stage(db, stage.id, work_order_number="WO-ELSEWHERE", created_by_id=sup.id)


# --- reuse (Stage again) -------------------------------------------------

def _complete(db, item):
    stage, *_ = _seed_loading_stage(db, item)
    update_stage(db, stage.id, status="completed")
    return stage


def test_reuse_makes_empty_stage_for_same_building(db):
    item = _seed_item(db, 100)
    src = _complete(db, item)
    fresh = reuse_stage(db, src.id, created_by_id=None)
    assert fresh.id != src.id
    assert fresh.status == "planning"
    assert fresh.community == src.community
    assert fresh.building_name == src.building_name
    assert get_stage(db, fresh.id).work_order_slots == []


def test_reuse_requires_completed_source(db):
    item = _seed_item(db, 100)
    stage, *_ = _seed_loading_stage(db, item)  # loading
    with pytest.raises(StageStateError):
        reuse_stage(db, stage.id, created_by_id=None)


def test_reuse_blocked_when_building_already_active(db):
    item = _seed_item(db, 100)
    src = _complete(db, item)
    reuse_stage(db, src.id, created_by_id=None)
    with pytest.raises(DuplicateBuildingStageError):
        reuse_stage(db, src.id, created_by_id=None)


# --- list scoping --------------------------------------------------------

def test_list_stages_scoped_for_supervisor(db):
    sup_a = _seed_user(db, "supervisor")
    sup_b = _seed_user(db, "supervisor")
    admin = _seed_user(db, "admin")
    a = create_stage(db, community="Scholars", building_name=_building(), created_by_id=sup_a.id)
    b = create_stage(db, community="Scholars", building_name=_building(), created_by_id=sup_b.id)

    a_ids = {s.id for s in list_stages(db, user=sup_a)}
    assert a.id in a_ids and b.id not in a_ids
    admin_ids = {s.id for s in list_stages(db, user=admin)}
    assert a.id in admin_ids and b.id in admin_ids
