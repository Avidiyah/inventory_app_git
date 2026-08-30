"""Service, CSV, and window tests for the Admin daily report.

Spec: docs/superpowers/specs/2026-08-30-work-order-daily-report-design.md

The `db` fixture rolls back, but it runs against a *developer* Postgres that
may already hold real work orders. Count assertions are therefore scoped to
rows the test created, or to a window no pre-existing row can fall into.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.domain import work_orders as wo
from app.models import Item, User, WorkOrder, WorkOrderItem, WorkOrderLabor
from app.services import work_orders as work_orders_service


def _user(db, role="technician"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:8]}",
        first_name="Test",
        last_name=role.title(),
        password_hash="x",
        role=role,
    )
    db.add(user)
    db.commit()
    return user


def _work_order(db, **kwargs):
    """A work order with a unique number. Every column the report reads is
    settable; the defaults are a plain live row created 'now'."""
    fields = {
        "number": f"WO-{uuid.uuid4().hex[:10]}",
        "status": wo.STATUS_CREATED,
        "created_at": datetime.now(timezone.utc),
        "community": "Cedar Ridge",
        "location": "Bldg 3",
        "service_type": "Plumbing",
        "entry_mode": "dispense",
    }
    fields.update(kwargs)
    record = WorkOrder(id=uuid.uuid4(), **fields)
    db.add(record)
    db.commit()
    return record


def _priced_item(db, price):
    item = Item(
        id=uuid.uuid4(),
        barcode=f"bc-{uuid.uuid4().hex[:12]}",
        name=f"part-{uuid.uuid4().hex[:8]}",
        quantity=Decimal("100"),
        location="A1",
        price=price,
    )
    db.add(item)
    db.commit()
    return item


def _add_material(db, order, item, quantity):
    db.add(
        WorkOrderItem(
            id=uuid.uuid4(),
            work_order_id=order.id,
            item_id=item.id,
            quantity=Decimal(quantity),
            mode="dispense",
        )
    )
    db.commit()


def _add_labor(db, order, minutes, technician=None):
    technician = technician or _user(db)
    db.add(
        WorkOrderLabor(
            id=uuid.uuid4(),
            work_order_id=order.id,
            technician_id=technician.id,
            minutes=minutes,
        )
    )
    db.commit()


def test_work_order_totals_matches_the_export_rows_money(db):
    item = _priced_item(db, Decimal("10.00"))
    order = _work_order(db)
    _add_material(db, order, item, 3)
    _add_labor(db, order, 90)
    db.refresh(order)

    totals = work_orders_service.work_order_totals(order)
    row = work_orders_service.export_row(order)

    headers = list(wo.EXPORT_HEADERS)
    assert row[headers.index("MATERIALS TOTAL")] == f"{totals.materials_total:.2f}"
    assert row[headers.index("LABOR MINUTES")] == totals.labor_minutes
    assert row[headers.index("LABOR TOTAL")] == f"{totals.labor_total:.2f}"
    assert row[headers.index("TOTAL")] == f"{totals.total:.2f}"


def test_totals_sum_materials_and_labor(db):
    item = _priced_item(db, Decimal("10.00"))
    order = _work_order(db)
    _add_material(db, order, item, 2)
    _add_labor(db, order, 60)
    db.refresh(order)

    totals = work_orders_service.work_order_totals(order)

    assert totals.materials_total == Decimal("20.00")
    assert totals.labor_minutes == 60
    assert totals.labor_total == wo.labor_charge(60)
    assert totals.total == totals.materials_total + totals.labor_total
