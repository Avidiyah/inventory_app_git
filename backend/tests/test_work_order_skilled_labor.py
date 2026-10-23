"""Anonymous Skilled Technician labor (spec 2026-10-23): a null-technician
labor entry allowed only on SMR orders by Admin+, billed at the labor rate
with its minutes rounded apart from real technicians, and invisible to the
Hub's per-person billing."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain import work_orders as wo
from app.domain.errors import InvalidAssigneeError, RoleManagementError
from app.models import User
from app.routers.work_orders import _detail, _labor_detail
from app.services import auth, hub
from app.services import work_orders as wos


def _user(db, role):
    user = User(
        username=f"u-{uuid.uuid4().hex[:8]}", first_name="Pat", last_name=role.title(),
        password_hash=auth.hash_password("x"), role=role,
    )
    db.add(user)
    db.flush()
    return user


def _order(db, user, *, smr=True):
    order = wos.get_or_create_work_order(db, number=f"WO-{uuid.uuid4().hex[:8]}", created_by_id=user.id)
    if smr:
        order.smr_imported_at = datetime.now(timezone.utc)
        db.flush()
    return order


def test_skilled_labor_added_on_smr_order_by_admin(db):
    admin = _user(db, "admin")
    order = _order(db, admin)
    wos.add_work_order_labor(db, order.id, user=admin, technician_id=admin.id, minutes=20)
    entry = wos.add_work_order_labor(db, order.id, user=admin, technician_id=None, minutes=10)
    assert entry.technician_id is None
    assert _labor_detail(entry).technician_name == "Skilled Technician"

    detail = _detail(wos.get_work_order(db, order.id, user=admin), include_price=True)
    assert detail.smr is True
    assert (detail.labor_minutes, detail.skilled_labor_minutes) == (20, 10)
    assert (detail.labor_billed_minutes, detail.skilled_labor_billed_minutes) == (30, 30)
    assert detail.labor_total == wo.labor_charge(30) * 2


def test_skilled_labor_rejected_off_smr_and_below_admin(db):
    admin = _user(db, "admin")
    plain = _order(db, admin, smr=False)
    with pytest.raises(InvalidAssigneeError):
        wos.add_work_order_labor(db, plain.id, user=admin, technician_id=None, minutes=10)
    sup = _user(db, "supervisor")
    smr_order = _order(db, sup)
    with pytest.raises(RoleManagementError):
        wos.add_work_order_labor(db, smr_order.id, user=sup, technician_id=None, minutes=10)
    assert wos.get_work_order(db, smr_order.id, user=sup).labor_entries == []


def test_update_and_delete_skilled_entry(db):
    admin = _user(db, "admin")
    order = _order(db, admin)
    entry = wos.add_work_order_labor(db, order.id, user=admin, technician_id=None, minutes=10)
    assert wos.update_work_order_labor(db, order.id, entry.id, user=admin, minutes=45).minutes == 45
    sup = _user(db, "supervisor")
    with pytest.raises(RoleManagementError):
        wos.update_work_order_labor(db, order.id, entry.id, user=sup, minutes=5)
    wos.delete_work_order_labor(db, order.id, entry.id, user=admin)
    assert wos.get_work_order(db, order.id, user=admin).labor_entries == []


def test_hub_billing_ignores_skilled_minutes(db):
    admin = _user(db, "admin")
    order = _order(db, admin)
    wos.add_work_order_labor(db, order.id, user=admin, technician_id=None, minutes=90)
    _, labor_total = hub._materials_and_labor([wos.get_work_order(db, order.id, user=admin)])
    assert labor_total == Decimal(0)


def test_work_order_totals_split_rounding(db):
    admin = _user(db, "admin")
    order = _order(db, admin)
    wos.add_work_order_labor(db, order.id, user=admin, technician_id=admin.id, minutes=20)
    wos.add_work_order_labor(db, order.id, user=admin, technician_id=None, minutes=10)
    totals = wos.work_order_totals(wos.get_work_order(db, order.id, user=admin))
    assert totals.labor_minutes == 30
    assert totals.labor_total == wo.labor_charge(30) * 2
