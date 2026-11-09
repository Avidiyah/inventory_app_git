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
from app.models import SmrLaborLine, SmrVendorInvoice, User, WorkOrder
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


def _cell(cells, week, vendor):
    figures = cells.get((week, vendor)) or {}
    return tuple(figures.get(k, Decimal(0)) for k in ("original", "found", "undated", "invoiced"))


def _line(order, **overrides):
    fields = dict(work_order_id=order.id, work_date=date(2026, 6, 9), vendor="Green Choice", headcount=1,
                  hours_each=Decimal(2), kind="field", reason_code="accurate", status="charged", week=3)
    fields.update(overrides)
    return SmrLaborLine(**fields)


def test_weekly_cell_arithmetic(db):
    """Deltas against whatever the dev DB already holds for the cell. An order
    with a 10 h Breakdown target, 4 h charged in week 3 and 6 h undated: the
    paper (10 h) covers the target exactly, so it is all original and nothing
    is found; original follows the lines pro rata (4 h to week 3, 6 h to
    Undated), the undated hours not counted twice."""
    owner = _user(db)
    tag = uuid.uuid4().hex[:6]
    before = _cell(weekly.raw_cells(db), 3, "Green Choice")
    before_undated = _cell(weekly.raw_cells(db), None, "Green Choice")
    order = WorkOrder(number=f"WO-{tag}", created_by_id=owner.id, smr_imported_at=datetime.now(timezone.utc),
                      smr_target={"hours": "10", "total": "0", "source_row": {}})
    db.add(order)
    db.flush()
    db.add_all([
        _line(order, headcount=2),
        _line(order, work_date=None, week=None, hours_each=Decimal(6), status="excluded", exclusion_ground="undated"),
        _line(order, hours_each=Decimal(9), status="excluded", exclusion_ground="reprint (no hours added)"),
        _line(order, vendor="Belfor", hours_each=Decimal(5)),
    ])
    db.flush()
    weekly.import_invoices(db, csv_bytes=_csv(f"GC {tag},06/08/2026,Green Choice,,40,30"), user=owner)

    out = weekly.weekly_hours(db)
    assert out.vendors == ["Green Choice", "XXL Construction", "BT Restoration"]
    assert not any(c.vendor == "Belfor" for c in out.cells)
    cell = next(c for c in out.cells if c.week == 3 and c.vendor == "Green Choice")
    assert cell.missing == max(cell.invoiced - cell.original - cell.found - cell.carried, Decimal(0)) and cell.week_label == "Week 3"
    raw = weekly.raw_cells(db)
    after = _cell(raw, 3, "Green Choice")
    assert tuple(round(a - b, 2) for a, b in zip(after, before)) == (Decimal(4), Decimal(0), Decimal(0), Decimal(30))
    undated = _cell(raw, None, "Green Choice")
    assert tuple(round(a - b, 2) for a, b in zip(undated, before_undated)) == (Decimal(6), Decimal(0), Decimal(0), Decimal(0))
    # A second order whose paper (3 h) exceeds its 1 h target: 1 h original, 2 h found.
    over = WorkOrder(number=f"WO-{tag}-o", created_by_id=owner.id, smr_imported_at=datetime.now(timezone.utc),
                     smr_target={"hours": "1", "total": "0", "source_row": {}})
    db.add(over)
    db.flush()
    db.add(_line(over, vendor="BT Restoration", hours_each=Decimal(3)))
    db.flush()
    before_bt = _cell(raw, 3, "BT Restoration")
    after_bt = _cell(weekly.raw_cells(db), 3, "BT Restoration")
    assert tuple(round(a - b, 2) for a, b in zip(after_bt, before_bt)) == (Decimal(1), Decimal(2), Decimal(0), Decimal(0))


def _figures(**kw):
    return {k: Decimal(kw.get(k, 0)) for k in weekly.FIGURES}


def test_paper_above_a_week_invoice_is_carried_into_the_next_week():
    """Roll-forward (user 2026-11-06). XXL: week 1 invoiced 1 h with 4 h of paper
    (1 original + 3 found) -> 3 h carries (found first) into week 2 (invoiced 10 h,
    2 h found) which then uses 5 h; week 2 overflows nothing. A vendor's last
    week keeps its overflow on the bar. Belfor-less weeks get a cell only to
    carry."""
    cells = {
        (1, "XXL Construction"): _figures(original=1, found=3, invoiced=1),
        (2, "XXL Construction"): _figures(found=2, invoiced=10),
        (7, "Green Choice"): _figures(found=5, invoiced=0),
    }
    weekly.roll_forward(cells)
    w1, w2 = cells[(1, "XXL Construction")], cells[(2, "XXL Construction")]
    assert (w1["original"], w1["found"], w1["carried"]) == (Decimal(1), Decimal(0), Decimal(0))
    assert (w2["found"], w2["carried"], w2["invoiced"]) == (Decimal(2), Decimal(3), Decimal(10))
    assert (3, "XXL Construction") not in cells
    assert cells[(7, "Green Choice")]["found"] == Decimal(5)
    assert cells[(6, "Green Choice")]["carried"] == Decimal(0) if (6, "Green Choice") in cells else True


def test_fill_invoice_names_names_units_with_room_and_undoes(db):
    """XXL week 3: Pat invoiced 100 h, Sam 1 h. A 2-unit crew line of 2 h each:
    both units go to Pat (room), none to Sam (1 < 2); the original is removed.
    Undo removes the named lines and restores the original. Other dev-DB
    lines may take some of Pat's room too, so assertions stay on this order."""
    owner = _user(db)
    tag = uuid.uuid4().hex[:6]
    pat, sam = f"Pat {tag}", f"Sam {tag}"
    weekly.import_invoices(db, csv_bytes=_csv(f"XXL {tag},06/09/2026,XXL Construction,{pat} (REG),0,100",
                                              f"XXL {tag},06/09/2026,XXL Construction,{sam},0,1"), user=owner)
    order = WorkOrder(number=f"WO-{tag}", created_by_id=owner.id, smr_imported_at=datetime.now(timezone.utc))
    db.add(order)
    db.flush()
    crew = _line(order, vendor="XXL Construction", headcount=2, hours_each=Decimal(2))
    db.add(crew)
    db.flush()
    run = f"name test {tag}"
    mine = lambda result: sorted((n, h) for wo, _, n, h in result["named"] if wo == f"WO-{tag}")  # noqa: E731
    dry = weekly.fill_invoice_names(db, user=owner, tag=run, dry_run=True)
    assert mine(dry) == [(pat, Decimal(2)), (pat, Decimal(2))]
    db.refresh(crew)
    assert crew.headcount == 2 and crew.status == "charged"  # dry run wrote nothing

    result = weekly.fill_invoice_names(db, user=owner, tag=run)
    assert mine(result) == [(pat, Decimal(2)), (pat, Decimal(2))]
    assert not any(wo == f"WO-{tag}" for wo, *_ in result["left"])
    db.refresh(crew)
    db.refresh(order)
    named = [l for l in order.smr_lines if l.worker is not None and l.worker.display_name == pat]
    assert (crew.status, crew.exclusion_ground) == ("excluded", "removed")
    assert len(named) == 2 and all(l.hours_each == Decimal(2) and l.week == 3 and l.headcount == 1 for l in named)

    weekly.undo_invoice_names(db, user=owner, tag=run)
    db.refresh(crew)
    for l in named:
        db.refresh(l)
    assert (crew.status, crew.headcount) == ("charged", 2) and all(l.exclusion_ground == "removed" for l in named)
