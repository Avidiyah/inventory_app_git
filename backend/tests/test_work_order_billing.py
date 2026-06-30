"""Phase 1 of work-order billing: the line is the billing unit.

A work-order material line (`work_order_items.quantity`) is the authoritative
"materials used" total, and it is what gets charged (quantity * current price).
Individual work-order-linked transaction rows are therefore a pure inventory
record in History -- their per-row charge is suppressed so the customer is not
double-billed and a line edit's signed stock-correction `adjust` no longer bills
as a nonsensical negative. Ad-hoc (non-work-order) transactions still carry a
per-row price. Skip if no DB.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from decimal import Decimal

import pytest

from app.domain.errors import BillingQuantityError
from app.models import Item, Transaction, User
from app.routers.work_orders import _detail
from app.services import auth
from app.services import work_orders as wos
from app.services.history import list_history
from app.services.transactions import apply_transaction


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


def _rows_for(db, item_id):
    page = list_history(
        db, item_id=item_id, user_id=None, page=1, page_size=50, include_price=True
    )
    return page.items


def test_work_order_dispense_not_billed_per_row(db):
    sup = _seed_user(db, "supervisor")
    item = _seed_item(db, 100, price="3.27")
    w = _wo(db, sup)

    apply_transaction(
        db, item_id=item.id, transaction_type="dispense", quantity=Decimal(2),
        user_id=sup.id, work_order_number=w.number, work_order_id=w.id,
    )

    row = _rows_for(db, item.id)[0]
    # Inventory-only in History: the charge lives on the work-order line instead.
    assert row.item_price is None
    assert row.billable_quantity is None


def test_non_work_order_dispense_still_billed(db):
    sup = _seed_user(db, "supervisor")
    item = _seed_item(db, 100, price="3.27")

    apply_transaction(
        db, item_id=item.id, transaction_type="dispense", quantity=Decimal(2),
        user_id=sup.id, work_order_number=None, work_order_id=None,
    )

    row = _rows_for(db, item.id)[0]
    assert row.item_price == Decimal("3.27")  # ad-hoc rows keep their charge


def test_line_edit_adjustment_not_billed_negative(db):
    # The reported bug: editing a line 2 -> 8 writes a signed -6 stock adjust.
    # Stock must still correct, but History must NOT bill that -6 as a credit.
    sup = _seed_user(db, "supervisor")
    item = _seed_item(db, 100, price="3.27")
    w = _wo(db, sup)

    line = wos.add_work_order_item(db, w.id, user=sup, item_id=item.id, quantity=Decimal(2))
    wos.update_work_order_item(db, w.id, line.id, user=sup, quantity=Decimal(8))

    db.refresh(line)
    assert line.quantity == Decimal(8)  # line = materials used
    db.refresh(item)
    assert item.quantity == Decimal(92)  # 8 consumed from 100, stock correct

    # No work-order row carries a per-row charge -- including the -6 correction.
    rows = _rows_for(db, item.id)
    assert rows, "expected history rows"
    assert all(r.item_price is None for r in rows)
    adjust = next(r for r in rows if r.transaction_type == "adjust")
    assert adjust.quantity == Decimal(-6)  # stock delta retained for audit
    assert adjust.item_price is None  # but never billed


# --- Phase 2: line-level billing override + work-order total -------------

def _line_in(detail, item_id):
    return next(li for li in detail.items if li.item_id == item_id)


def test_line_billing_override_drives_charge_and_total(db):
    sup = _seed_user(db, "supervisor")
    item = _seed_item(db, 100, price="3.00")
    w = _wo(db, sup)
    line = wos.add_work_order_item(db, w.id, user=sup, item_id=item.id, quantity=Decimal(8))

    # Bill only 5 of the 8 consumed.
    wos.set_work_order_item_billable(db, w.id, line.id, user=sup, billable_quantity=Decimal(5))

    detail = wos.get_work_order(db, w.id, user=sup)
    admin_view = _detail(detail, include_price=True)
    li = _line_in(admin_view, item.id)
    assert li.quantity == Decimal(8)  # still 8 consumed (stock unchanged)
    assert li.billable_quantity == Decimal(5)
    assert admin_view.materials_total == Decimal(15)  # 5 * 3.00


def test_line_billing_zero_not_charged(db):
    sup = _seed_user(db, "supervisor")
    item = _seed_item(db, 100, price="3.00")
    w = _wo(db, sup)
    line = wos.add_work_order_item(db, w.id, user=sup, item_id=item.id, quantity=Decimal(4))
    wos.set_work_order_item_billable(db, w.id, line.id, user=sup, billable_quantity=Decimal(0))

    admin_view = _detail(wos.get_work_order(db, w.id, user=sup), include_price=True)
    assert admin_view.materials_total == Decimal(0)


def test_line_billing_redacted_below_admin(db):
    sup = _seed_user(db, "supervisor")
    item = _seed_item(db, 100, price="3.00")
    w = _wo(db, sup)
    line = wos.add_work_order_item(db, w.id, user=sup, item_id=item.id, quantity=Decimal(4))
    wos.set_work_order_item_billable(db, w.id, line.id, user=sup, billable_quantity=Decimal(1))

    detail = wos.get_work_order(db, w.id, user=sup)
    redacted = _detail(detail, include_price=False)
    li = _line_in(redacted, item.id)
    assert li.unit_price is None
    assert li.billable_quantity is None
    assert redacted.materials_total is None


def test_override_cleared_when_quantity_drops_below_it(db):
    sup = _seed_user(db, "supervisor")
    item = _seed_item(db, 100, price="3.00")
    w = _wo(db, sup)
    line = wos.add_work_order_item(db, w.id, user=sup, item_id=item.id, quantity=Decimal(8))
    wos.set_work_order_item_billable(db, w.id, line.id, user=sup, billable_quantity=Decimal(6))

    # Lower the line below the override -> the stale override is cleared.
    wos.update_work_order_item(db, w.id, line.id, user=sup, quantity=Decimal(4))
    db.refresh(line)
    assert line.quantity == Decimal(4)
    assert line.billable_quantity is None  # reverted to full

    # Still-valid override survives a quantity change that stays above it.
    wos.set_work_order_item_billable(db, w.id, line.id, user=sup, billable_quantity=Decimal(2))
    wos.update_work_order_item(db, w.id, line.id, user=sup, quantity=Decimal(3))
    db.refresh(line)
    assert line.billable_quantity == Decimal(2)


def test_override_above_quantity_rejected(db):
    sup = _seed_user(db, "supervisor")
    item = _seed_item(db, 100, price="3.00")
    w = _wo(db, sup)
    line = wos.add_work_order_item(db, w.id, user=sup, item_id=item.id, quantity=Decimal(4))
    with pytest.raises(BillingQuantityError):
        wos.set_work_order_item_billable(db, w.id, line.id, user=sup, billable_quantity=Decimal(5))
