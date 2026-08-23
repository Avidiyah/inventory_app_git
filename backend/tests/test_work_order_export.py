"""The Work Orders CSV export: scope filtering, row content, and round-trip.

The export is the mirror of the import, so the property that matters most is
that a downloaded file can be uploaded back: its first seven columns are the
import's own headers, and `parse_import_row` must read them. The rest of the
suite pins the scope vocabulary (`all` / `archived` / one live status), the
per-row values, and that the export never widens what a caller can see.

DB-backed tests skip if no database (the `db` fixture).
"""

import csv
import io
import os
import re
import sys
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.domain import work_orders as wo
from app.domain.errors import WorkOrderStateError
from app.models import Item, User
from app.routers.work_orders import export_work_orders as export_route
from app.services import auth
from app.services import work_orders as wos


# --- seed helpers --------------------------------------------------------

def _seed_user(db, role, first="Jamie", last="Rivera"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        first_name=first,
        last_name=last,
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _seed_item(db, qty=100, price="2.50", name="Spray Paint"):
    item = Item(
        barcode=f"BC-{uuid.uuid4().hex[:10]}",
        name=name,
        quantity=Decimal(qty),
        location="Bay 1",
        # `None` seeds an item that has no price yet -- the case the receipt
        # calls out rather than billing as free.
        price=None if price is None else Decimal(price),
    )
    db.add(item)
    db.flush()
    return item


def _wo(db, creator, **attrs):
    return wos.get_or_create_work_order(
        db,
        number=f"WO-{uuid.uuid4().hex[:8]}",
        created_by_id=creator.id,
        **attrs,
    )


def _rows(db, *, user, scope, numbers=None, **filters):
    """Parsed export rows, optionally narrowed to the numbers a test seeded --
    the fixture rolls back rather than truncating, so a developer's existing
    work orders are in the file too."""
    text = wos.export_work_orders_csv(db, user=user, scope=scope, **filters)
    rows = list(csv.DictReader(io.StringIO(text)))
    if numbers is None:
        return rows
    wanted = set(numbers)
    return [row for row in rows if row["WORK ORDER"] in wanted]


# --- scope vocabulary (pure) ---------------------------------------------

@pytest.mark.parametrize(
    "scope",
    ("all", "archived") + wo.ALL_STATUSES,
)
def test_every_documented_scope_validates(scope):
    wo.validate_export_scope(scope)  # does not raise


@pytest.mark.parametrize("scope", ("", "closed", "ALL", "in progress", "deleted"))
def test_unknown_scope_is_rejected(scope):
    with pytest.raises(WorkOrderStateError):
        wo.validate_export_scope(scope)


def test_export_headers_lead_with_the_import_headers():
    # This is what makes an export re-importable; if the import schema ever
    # changes, the export must move with it.
    assert wo.EXPORT_HEADERS[: len(wo.IMPORT_HEADERS)] == wo.IMPORT_HEADERS


# --- file shape ----------------------------------------------------------

def test_header_row_matches_the_declared_columns(db):
    text = wos.export_work_orders_csv(db, user=None, scope="all")
    assert next(csv.reader(io.StringIO(text))) == list(wo.EXPORT_HEADERS)


def test_export_round_trips_through_the_import_parser(db):
    admin = _seed_user(db, "admin")
    work_order = _wo(
        db,
        admin,
        location="Scholars Inn: 1132 - Shower 1",
        output_to="Belfor",
        vendor_assignee="Hayden Hurst (Belfor)",
        service_type="SMR27 - Belfor Re-Work",
        schedule_date="7/9/2026",
        description="Please remove the bugs in the light covers",
    )

    (row,) = _rows(db, user=admin, scope="all", numbers=[work_order.number])
    parsed = wo.parse_import_row(row)

    assert parsed == {
        "number": work_order.number,
        "location": "Scholars Inn: 1132 - Shower 1",
        "output_to": "Belfor",
        "vendor_assignee": "Hayden Hurst (Belfor)",
        "service_type": "SMR27 - Belfor Re-Work",
        "schedule_date": "7/9/2026",
        "description": "Please remove the bugs in the light covers",
    }


def test_generated_task_link_round_trips_through_operational_export(db):
    admin = _seed_user(db, "admin")
    number = f"WO-{uuid.uuid4().hex[:8]}"
    csv_bytes = (
        ",".join(wo.IMPORT_HEADERS)
        + "\r\n"
        + ",".join([number, "Commons", "Belfor", "", "SMR27", "7/9/2026", ""])
        + "\r\n"
    ).encode("utf-8")
    wos.import_work_orders(db, csv_bytes=csv_bytes, user=admin)
    fallback = wo.work_order_task_fallback(number)

    (row,) = _rows(db, user=admin, scope="all", numbers=[number])

    assert row["SYMPTOM/TASK"] == fallback
    assert wo.parse_import_row(row)["description"] == fallback

    result = wos.import_work_orders(
        db,
        csv_bytes=wos.export_work_orders_csv(
            db,
            user=admin,
            scope="all",
            search=number,
        ).encode("utf-8"),
        user=admin,
    )
    assert result["opened"] == 1
    assert wos.find_by_number(db, number).description == fallback


def test_row_carries_status_assignment_and_billing(db):
    admin = _seed_user(db, "admin")
    tech = _seed_user(db, "technician", first="Alex", last="Stone")
    other_tech = _seed_user(db, "technician", first="Sam", last="Diaz")
    item = _seed_item(db, qty=100, price="2.50")
    work_order = _wo(db, admin)
    wos.update_work_order(
        db,
        work_order.id,
        user=admin,
        fields={"assigned_to_ids": [tech.id, other_tech.id]},
    )
    wos.add_work_order_item(
        db, work_order.id, user=admin, item_id=item.id, quantity=Decimal(4)
    )
    wos.add_work_order_labor(
        db, work_order.id, user=admin, technician_id=tech.id, minutes=45
    )

    (row,) = _rows(db, user=admin, scope="all", numbers=[work_order.number])

    assert row["STATUS"] == "in_progress"  # material + labor activity
    # Multiple technicians collapse into one semicolon-joined cell.
    assert row["TECHNICIANS"] == "Alex Stone; Sam Diaz"
    assert row["MATERIAL LINES"] == "1"
    assert row["MATERIALS TOTAL"] == "10.00"  # 4 x $2.50
    assert row["LABOR MINUTES"] == "45"
    assert row["BILLED LABOR MINUTES"] == "60"  # rounded up to the increment
    assert row["LABOR TOTAL"] == "62.50"
    assert row["TOTAL"] == "72.50"
    assert row["ARCHIVED AT"] == ""


def test_billable_override_drives_the_materials_total(db):
    # The export bills exactly what the work-order detail bills.
    admin = _seed_user(db, "admin")
    item = _seed_item(db, qty=100, price="2.50")
    work_order = _wo(db, admin)
    line = wos.add_work_order_item(
        db, work_order.id, user=admin, item_id=item.id, quantity=Decimal(4)
    )
    wos.set_work_order_item_billable(
        db, work_order.id, line.id, user=admin, billable_quantity=Decimal(1)
    )

    (row,) = _rows(db, user=admin, scope="all", numbers=[work_order.number])
    assert row["MATERIALS TOTAL"] == "2.50"  # 1 billable x $2.50, not 4


# --- scope filtering -----------------------------------------------------

def test_status_scope_selects_only_that_status(db):
    admin = _seed_user(db, "admin")
    created = _wo(db, admin)
    on_hold = _wo(db, admin)
    wos.update_work_order(db, on_hold.id, user=admin, fields={"status": "on_hold"})
    numbers = [created.number, on_hold.number]

    assert [r["WORK ORDER"] for r in _rows(db, user=admin, scope="on_hold", numbers=numbers)] == [
        on_hold.number
    ]
    assert [r["WORK ORDER"] for r in _rows(db, user=admin, scope="created", numbers=numbers)] == [
        created.number
    ]


def test_operational_export_combines_the_active_work_order_filters(db):
    admin = _seed_user(db, "admin")
    supervisor = _seed_user(db, "supervisor", first="Avery", last="Able")
    other_supervisor = _seed_user(db, "supervisor", first="Blake", last="Baker")
    prefix = f"WO-EXPORT-FILTER-{uuid.uuid4().hex[:8]}"

    def make(
        suffix,
        *,
        routed=supervisor,
        service="Repair",
        location="Commons",
        scheduled="7/28/2026",
    ):
        work_order = wos.get_or_create_work_order(
            db,
            number=f"{prefix}-{suffix}",
            created_by_id=admin.id,
            supervisor_id=routed.id,
            service_type=service,
            location=location,
            schedule_date=scheduled,
        )
        wos.update_work_order(
            db, work_order.id, user=admin, fields={"status": "in_progress"}
        )
        return work_order

    target = make("TARGET")
    make("SUPERVISOR", routed=other_supervisor)
    make("SERVICE", service="Inspection")
    make("COMMUNITY", location="Centennial")
    make("DATE", scheduled="7/27/2026")

    rows = _rows(
        db,
        user=admin,
        scope="in_progress",
        service_type="repair",
        supervisor_id=supervisor.id,
        community="commons",
        scheduled_date=date(2026, 7, 28),
        search=prefix,
    )
    assert [row["WORK ORDER"] for row in rows] == [target.number]


def test_operational_export_honors_the_priority_filter(db):
    """The export shares `_apply_work_order_filters` with the list, so what the
    page shows and what the CSV contains stay the same set."""
    admin = _seed_user(db, "admin")
    emergency = _wo(db, admin)
    normal = _wo(db, admin)
    unenriched = _wo(db, admin)
    emergency.priority = "Emergency"
    normal.priority = "Normal"
    db.flush()
    numbers = [emergency.number, normal.number, unenriched.number]

    rated = _rows(
        db, user=admin, scope="all", numbers=numbers, priority="emergency"
    )
    missing = _rows(
        db,
        user=admin,
        scope="all",
        numbers=numbers,
        priority=wo.PRIORITY_FILTER_NONE,
    )

    assert [row["WORK ORDER"] for row in rated] == [emergency.number]
    assert [row["WORK ORDER"] for row in missing] == [unenriched.number]


def test_all_scope_excludes_archived_and_archived_scope_includes_only_them(db):
    admin = _seed_user(db, "admin")
    live = _wo(db, admin)
    closed = _wo(db, admin)
    wos.update_work_order(db, closed.id, user=admin, fields={"status": "completed"})
    wos.update_work_order(db, closed.id, user=admin, fields={"status": "review"})
    wos.archive_work_order(db, closed.id, user=admin)
    numbers = [live.number, closed.number]

    assert [r["WORK ORDER"] for r in _rows(db, user=admin, scope="all", numbers=numbers)] == [
        live.number
    ]

    (archived_row,) = _rows(db, user=admin, scope="archived", numbers=numbers)
    assert archived_row["WORK ORDER"] == closed.number
    assert archived_row["ARCHIVED AT"] != ""


def test_unknown_scope_reaches_the_caller_as_a_domain_error(db):
    with pytest.raises(WorkOrderStateError):
        wos.export_work_orders_csv(db, user=None, scope="everything")


# --- visibility ----------------------------------------------------------

def test_export_is_scoped_like_the_list(db):
    # An export must not become a way to read work orders the page hides.
    admin = _seed_user(db, "admin")
    tech = _seed_user(db, "technician")
    mine = _wo(db, admin)
    theirs = _wo(db, admin)
    wos.update_work_order(db, mine.id, user=admin, fields={"assigned_to_ids": [tech.id]})
    numbers = [mine.number, theirs.number]

    assert [r["WORK ORDER"] for r in _rows(db, user=tech, scope="all", numbers=numbers)] == [
        mine.number
    ]
    assert {r["WORK ORDER"] for r in _rows(db, user=admin, scope="all", numbers=numbers)} == set(
        numbers
    )


# --- the "For Client" variant --------------------------------------------

def _client_rows(db, *, user, scope, numbers):
    text = wos.export_work_orders_csv(db, user=user, scope=scope, variant="client")
    rows = list(csv.DictReader(io.StringIO(text)))
    wanted = set(numbers)
    return [row for row in rows if row["WORK ORDER"] in wanted]


def test_client_variant_has_only_the_billing_columns(db):
    text = wos.export_work_orders_csv(db, user=None, scope="all", variant="client")
    assert next(csv.reader(io.StringIO(text))) == [
        "WORK ORDER",
        "MATERIAL TOTAL",
        "LABOR TOTAL",
        "RECEIPT",
    ]


def test_client_row_carries_billed_totals_and_the_full_receipt(db):
    admin = _seed_user(db, "admin")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, qty=100, price="2.50")
    work_order = _wo(db, admin)
    wos.update_work_order(
        db, work_order.id, user=admin, fields={"assigned_to_ids": [tech.id]}
    )
    wos.add_work_order_item(
        db, work_order.id, user=admin, item_id=item.id, quantity=Decimal(4)
    )
    wos.add_work_order_labor(
        db, work_order.id, user=admin, technician_id=tech.id, minutes=30
    )

    (row,) = _client_rows(db, user=admin, scope="all", numbers=[work_order.number])

    # 4 x $2.50 = $10.00, marked up 15% -> the receipt's own material charge.
    assert row["MATERIAL TOTAL"] == "$11.50"
    assert row["LABOR TOTAL"] == "$31.25"
    # The receipt is the whole document, newlines intact through CSV quoting.
    assert row["RECEIPT"].splitlines() == [
        "4 Spray Paint                      $11.50",
        "[0.5] Labor Hours                  $31.25",
        "",
        "Total                              $42.75",
    ]
    # The two totals add up to what the receipt bills -- that is the point of
    # using billed (marked-up) figures in the columns.
    assert Decimal("11.50") + Decimal("31.25") == Decimal("42.75")


