"""The work-order materials list stays in sync across every write path.

Regression coverage for the unification: a dispense logged from the Scan/Stock
page / scan-and-go (`services.transactions.apply_transaction`) and a Mass Stage
truck-load now produce the same `WorkOrderItem` line the Work Orders page button
does, scans ACCUMULATE, stock-ins do not, voiding from History walks the line
back, and an orphaned linked dispense self-heals into a line on read. Skip if no
DB.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from decimal import Decimal

from app.models import Item, Transaction, User, WorkOrderItem
from app.services import auth
from app.services import work_orders as wos
from app.services.transactions import apply_transaction, void_transaction


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


def _wo(db, sup):
    return wos.get_or_create_work_order(
        db, number=f"WO-{uuid.uuid4().hex[:8]}", created_by_id=sup.id
    )


def _line(db, work_order_id, item_id):
    return (
        db.query(WorkOrderItem)
        .filter(
            WorkOrderItem.work_order_id == work_order_id,
            WorkOrderItem.item_id == item_id,
        )
        .first()
    )


# --- Scan/Stock + scan-and-go path (apply_transaction) -------------------

def test_scan_dispense_creates_work_order_line(db):
    sup = _seed_user(db, "supervisor")
    item = _seed_item(db, 100)
    w = _wo(db, sup)

    apply_transaction(
        db,
        item_id=item.id,
        transaction_type="dispense",
        quantity=Decimal(3),
        user_id=sup.id,
        work_order_number=w.number,
        work_order_id=w.id,
    )

    line = _line(db, w.id, item.id)
    assert line is not None
    assert line.quantity == Decimal(3)
    assert line.mode == "dispense"
    db.refresh(item)
    assert item.quantity == Decimal(97)


def test_repeated_scans_accumulate_one_line(db):
    sup = _seed_user(db, "supervisor")
    item = _seed_item(db, 100)
    w = _wo(db, sup)

    for _ in range(3):
        apply_transaction(
            db,
            item_id=item.id,
            transaction_type="dispense",
            quantity=Decimal(2),
            user_id=sup.id,
            work_order_number=w.number,
            work_order_id=w.id,
        )

    line = _line(db, w.id, item.id)
    assert line.quantity == Decimal(6)  # 3 scans x 2
    # One line, three ledger rows.
    n = (
        db.query(Transaction)
        .filter(Transaction.work_order_id == w.id, Transaction.transaction_type == "dispense")
        .count()
    )
    assert n == 3


def test_scan_stock_in_creates_no_line(db):
    sup = _seed_user(db, "supervisor")
    item = _seed_item(db, 100)
    w = _wo(db, sup)

    apply_transaction(
        db,
        item_id=item.id,
        transaction_type="stock",
        quantity=Decimal(5),
        user_id=sup.id,
        work_order_number=w.number,
        work_order_id=w.id,
    )

    assert _line(db, w.id, item.id) is None  # restocking is not "material used"
    db.refresh(item)
    assert item.quantity == Decimal(105)


def test_dispense_without_work_order_creates_no_line(db):
    sup = _seed_user(db, "supervisor")
    item = _seed_item(db, 100)
    apply_transaction(
        db,
        item_id=item.id,
        transaction_type="dispense",
        quantity=Decimal(1),
        user_id=sup.id,
        work_order_number=None,
        work_order_id=None,
    )
    assert db.query(WorkOrderItem).count() == 0


# --- void from History reconciles the line -------------------------------

def test_void_of_scanned_dispense_walks_line_back(db):
    sup = _seed_user(db, "supervisor")
    item = _seed_item(db, 100)
    w = _wo(db, sup)

    a = apply_transaction(
        db, item_id=item.id, transaction_type="dispense", quantity=Decimal(2),
        user_id=sup.id, work_order_number=w.number, work_order_id=w.id,
    )
    apply_transaction(
        db, item_id=item.id, transaction_type="dispense", quantity=Decimal(5),
        user_id=sup.id, work_order_number=w.number, work_order_id=w.id,
    )
    assert _line(db, w.id, item.id).quantity == Decimal(7)

    void_transaction(db, transaction_id=a.id, user_id=sup.id)
    assert _line(db, w.id, item.id).quantity == Decimal(5)  # 7 - 2
    db.refresh(item)
    assert item.quantity == Decimal(95)  # stock returned for the void


def test_void_of_edit_adjustment_restores_line(db):
    # Editing a line writes a reconciling `adjust`; voiding that adjust from
    # History must walk the line and stock back to the pre-edit state.
    sup = _seed_user(db, "supervisor")
    item = _seed_item(db, 100)
    w = _wo(db, sup)
    line = wos.add_work_order_item(db, w.id, user=sup, item_id=item.id, quantity=Decimal(4))
    wos.update_work_order_item(db, w.id, line.id, user=sup, quantity=Decimal(10))
    assert _line(db, w.id, item.id).quantity == Decimal(10)
    db.refresh(item)
    assert item.quantity == Decimal(90)

    adj = (
        db.query(Transaction)
        .filter(Transaction.work_order_id == w.id, Transaction.transaction_type == "adjust")
        .one()
    )
    void_transaction(db, transaction_id=adj.id, user_id=sup.id)
    assert _line(db, w.id, item.id).quantity == Decimal(4)  # back to pre-edit
    db.refresh(item)
    assert item.quantity == Decimal(96)  # stock restored too


def test_void_of_last_dispense_drops_line(db):
    sup = _seed_user(db, "supervisor")
    item = _seed_item(db, 100)
    w = _wo(db, sup)
    only = apply_transaction(
        db, item_id=item.id, transaction_type="dispense", quantity=Decimal(2),
        user_id=sup.id, work_order_number=w.number, work_order_id=w.id,
    )
    void_transaction(db, transaction_id=only.id, user_id=sup.id)
    assert _line(db, w.id, item.id) is None


# --- reader fold-in (self-heal of an orphan) -----------------------------

def test_get_work_order_self_heals_orphan_line(db):
    sup = _seed_user(db, "supervisor")
    item = _seed_item(db, 100)
    w = _wo(db, sup)

    apply_transaction(
        db, item_id=item.id, transaction_type="dispense", quantity=Decimal(4),
        user_id=sup.id, work_order_number=w.number, work_order_id=w.id,
    )
    # Simulate a straggler: a linked dispense whose line was never written.
    db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == w.id).delete()
    db.flush()
    assert _line(db, w.id, item.id) is None

    detail = wos.get_work_order(db, w.id, user=sup)
    assert any(li.item_id == item.id and li.quantity == Decimal(4) for li in detail.items)
