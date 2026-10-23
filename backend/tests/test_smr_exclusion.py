"""SMR orders (spec 2026-10-23 D1) live only on the SMR page: every live
surface excludes `smr_imported_at IS NOT NULL`, while the editor and the
NetFacilities enrichment candidate query still see them."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models import User, WorkOrder
from app.services import auth, hub
from app.services import netfacilities
from app.services import work_order_report
from app.services import work_orders as wos
from app.domain import work_orders as wo


def _owner(db):
    user = User(username=f"o-{uuid.uuid4().hex[:8]}", password_hash=auth.hash_password("x"), role="owner")
    db.add(user)
    db.flush()
    return user


def _smr_order(db, owner, *, archived=False, service_type="SMR27 - Belfor"):
    order = wos.get_or_create_work_order(
        db, number=f"SMR-{uuid.uuid4().hex[:8]}", created_by_id=owner.id,
        service_type=service_type,
    )
    order.smr_imported_at = datetime.now(timezone.utc)
    order.description = wo.work_order_task_fallback(order.number)
    if archived:
        order.archived_at = datetime.now(timezone.utc)
    db.flush()
    return order


def test_smr_row_absent_from_list_and_filter_options(db):
    owner = _owner(db)
    order = _smr_order(db, owner, service_type=f"SMR-{uuid.uuid4().hex[:6]}")
    listed = wos.list_work_orders(db, user=owner, search=order.number)
    assert order.number not in [card.number for card in listed]
    options = wos.get_work_order_filter_options(db, user=owner)
    assert order.service_type not in options["service_types"]


def test_smr_row_absent_from_hub_counts(db):
    owner = _owner(db)
    before = hub._pipeline_counts(db)
    _smr_order(db, owner)
    assert hub._pipeline_counts(db) == before


def test_smr_row_absent_from_weekly_report(db):
    owner = _owner(db)
    order = _smr_order(db, owner, archived=True)
    now = datetime.now(timezone.utc)
    rows = work_order_report._closed_rows(db, start=now - timedelta(days=1), end=now + timedelta(days=1))
    assert order.number not in [row.number for row in rows]


def test_smr_row_still_enrichment_candidate(db):
    owner = _owner(db)
    order = _smr_order(db, owner)
    candidates = netfacilities._load_candidates(lambda: db)
    assert order.number in [c.number for c in candidates]


def test_editor_still_loads_smr_row(db):
    owner = _owner(db)
    order = _smr_order(db, owner)
    assert wos.get_work_order(db, order.id, user=owner).id == order.id