def test_client_row_flags_an_unpriced_item_rather_than_billing_zero(db):
    admin = _seed_user(db, "admin")
    priced = _seed_item(db, qty=100, price="2.50")
    unpriced = _seed_item(db, qty=100, price=None, name="Mystery Part")
    work_order = _wo(db, admin)
    for item in (priced, unpriced):
        wos.add_work_order_item(
            db, work_order.id, user=admin, item_id=item.id, quantity=Decimal(1)
        )

    (row,) = _client_rows(db, user=admin, scope="all", numbers=[work_order.number])

    assert "NO PRICE" in row["RECEIPT"]
    assert "Total (incomplete)" in row["RECEIPT"]
    # The priced line still bills; the unpriced one contributes nothing.
    assert row["MATERIAL TOTAL"] == "$2.88"


def test_client_variant_honours_scope_and_visibility(db):
    admin = _seed_user(db, "admin")
    tech = _seed_user(db, "technician")
    mine = _wo(db, admin)
    theirs = _wo(db, admin)
    wos.update_work_order(db, mine.id, user=admin, fields={"assigned_to_ids": [tech.id]})
    numbers = [mine.number, theirs.number]

    assert [r["WORK ORDER"] for r in _client_rows(db, user=tech, scope="all", numbers=numbers)] == [
        mine.number
    ]


