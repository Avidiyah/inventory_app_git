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
import sys
import uuid
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


def _rows(db, *, user, scope, numbers=None):
    """Parsed export rows, optionally narrowed to the numbers a test seeded --
    the fixture rolls back rather than truncating, so a developer's existing
    work orders are in the file too."""
    text = wos.export_work_orders_csv(db, user=user, scope=scope)
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


def test_all_scope_excludes_archived_and_archived_scope_includes_only_them(db):
    admin = _seed_user(db, "admin")
    live = _wo(db, admin)
    closed = _wo(db, admin)
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
    assert "work-orders-all-" in disposition
    assert work_order.number in response.body.decode("utf-8")


def test_route_rejects_below_admin(db):
    supervisor = _seed_user(db, "supervisor")

    with pytest.raises(HTTPException) as exc:
        export_route(scope="all", variant="full", user=supervisor, db=db)
    assert exc.value.status_code == 403


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

    assert "work-orders-all-" in full.headers["content-disposition"]
    assert "work-orders-client-all-" in client.headers["content-disposition"]
    assert client.body.decode("utf-8").startswith("WORK ORDER,MATERIAL TOTAL")


def test_route_reports_an_unknown_variant_as_400(db):
    admin = _seed_user(db, "admin")

    with pytest.raises(HTTPException) as exc:
        export_route(scope="all", variant="invoice", user=admin, db=db)
    assert exc.value.status_code == 400
    assert "variant" in exc.value.detail
