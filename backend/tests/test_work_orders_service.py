"""Database integration tests for the standalone work-order service.

Exercises find-or-create-by-number (case-insensitive, fill-blanks,
restore-on-archived), dispense vs retroactive logging, edit auto-correction,
delete reversal, the stock-neutral void, archive, and role scoping. Skip if no
DB.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.errors import (
    InvalidAssigneeError,
    ItemNotFoundError,
    NegativeQuantityError,
    WorkOrderNotFoundError,
    WorkOrderStateError,
)
from app.models import Item, Transaction, User
from app.services import auth
from app.services import work_orders as wos
from app.services.history import list_history
from app.services.transactions import void_transaction


# --- seed helpers --------------------------------------------------------

def _seed_item(db, qty=100, price="2.50"):
    item = Item(
        barcode=f"BC-{uuid.uuid4().hex[:10]}",
        name="Spray Paint",
        quantity=Decimal(qty),
        location="Bay 1",
        price=Decimal(price),
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


def _wo(db, *, created_by, assigned_to=None, number=None):
    return wos.get_or_create_work_order(
        db,
        number=number or f"WO-{uuid.uuid4().hex[:8]}",
        created_by_id=created_by.id,
        assigned_to_id=assigned_to.id if assigned_to else None,
    )


def _txn(db, txn_id):
    return db.query(Transaction).filter(Transaction.id == txn_id).one()


# --- find-or-create ------------------------------------------------------

def test_create_is_in_progress_with_number_identity(db):
    sup = _seed_user(db, "supervisor")
    w = wos.create_work_order(db, user=sup, number="WO-100", community="Scholars")
    assert w.status == "in_progress"
    assert w.entry_mode == "dispense"
    assert w.community == "Scholars"
    assert w.created_by_id == sup.id


def test_find_or_create_case_insensitive_and_fill_blanks(db):
    sup = _seed_user(db, "supervisor")
    a = wos.get_or_create_work_order(db, number=f"WO-{uuid.uuid4().hex[:6]}", created_by_id=sup.id)
    same = a.number.upper() + " "
    b = wos.get_or_create_work_order(db, number=f"  {same.lower()} ", community="Scholars", created_by_id=sup.id)
    assert b.id == a.id  # same normalized number
    assert b.community == "Scholars"  # blank filled
    # a later reference does NOT overwrite a set attribute
    c = wos.get_or_create_work_order(db, number=a.number, community="Centennial", created_by_id=sup.id)
    assert c.community == "Scholars"


def test_archived_number_is_restored_on_reference(db):
    sup = _seed_user(db, "supervisor")
    a = _wo(db, created_by=sup)
    wos.archive_work_order(db, a.id, user=sup)
    b = wos.get_or_create_work_order(db, number=a.number.lower(), created_by_id=sup.id)
    assert b.id == a.id
    assert b.archived_at is None


def test_assignee_must_be_technician(db):
    sup = _seed_user(db, "supervisor")
    other = _seed_user(db, "supervisor")
    with pytest.raises(InvalidAssigneeError):
        wos.get_or_create_work_order(
            db, number="WO-NT", assigned_to_id=other.id, created_by_id=sup.id
        )


# --- dispense mode (moves stock) -----------------------------------------

def test_dispense_add_moves_stock_and_writes_history_row(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100, price="3.00")
    w = _wo(db, created_by=sup, assigned_to=tech)  # default dispense

    line = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(4))

    db.refresh(item)
    assert item.quantity == Decimal(96)
    txn = _txn(db, line.transaction_id)
    assert txn.transaction_type == "dispense"
    assert txn.affects_stock is True
    assert txn.work_order_id == w.id
    assert txn.work_order_number == w.number
    assert txn.unit_price == Decimal("3.00")


def test_dispense_overdraft_refused(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 2)
    w = _wo(db, created_by=sup, assigned_to=tech)
    with pytest.raises(NegativeQuantityError):
        wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(5))
    db.refresh(item)
    assert item.quantity == Decimal(2)


def test_dispense_edit_auto_corrects_stock(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100)
    w = _wo(db, created_by=sup, assigned_to=tech)
    line = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(4))

    wos.update_work_order_item(db, w.id, line.id, user=tech, quantity=Decimal(10))
    db.refresh(item)
    assert item.quantity == Decimal(90)
    assert _txn(db, line.transaction_id).quantity == Decimal(10)

    wos.update_work_order_item(db, w.id, line.id, user=tech, quantity=Decimal(1))
    db.refresh(item)
    assert item.quantity == Decimal(99)


def test_dispense_delete_returns_stock_and_voids_txn(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100)
    w = _wo(db, created_by=sup, assigned_to=tech)
    line = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(4))
    txn_id = line.transaction_id

    wos.delete_work_order_item(db, w.id, line.id, user=tech)
    db.refresh(item)
    assert item.quantity == Decimal(100)
    assert _txn(db, txn_id).voided_at is not None


def test_readd_same_item_replaces_quantity(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100)
    w = _wo(db, created_by=sup, assigned_to=tech)
    first = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(4))
    second = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(7))
    assert second.id == first.id
    assert second.quantity == Decimal(7)
    db.refresh(item)
    assert item.quantity == Decimal(93)


# --- retroactive mode (stock-neutral, still in History) ------------------

def _make_retroactive(db, w, actor):
    wos.update_work_order(db, w.id, user=actor, fields={"entry_mode": "retroactive"})


def test_retroactive_add_does_not_move_stock_but_shows_in_history(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100, price="5.00")
    w = _wo(db, created_by=sup, assigned_to=tech)
    _make_retroactive(db, w, sup)

    line = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(4))
    db.refresh(item)
    assert item.quantity == Decimal(100)
    txn = _txn(db, line.transaction_id)
    assert txn.transaction_type == "dispense"
    assert txn.affects_stock is False

    page = list_history(
        db, item_id=item.id, user_id=None, work_order_number=w.number,
        page=1, page_size=10, include_price=True,
    )
    assert any(r.transaction_type == "dispense" and r.quantity == Decimal(4) for r in page.items)


def test_void_of_retroactive_txn_does_not_move_stock(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100)
    w = _wo(db, created_by=sup, assigned_to=tech)
    _make_retroactive(db, w, sup)
    line = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(4))

    void_transaction(db, transaction_id=line.transaction_id, user_id=sup.id)
    db.refresh(item)
    assert item.quantity == Decimal(100)


def test_mode_switch_only_affects_new_lines(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100)
    other = _seed_item(db, 100)
    w = _wo(db, created_by=sup, assigned_to=tech)  # dispense

    disp = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(4))
    _make_retroactive(db, w, sup)
    retro = wos.add_work_order_item(db, w.id, user=tech, item_id=other.id, quantity=Decimal(3))
    assert disp.mode == "dispense"
    assert retro.mode == "retroactive"

    wos.update_work_order_item(db, w.id, disp.id, user=tech, quantity=Decimal(6))
    db.refresh(item)
    assert item.quantity == Decimal(94)
    db.refresh(other)
    assert other.quantity == Decimal(100)


# --- status / completed-stays-editable -----------------------------------

def test_completed_work_order_still_editable(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100)
    w = _wo(db, created_by=sup, assigned_to=tech)

    completed = wos.update_work_order(db, w.id, user=tech, fields={"status": "completed"})
    assert completed.status == "completed"
    assert completed.completed_at is not None

    line = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(2))
    assert line.quantity == Decimal(2)


def test_set_invalid_status_rejected(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)
    with pytest.raises(WorkOrderStateError):
        wos.update_work_order(db, w.id, user=tech, fields={"status": "planning"})


# --- scoping -------------------------------------------------------------

def test_scoping_list_and_access(db):
    sup_a = _seed_user(db, "supervisor")
    sup_b = _seed_user(db, "supervisor")
    tech1 = _seed_user(db, "technician")
    tech2 = _seed_user(db, "technician")
    admin = _seed_user(db, "admin")

    a = _wo(db, created_by=sup_a, assigned_to=tech1)
    b = _wo(db, created_by=sup_b, assigned_to=tech2)

    def ids(user, **kw):
        return {w.id for w in wos.list_work_orders(db, user=user, **kw)}

    assert ids(tech1) == {a.id}
    assert ids(tech2) == {b.id}
    assert ids(sup_a) == {a.id}
    assert {a.id, b.id} <= ids(admin)

    with pytest.raises(WorkOrderNotFoundError):
        wos.get_work_order(db, b.id, user=tech1)
    item = _seed_item(db, 100)
    with pytest.raises(WorkOrderNotFoundError):
        wos.add_work_order_item(db, b.id, user=tech1, item_id=item.id, quantity=Decimal(1))


def test_status_filter_and_search(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    a = _wo(db, created_by=sup, assigned_to=tech)
    b = _wo(db, created_by=sup, assigned_to=tech)
    wos.update_work_order(db, b.id, user=sup, fields={"status": "completed"})

    in_prog = {w.id for w in wos.list_work_orders(db, user=sup, status="in_progress")}
    done = {w.id for w in wos.list_work_orders(db, user=sup, status="completed")}
    assert a.id in in_prog and b.id not in in_prog
    assert b.id in done and a.id not in done

    db.refresh(a)
    frag = a.number[-4:]
    found = {w.id for w in wos.list_work_orders(db, user=sup, search=frag)}
    assert a.id in found


def test_archived_work_order_hidden(db):
    sup = _seed_user(db, "supervisor")
    w = _wo(db, created_by=sup)
    wos.archive_work_order(db, w.id, user=sup)
    assert w.id not in {x.id for x in wos.list_work_orders(db, user=sup)}
    with pytest.raises(WorkOrderNotFoundError):
        wos.get_work_order(db, w.id, user=sup)


def test_archived_item_cannot_be_logged(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)
    item = _seed_item(db, 100)
    item.archived_at = datetime.now(timezone.utc)
    db.flush()
    with pytest.raises(ItemNotFoundError):
        wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(1))
