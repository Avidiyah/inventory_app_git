"""Schema-level tests for the Takeoff tables (spec
docs/superpowers/specs/2026-11-25-takeoff-design.md, "Data")."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Item, TakeoffPurchase, WorkOrder, WorkOrderTakeoffLine


def _order(db) -> WorkOrder:
    order = WorkOrder(number=f"WO-{uuid.uuid4().hex[:8]}")
    db.add(order)
    db.flush()
    return order


def _item(db) -> Item:
    item = Item(
        barcode=f"B-{uuid.uuid4().hex[:10]}", name="Toilet", location="A1", quantity=0
    )
    db.add(item)
    db.flush()
    return item


def _line(order, item, quantity=1):
    return WorkOrderTakeoffLine(
        work_order_id=order.id, item_id=item.id, quantity=Decimal(quantity)
    )


def test_line_round_trips_with_relationships(db):
    order, item = _order(db), _item(db)
    db.add(_line(order, item, "2.5"))
    db.flush()
    db.expire_all()
    assert [(l.item.name, l.quantity) for l in order.takeoff_lines] == [
        ("Toilet", Decimal("2.5"))
    ]


def test_duplicate_order_item_line_rejected(db):
    order, item = _order(db), _item(db)
    db.add(_line(order, item))
    db.flush()
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(_line(order, item, 2))
            db.flush()


def test_nonpositive_quantity_rejected(db):
    order, item = _order(db), _item(db)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(_line(order, item, 0))
            db.flush()


def test_deleting_work_order_removes_its_lines(db):
    order, item = _order(db), _item(db)
    db.add(_line(order, item))
    db.flush()
    db.delete(order)
    db.flush()
    assert db.query(WorkOrderTakeoffLine).filter_by(item_id=item.id).count() == 0


def _purchase(item, key="wmr", quantity=5):
    return TakeoffPurchase(
        item_id=item.id,
        service_type_key=key,
        service_type_label="WMR",
        quantity_on_the_way=Decimal(quantity),
    )


def test_duplicate_purchase_pair_rejected(db):
    item = _item(db)
    db.add(_purchase(item))
    db.flush()
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(_purchase(item))
            db.flush()


def test_purchase_same_item_other_type_allowed_but_zero_rejected(db):
    item = _item(db)
    db.add_all([_purchase(item, "wmr"), _purchase(item, "plumbing")])
    db.flush()
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(_purchase(item, "other", 0))
            db.flush()
