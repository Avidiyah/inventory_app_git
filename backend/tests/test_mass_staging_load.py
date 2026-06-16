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
    NegativeQuantityError,
    ReturnExceedsLoadedError,
    StageItemNotFoundError,
    StageStateError,
)
from app.models import Item, MassStageItem, MassStageRoom, Transaction
from app.routers.mass_stages import _merged_items
from app.services.mass_staging import (
    add_item,
    add_room,
    create_stage,
    get_stage,
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