def test_client_variant_remains_scope_only_when_operational_filters_are_supplied(db):
    admin = _seed_user(db, "admin")
    work_order = _wo(db, admin, service_type="Repair")

    text = wos.export_work_orders_csv(
        db,
        user=admin,
        scope="all",
        variant="client",
        service_type="does-not-match",
        community="commons",
        scheduled_date=date(2099, 1, 1),
        search="does-not-match",
    )
    rows = list(csv.DictReader(io.StringIO(text)))
    assert work_order.number in {row["WORK ORDER"] for row in rows}


def test_full_variant_is_unchanged_by_the_client_one(db):
    admin = _seed_user(db, "admin")
    work_order = _wo(db, admin)

    (row,) = _rows(db, user=admin, scope="all", numbers=[work_order.number])
    assert set(wo.EXPORT_HEADERS) <= set(row)
    assert "RECEIPT" not in row


@pytest.mark.parametrize("variant", ("", "invoice", "FULL", "customer"))
def test_unknown_variant_is_rejected(variant):
    with pytest.raises(WorkOrderStateError):
        wo.validate_export_variant(variant)


# --- route ---------------------------------------------------------------

def test_route_returns_a_csv_attachment(db):
    admin = _seed_user(db, "admin")
    work_order = _wo(db, admin)

    # Every argument is passed explicitly: calling the handler directly skips
    # FastAPI's dependency resolution, so a `Query(...)` default would arrive as
    # the Query object rather than its value.
    response = export_route(scope="all", variant="full", user=admin, db=db)

    assert response.media_type.startswith("text/csv")
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert re.search(r'filename="\d{2}-\d{2}-\d{2}_\d{2}-\d{2}_all\.csv"', disposition)
    assert work_order.number in response.body.decode("utf-8")


