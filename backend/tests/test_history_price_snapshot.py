"""Database integration tests for transaction history pricing.

`Transaction.unit_price` is captured from `Item.price` when a stock /
dispense row is written, and `services.history.list_history` reports that
frozen snapshot -- editing an item's price does NOT rewrite already-recorded
history. The single exception is a row recorded while the item was free
(snapshot 0): it tracks the live `Item.price`, so giving a previously-free
item a real price flows onto its past rows. A NULL snapshot (legacy/adjust)
also falls back to the live price. These skip if no DB (the `db` fixture).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from decimal import Decimal

from app.models import Item, Transaction
from app.services.history import list_history
from app.services.transactions import apply_transaction


def _seed_item(db, qty, price):
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


def _row_for(db, txn_id, item_id):
    page = list_history(
        db, item_id=item_id, user_id=None, page=1, page_size=50, include_price=True
    )
    return next(r for r in page.items if r.id == txn_id)


def test_dispense_snapshots_price_at_write_time(db):
    item = _seed_item(db, qty=100, price="10.00")
    txn = apply_transaction(
        db,
        item_id=item.id,
        transaction_type="dispense",
        quantity=Decimal("5"),
        user_id=None,
        work_order_number="WO-1",
    )
    assert txn.unit_price == Decimal("10.00")


def test_price_edit_does_not_rewrite_nonzero_history(db):
    item = _seed_item(db, qty=100, price="10.00")
    txn = apply_transaction(
        db,
        item_id=item.id,
        transaction_type="dispense",
        quantity=Decimal("5"),
        user_id=None,
        work_order_number="WO-1",
    )

    # A row recorded at a real (non-zero) price stays frozen at that price no
    # matter how the item is later repriced.
    item.price = Decimal("99.00")
    db.flush()

    row = _row_for(db, txn.id, item.id)
    assert row.item_price == Decimal("10.00")


def test_free_dispense_reflects_new_price(db):
    # The exception: an item dispensed while free ($0) tracks the live price,
    # so giving it a real price later DOES flow onto that past row.
    item = _seed_item(db, qty=100, price="0")
    txn = apply_transaction(
        db,
        item_id=item.id,
        transaction_type="dispense",
        quantity=Decimal("5"),
        user_id=None,
        work_order_number="WO-FREE",
    )
    assert txn.unit_price == Decimal("0")

    item.price = Decimal("15.00")
    db.flush()

    row = _row_for(db, txn.id, item.id)
    assert row.item_price == Decimal("15.00")  # free -> priced reflects


def test_null_snapshot_falls_back_to_live_price(db):
    # A pre-snapshot row (written before the snapshot existed) has NULL
    # unit_price and falls back to the current item price.
    item = _seed_item(db, qty=100, price="7.50")
    legacy = Transaction(
        item_id=item.id,
        user_id=None,
        transaction_type="dispense",
        quantity=Decimal("3"),
        unit_price=None,
        work_order_number="WO-OLD",
    )
    db.add(legacy)
    db.flush()

    row = _row_for(db, legacy.id, item.id)
    assert row.item_price == Decimal("7.50")
