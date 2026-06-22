"""Database integration tests for mass-staging load + return.

These exercise the real stock-touching paths against Postgres (via the `db`
fixture's rolled-back transaction): `services.mass_staging.load_item` splits a
merged load into per-room dispense transactions under the item row lock, and
`return_item` adds stock back silently (no ledger row). They skip if no DB.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from decimal import Decimal

import pytest

from app.domain.errors import (
    DuplicateBuildingStageError,
    InvalidAssigneeError,
    NegativeQuantityError,
    ReturnExceedsLoadedError,
    StageItemNotFoundError,
    StageStateError,
)
from app.models import Item, MassStageItem, MassStageRoom, Transaction, User
from app.routers.mass_stages import _merged_items
from app.services import auth
from app.services.mass_staging import (
    add_item,
    add_room,
    add_room_to_building,
    assign_room,
    create_stage,
    get_stage,
    list_active_rooms,
    list_stages,
    load_item,
    return_item,
    reuse_stage,
    update_room,
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


def _seed_loading_stage(db, item, planned1=10, planned2=5):
    """A loading-status stage with the item planned in two rooms (WO-1, WO-2)."""
    stage = create_stage(
        db, building_name=f"Tower {uuid.uuid4().hex[:6]}", created_by_id=None
    )
    r1 = add_room(db, stage.id, room_number="101", work_order_number="WO-1")
    r2 = add_room(db, stage.id, room_number="102", work_order_number="WO-2")
    add_item(db, stage.id, r1.id, item_id=item.id, planned_quantity=Decimal(planned1))
    add_item(db, stage.id, r2.id, item_id=item.id, planned_quantity=Decimal(planned2))
    update_stage(db, stage.id, status="loading")
    return stage, r1, r2


def _dispenses(db, item_id):
    return (
        db.query(Transaction)
        .filter(
            Transaction.item_id == item_id,
            Transaction.transaction_type == "dispense",
        )
        .all()
    )


def _stage_item(db, room_id, item_id):
    return (
        db.query(MassStageItem)
        .filter(MassStageItem.room_id == room_id, MassStageItem.item_id == item_id)
        .one()
    )


# --- load ----------------------------------------------------------------

def test_load_splits_across_rooms_with_work_orders(db):
    item = _seed_item(db, 100)
    stage, r1, r2 = _seed_loading_stage(db, item)  # planned 10 + 5

    load_item(db, stage.id, item_id=item.id, quantity=Decimal(16), user_id=None)

    txns = _dispenses(db, item.id)
    # 10 on the first room's WO; 5 + 1 overflow on the last room's WO.
    assert {(t.work_order_number, t.quantity) for t in txns} == {
        ("WO-1", Decimal(10)),
        ("WO-2", Decimal(6)),
    }
    db.refresh(item)
    assert item.quantity == Decimal(84)  # 100 - 16
    assert _stage_item(db, r1.id, item.id).loaded_quantity == Decimal(10)
    assert _stage_item(db, r2.id, item.id).loaded_quantity == Decimal(6)


def test_load_overdraft_refused_leaves_db_clean(db):
    item = _seed_item(db, 5)
    stage, _r1, _r2 = _seed_loading_stage(db, item)

    with pytest.raises(NegativeQuantityError):
        load_item(db, stage.id, item_id=item.id, quantity=Decimal(16), user_id=None)

    assert _dispenses(db, item.id) == []  # nothing written
    db.refresh(item)
    assert item.quantity == Decimal(5)  # unchanged


def test_load_refused_when_not_loading(db):
    item = _seed_item(db, 100)
    stage = create_stage(
        db, building_name=f"Tower {uuid.uuid4().hex[:6]}", created_by_id=None
    )
    r1 = add_room(db, stage.id, room_number="101", work_order_number="WO-1")
    add_item(db, stage.id, r1.id, item_id=item.id, planned_quantity=Decimal(10))
    # still planning

    with pytest.raises(StageStateError):
        load_item(db, stage.id, item_id=item.id, quantity=Decimal(1), user_id=None)


def test_load_item_not_planned(db):
    item = _seed_item(db, 100)
    other = _seed_item(db, 100)
    stage, _r1, _r2 = _seed_loading_stage(db, item)

    with pytest.raises(StageItemNotFoundError):
        load_item(db, stage.id, item_id=other.id, quantity=Decimal(1), user_id=None)


# --- return --------------------------------------------------------------

def test_return_adds_stock_without_transaction(db):
    item = _seed_item(db, 100)
    stage, r1, r2 = _seed_loading_stage(db, item)
    load_item(db, stage.id, item_id=item.id, quantity=Decimal(16), user_id=None)  # -> 84
    before = len(_dispenses(db, item.id))

    return_item(db, stage.id, item_id=item.id, quantity=Decimal(4))

    db.refresh(item)
    assert item.quantity == Decimal(88)  # 84 + 4, silent add
    assert len(_dispenses(db, item.id)) == before  # no new ledger rows
    # reverse-fill: the last-loaded room gives back first.
    assert _stage_item(db, r2.id, item.id).returned_quantity == Decimal(4)
    assert _stage_item(db, r1.id, item.id).returned_quantity == Decimal(0)


def test_return_exceeds_loaded_refused(db):
    item = _seed_item(db, 100)
    stage, _r1, _r2 = _seed_loading_stage(db, item)
    load_item(db, stage.id, item_id=item.id, quantity=Decimal(10), user_id=None)

    with pytest.raises(ReturnExceedsLoadedError):
        return_item(db, stage.id, item_id=item.id, quantity=Decimal(11))


# --- merged rollup -------------------------------------------------------

def test_merged_rollup_reflects_overflow(db):
    item = _seed_item(db, 100)
    stage, _r1, _r2 = _seed_loading_stage(db, item)  # planned 15
    load_item(db, stage.id, item_id=item.id, quantity=Decimal(16), user_id=None)

    merged = _merged_items(get_stage(db, stage.id))
    assert len(merged) == 1
    m = merged[0]
    assert m.planned_total == Decimal(15)
    assert m.loaded_total == Decimal(16)
    assert m.overflow == Decimal(1)
    assert m.net_consumed == Decimal(16)
    assert m.remaining_to_load == Decimal(0)


# --- reuse (Stage again) -------------------------------------------------

def _rooms(db, stage_id):
    return (
        db.query(MassStageRoom)
        .filter(MassStageRoom.stage_id == stage_id)
        .order_by(MassStageRoom.sort_order)
        .all()
    )


def _complete(db, item, qty1=10, qty2=5):
    """A completed stage with two rooms (WO-1/WO-2) and items planned."""
    stage, r1, r2 = _seed_loading_stage(db, item, planned1=qty1, planned2=qty2)
    update_stage(db, stage.id, status="completed")
    return stage


def test_reuse_copies_rooms_clears_work_orders_and_items(db):
    item = _seed_item(db, 100)
    src = _complete(db, item)

    fresh = reuse_stage(db, src.id, created_by_id=None)

    assert fresh.id != src.id
    assert fresh.status == "planning"
    assert fresh.building_name == src.building_name
    fresh_rooms = _rooms(db, fresh.id)
    assert [r.room_number for r in fresh_rooms] == ["101", "102"]  # numbers kept
    assert all(r.work_order_number == "" for r in fresh_rooms)     # WOs cleared
    # No planned items copied.
    assert db.query(MassStageItem).join(
        MassStageRoom, MassStageItem.room_id == MassStageRoom.id
    ).filter(MassStageRoom.stage_id == fresh.id).count() == 0
    # Source is untouched (still the saved record).
    src_after = get_stage(db, src.id)
    assert src_after.status == "completed"


def test_reuse_requires_completed_source(db):
    item = _seed_item(db, 100)
    stage, _r1, _r2 = _seed_loading_stage(db, item)  # status == loading
    with pytest.raises(StageStateError):
        reuse_stage(db, stage.id, created_by_id=None)


def test_reuse_blocked_when_building_already_active(db):
    item = _seed_item(db, 100)
    src = _complete(db, item)
    reuse_stage(db, src.id, created_by_id=None)  # now an active planning stage exists
    with pytest.raises(DuplicateBuildingStageError):
        reuse_stage(db, src.id, created_by_id=None)


def test_reused_stage_cannot_load_until_work_orders_set(db):
    item = _seed_item(db, 100)
    src = _complete(db, item)
    fresh = reuse_stage(db, src.id, created_by_id=None)
    r1, r2 = _rooms(db, fresh.id)
    add_item(db, fresh.id, r1.id, item_id=item.id, planned_quantity=Decimal(3))

    # Work orders are blank -> cannot move to loading.
    with pytest.raises(StageStateError):
        update_stage(db, fresh.id, status="loading")

    # Fill every room's work order -> transition succeeds.
    update_room(db, fresh.id, r1.id, work_order_number="WO-NEW-1")
    update_room(db, fresh.id, r2.id, work_order_number="WO-NEW-2")
    update_stage(db, fresh.id, status="loading")
    assert get_stage(db, fresh.id).status == "loading"


# --- quick-add work order (scan-gate find-or-create) ---------------------

def test_quick_add_new_building_creates_planning_stage_with_room(db):
    building = f"Maple {uuid.uuid4().hex[:6]}"
    stage = add_room_to_building(
        db,
        building_name=building,
        room_number="101",
        work_order_number="WO-Q1",
        created_by_id=None,
    )
    assert stage.building_name == building
    assert stage.status == "planning"
    rooms = _rooms(db, stage.id)
    assert [(r.room_number, r.work_order_number) for r in rooms] == [("101", "WO-Q1")]


def test_quick_add_existing_building_appends_to_same_stage(db):
    building = f"Maple {uuid.uuid4().hex[:6]}"
    first = add_room_to_building(
        db, building_name=building, room_number="101",
        work_order_number="WO-Q1", created_by_id=None,
    )
    second = add_room_to_building(
        db, building_name=building, room_number="102",
        work_order_number="WO-Q2", created_by_id=None,
    )
    # Same stage -- a 2nd room makes the building a Mass Stage card.
    assert second.id == first.id
    rooms = _rooms(db, first.id)
    assert [r.room_number for r in rooms] == ["101", "102"]


def test_quick_add_duplicate_room_rejected(db):
    building = f"Maple {uuid.uuid4().hex[:6]}"
    add_room_to_building(
        db, building_name=building, room_number="101",
        work_order_number="WO-Q1", created_by_id=None,
    )
    with pytest.raises(StageStateError):
        add_room_to_building(
            db, building_name=building, room_number="101",
            work_order_number="WO-DUP", created_by_id=None,
        )


def test_quick_add_into_loading_building_rejected(db):
    item = _seed_item(db, 100)
    stage, _r1, _r2 = _seed_loading_stage(db, item)  # status == loading
    with pytest.raises(StageStateError):
        add_room_to_building(
            db, building_name=stage.building_name, room_number="103",
            work_order_number="WO-Q3", created_by_id=None,
        )


# --- active-rooms (scan-gate card source) --------------------------------

def test_list_active_rooms_excludes_completed_and_blank_wo(db):
    item = _seed_item(db, 100)
    # Active stage with one valid room + one blank-WO room (reused-style).
    active = add_room_to_building(
        db, building_name=f"Active {uuid.uuid4().hex[:6]}", room_number="201",
        work_order_number="WO-A1", created_by_id=None,
    )
    # A blank-WO room (reused-style) on the same active stage must be skipped.
    add_room(db, active.id, room_number="202", work_order_number="")
    # A completed stage's rooms must NOT appear.
    completed = _complete(db, item)

    rows = list_active_rooms(db)
    keys = {(r["building_name"], r["room_number"], r["work_order_number"]) for r in rows}
    assert (active.building_name, "201", "WO-A1") in keys
    # blank-WO room skipped
    assert all(r["work_order_number"].strip() for r in rows)
    # no rooms from the completed stage
    assert all(r["stage_id"] != completed.id for r in rows)


# --- work-order ownership + assignment + visibility ----------------------

def _seed_user(db, role):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def test_quick_add_records_creator_and_assignee(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    stage = add_room_to_building(
        db, building_name=f"Scholars {uuid.uuid4().hex[:6]}", room_number="1121",
        work_order_number="WO-1", created_by_id=sup.id, assigned_to_id=tech.id,
    )
    room = _rooms(db, stage.id)[0]
    assert room.created_by_id == sup.id
    assert room.assigned_to_id == tech.id


def test_assign_to_non_technician_rejected(db):
    sup = _seed_user(db, "supervisor")
    other_sup = _seed_user(db, "supervisor")
    # On quick-add:
    with pytest.raises(InvalidAssigneeError):
        add_room_to_building(
            db, building_name=f"Scholars {uuid.uuid4().hex[:6]}", room_number="1121",
            work_order_number="WO-1", created_by_id=sup.id, assigned_to_id=other_sup.id,
        )


def test_assign_room_sets_and_clears(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    stage = add_room_to_building(
        db, building_name=f"Scholars {uuid.uuid4().hex[:6]}", room_number="1121",
        work_order_number="WO-1", created_by_id=sup.id,
    )
    room = _rooms(db, stage.id)[0]
    assert room.assigned_to_id is None

    assign_room(db, stage.id, room.id, assigned_to_id=tech.id)
    db.refresh(room)
    assert room.assigned_to_id == tech.id

    assign_room(db, stage.id, room.id, assigned_to_id=None)  # unassign
    db.refresh(room)
    assert room.assigned_to_id is None


def test_assign_room_blocked_on_completed_stage(db):
    item = _seed_item(db, 100)
    tech = _seed_user(db, "technician")
    stage = _complete(db, item)
    room = _rooms(db, stage.id)[0]
    with pytest.raises(StageStateError):
        assign_room(db, stage.id, room.id, assigned_to_id=tech.id)


def test_active_rooms_scoped_by_role(db):
    sup_a = _seed_user(db, "supervisor")
    sup_b = _seed_user(db, "supervisor")
    tech1 = _seed_user(db, "technician")
    tech2 = _seed_user(db, "technician")
    admin = _seed_user(db, "admin")

    # sup_a creates two work orders: one assigned to tech1, one unassigned.
    sa = add_room_to_building(
        db, building_name=f"A {uuid.uuid4().hex[:6]}", room_number="101",
        work_order_number="WO-A1", created_by_id=sup_a.id, assigned_to_id=tech1.id,
    )
    add_room(
        db, sa.id, room_number="102", work_order_number="WO-A2",
        created_by_id=sup_a.id,  # unassigned
    )
    # sup_b creates one assigned to tech2.
    add_room_to_building(
        db, building_name=f"B {uuid.uuid4().hex[:6]}", room_number="201",
        work_order_number="WO-B1", created_by_id=sup_b.id, assigned_to_id=tech2.id,
    )

    def wos(user):
        return {r["work_order_number"] for r in list_active_rooms(db, user=user)}

    # Technician: only work orders assigned to them.
    assert wos(tech1) == {"WO-A1"}
    assert wos(tech2) == {"WO-B1"}
    # Supervisor: only work orders they created (assigned or not).
    assert wos(sup_a) == {"WO-A1", "WO-A2"}
    assert wos(sup_b) == {"WO-B1"}
    # Admin: everything.
    assert {"WO-A1", "WO-A2", "WO-B1"} <= wos(admin)


def test_list_stages_scoped_for_supervisor(db):
    sup_a = _seed_user(db, "supervisor")
    sup_b = _seed_user(db, "supervisor")
    admin = _seed_user(db, "admin")
    a = create_stage(db, building_name=f"A {uuid.uuid4().hex[:6]}", created_by_id=sup_a.id)
    b = create_stage(db, building_name=f"B {uuid.uuid4().hex[:6]}", created_by_id=sup_b.id)

    a_ids = {s.id for s in list_stages(db, user=sup_a)}
    assert a.id in a_ids and b.id not in a_ids  # supervisor sees only their own
    admin_ids = {s.id for s in list_stages(db, user=admin)}
    assert a.id in admin_ids and b.id in admin_ids  # admin sees all
