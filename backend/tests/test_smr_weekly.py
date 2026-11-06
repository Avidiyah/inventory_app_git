"""Vendor invoices upload and the weekly hours series (spec
2026-11-06-smr-weekly-hours-chart): replace-by-invoice rerun, role gates,
and one cell's original / added / invoiced / missing arithmetic."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.domain.errors import WorkOrderStateError
from app.main import app
from app.models import SmrLaborLine, SmrVendorInvoice, SmrWorker, User, WorkOrder
from app.services import auth as auth_service
from app.services import work_orders_smr_weekly as weekly

HEADER = "Invoice,Date,Vendor,Worker,Rate,Hours\r\n"


def _user(db, role="owner"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}", first_name="Pat", last_name=role.title(),
                password_hash=auth_service.hash_password("hunter2"), role=role)
    db.add(user)
    db.flush()
    return user


def _csv(*rows):
    return (HEADER + "".join(f"{r}\r\n" for r in rows)).encode()


def _client(db, user):
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    client.cookies.set("session", auth_service.create_session(db, user))
    return client


def _rows(db, invoice):
    return db.query(SmrVendorInvoice).filter(SmrVendorInvoice.invoice == invoice).all()


def test_reupload_replaces_an_invoice_and_other_invoices_add(db):
    owner = _user(db)
    tag = uuid.uuid4().hex[:6]
    first = _csv(f"GC {tag},06/10/2026,Green Choice,Cris,40,8", f"GC {tag},06/11/2026,Green Choice,Cris,40,2")
    result = weekly.import_invoices(db, csv_bytes=first, user=owner)
    assert (result.total, result.invoices, result.hours) == (2, [f"GC {tag}"], Decimal(10))
    weekly.import_invoices(db, csv_bytes=first, user=owner)
    assert len(_rows(db, f"GC {tag}")) == 2
    weekly.import_invoices(db, csv_bytes=_csv(f"BT {tag},2026-06-10,BT Restoration,,26,40"), user=owner)
    assert len(_rows(db, f"GC {tag}")) == 2 and len(_rows(db, f"BT {tag}")) == 1
    assert _rows(db, f"GC {tag}")[0].week == 3


def test_bad_rows_fail_the_file_naming_the_row(db):
    owner = _user(db)
    with pytest.raises(WorkOrderStateError, match="Row 3: unknown vendor 'Acme'"):
        weekly.import_invoices(db, csv_bytes=_csv("X 1,06/10/2026,Belfor,,0,1", "X 1,06/10/2026,Acme,,0,1"), user=owner)
    assert _rows(db, "X 1") == []


def test_upload_route_is_owner_only(db):
    admin = _user(db, "admin")
    files = {"file": ("inv.csv", _csv("GC 9,06/10/2026,Green Choice,,40,8"), "text/csv")}
    try:
        assert _client(db, admin).post("/work-orders/smr/invoices", files=files).status_code == 403
        assert _client(db, _user(db)).post("/work-orders/smr/invoices", files=files).status_code == 200
        assert _client(db, _user(db, "technician")).get("/work-orders/smr/weekly-hours").status_code == 403
    finally:
        del app.dependency_overrides[get_db]


def _cell(out, week, vendor):
    found = next((c for c in out.cells if c.week == week and c.vendor == vendor), None)
    return tuple(getattr(found, k) if found else Decimal(0) for k in ("original", "added", "invoiced"))


def test_weekly_cell_arithmetic(db):
    """Deltas against whatever the dev DB already holds for the cell."""
    owner = _user(db)
    tag = uuid.uuid4().hex[:6]
    before = _cell(weekly.weekly_hours(db), 3, "Green Choice")
    before_unknown = _cell(weekly.weekly_hours(db), None, "Unknown")
    db.add(SmrWorker(display_name=f"Cris {tag}", vendor="Green Choice", aliases=[f"C. {tag}"]))
    closed = WorkOrder(number=f"WO-{tag}-a", created_by_id=owner.id, smr_imported_at=datetime.now(timezone.utc),
                       smr_baseline={"source_row": {"COMPLETION DATE": "06/10/2026", "ASSIGNED TO": f"c. {tag}"},
                                     "totals": {"real_billed_minutes": 540, "skilled_billed_minutes": 60}})
    undated = WorkOrder(number=f"WO-{tag}-b", created_by_id=owner.id, smr_imported_at=datetime.now(timezone.utc),
                        smr_baseline={"source_row": {"ASSIGNED TO": "nobody"}, "totals": {"real_billed_minutes": 30}})
    db.add_all([closed, undated])
    db.flush()
    db.add(SmrLaborLine(work_order_id=closed.id, work_date=date(2026, 6, 9), vendor="Green Choice", headcount=2,
                        hours_each=Decimal(2), kind="field", reason_code="accurate", status="charged", week=3))
    db.add(SmrLaborLine(work_order_id=closed.id, work_date=date(2026, 6, 9), vendor="Green Choice", headcount=1,
                        hours_each=Decimal(9), kind="field", reason_code="accurate", status="excluded", week=3))
    db.flush()
    weekly.import_invoices(db, csv_bytes=_csv(f"GC {tag},06/08/2026,Green Choice,,40,30"), user=owner)

    out = weekly.weekly_hours(db)
    after = _cell(out, 3, "Green Choice")
    assert tuple(a - b for a, b in zip(after, before)) == (Decimal(10), Decimal(4), Decimal(30))
    cell = next(c for c in out.cells if c.week == 3 and c.vendor == "Green Choice")
    assert cell.missing == max(cell.invoiced - cell.added, Decimal(0)) and cell.week_label == "Week 3"
    assert _cell(out, None, "Unknown")[0] - before_unknown[0] == Decimal("0.5")
    assert out.weeks[-1] is None and "Green Choice" in out.vendors