def test_route_forwards_operational_export_filters(db, monkeypatch):
    admin = _seed_user(db, "admin")
    supervisor = _seed_user(db, "supervisor", first="Avery", last="Able")
    supervisor_id = supervisor.id
    captured = {}

    def export_filtered(db, **kwargs):
        captured.update(kwargs)
        return "WORK ORDER\r\n"

    monkeypatch.setattr(wos, "export_work_orders_csv", export_filtered)
    response = export_route(
        scope="in_progress",
        variant="full",
        service_type="Repair",
        supervisor_id=supervisor_id,
        community="commons",
        priority="Emergency",
        priority_bucket="high",
        scheduled_date=date(2026, 7, 28),
        q="WO-123",
        user=admin,
        db=db,
    )

    assert response.body == b"WORK ORDER\r\n"
    assert re.search(
        r'filename="\d{2}-\d{2}-\d{2}_\d{2}-\d{2}_status-in-progress-service-repair-'
        r'supervisor-avery-able-community-commons-priority-emergency-level-high-'
        r'date-2026-07-28-number-wo-123\.csv"',
        response.headers["content-disposition"],
    )
    assert captured == {
        "user": admin,
        "scope": "in_progress",
        "variant": "full",
        "service_type": "Repair",
        "supervisor_id": supervisor_id,
        "community": "commons",
        "priority": "Emergency",
        "priority_bucket": "high",
        "scheduled_date": date(2026, 7, 28),
        "search": "WO-123",
    }


# The Admin+ gate on this route is asserted in `test_route_role_gates.py`
# (`test_folded_work_order_gates_are_declarative`). C1 moved it out of the
# handler body into `Depends(require_min_role("admin"))`, and a directly-called
# handler never resolves its dependencies -- so a below-rank call like the one
# that used to live here now builds the CSV instead of raising 403. The gate is
# unchanged; only where it is written, and therefore where it is provable, has
# moved. The 400 checks below still belong here: those are the route's own.


def test_route_reports_an_unknown_scope_as_400(db):
    admin = _seed_user(db, "admin")

    with pytest.raises(HTTPException) as exc:
        export_route(scope="closed", variant="full", user=admin, db=db)
    assert exc.value.status_code == 400
    # Name the offending field, so this cannot pass on the variant's message.
    assert "filter" in exc.value.detail


def test_route_names_the_client_file_distinctly(db):
    # Two exports of the same scope must not land on top of each other in the
    # downloads folder.
    admin = _seed_user(db, "admin")

    full = export_route(scope="all", variant="full", user=admin, db=db)
    client = export_route(scope="all", variant="client", user=admin, db=db)

    assert re.search(
        r'filename="\d{2}-\d{2}-\d{2}_\d{2}-\d{2}_all\.csv"',
        full.headers["content-disposition"],
    )
    assert re.search(
        r'filename="\d{2}-\d{2}-\d{2}_\d{2}-\d{2}_client-all\.csv"',
        client.headers["content-disposition"],
    )
    assert client.body.decode("utf-8").startswith("WORK ORDER,MATERIAL TOTAL")


def test_route_reports_an_unknown_variant_as_400(db):
    admin = _seed_user(db, "admin")

    with pytest.raises(HTTPException) as exc:
        export_route(scope="all", variant="invoice", user=admin, db=db)
    assert exc.value.status_code == 400
    assert "variant" in exc.value.detail
