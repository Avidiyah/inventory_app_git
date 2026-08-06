"""Tests for the CSV work-order import (the new default schema).

Pure coverage of the two import helpers (`normalize_assignee_name`,
`parse_import_row`), DB-backed coverage of `services.work_orders.import_work_orders`
(create, idempotent re-upload, supervisor name-match, blank-number skip), and the
Admin+ gate on the router handler. DB-backed tests skip if no database.
"""

import asyncio
import io
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException, UploadFile

from app.domain import roles
from app.domain import work_orders as wo
from app.domain.errors import WorkOrderStateError
from app.models import Item, User, WorkOrder
from app.routers.work_orders import import_work_orders as import_route
from app.services import auth
from app.services import work_orders as wos


# --- pure helpers --------------------------------------------------------

def test_normalize_assignee_name_strips_vendor_tag():
    assert wo.normalize_assignee_name("Hayden Hurst (Belfor)") == "hayden hurst"
    assert wo.normalize_assignee_name("  Alissa   Stephens (Belfor) ") == "alissa stephens"
    assert wo.normalize_assignee_name("Belfor Dispatch") == "belfor dispatch"


def test_normalize_assignee_name_blank_is_none():
    assert wo.normalize_assignee_name("") is None
    assert wo.normalize_assignee_name("   ") is None
    assert wo.normalize_assignee_name(None) is None


def test_parse_import_row_maps_headers():
    row = {
        "WORK ORDER": " 23490253 ",
        "LOCATION": "Commons Apartments: 8B",
        "OUTPUT TO": "Belfor",
        "ASSIGNED TO": "Hayden Hurst (Belfor)",
        "SERVICE TYPE": "SMR27 - Belfor",
        "SCHEDULE DATE": "7/29/2026",
        "SYMPTOM/TASK": "Fix the couch",
    }
    parsed = wo.parse_import_row(row)
    assert parsed == {
        "number": "23490253",
        "location": "Commons Apartments: 8B",
        "output_to": "Belfor",
        "vendor_assignee": "Hayden Hurst (Belfor)",
        "service_type": "SMR27 - Belfor",
        "schedule_date": "7/29/2026",
        "description": "Fix the couch",
    }


def test_parse_import_row_blanks_become_none():
    parsed = wo.parse_import_row({"WORK ORDER": "", "LOCATION": "   "})
    assert parsed["number"] is None
    assert parsed["location"] is None
    assert parsed["description"] is None


def test_work_order_task_fallback_builds_one_safe_url_path_segment():
    assert wo.work_order_task_fallback("  WO 12/3 #A  ") == (
        "https://system.netfacilities.com/tools/viewworkorders/"
        "WO%2012%2F3%20%23A"
    )


def test_work_order_task_fallback_recognizes_only_the_canonical_link():
    number = "23490253"
    fallback = wo.work_order_task_fallback(number)

    assert wo.is_work_order_task_fallback(fallback, number)
    assert not wo.is_work_order_task_fallback("Repair the sink", number)
    assert not wo.is_work_order_task_fallback(f"{fallback}/extra", number)


# --- service (DB-backed) -------------------------------------------------

def _seed_user(db, role, username=None, first_name=None, last_name=None):
    user = User(
        username=username or f"u-{uuid.uuid4().hex[:10]}",
        first_name=first_name,
        last_name=last_name,
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _csv(rows):
    """Build CSV bytes with the export header row + the given data rows."""
    lines = [",".join(wo.IMPORT_HEADERS)]
    for r in rows:
        # Minimal quoting: wrap any field containing a comma.
        cells = [f'"{c}"' if "," in c else c for c in r]
        lines.append(",".join(cells))
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def _num():
    return f"WO-{uuid.uuid4().hex[:8]}"


def test_import_creates_work_orders_with_new_fields(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    n1 = _num()
    csv_bytes = _csv([
        [n1, "Commons: 8B", "Belfor", "Nobody Here (Belfor)", "SMR27 - Belfor", "7/29/2026", "Fix couch"],
    ])
    result = wos.import_work_orders(db, csv_bytes=csv_bytes, user=admin)
    assert result["created"] == 1
    assert result["opened"] == 0
    assert result["skipped"] == 0

    row = wos.find_by_number(db, n1)
    assert row is not None
    assert row.location == "Commons: 8B"
    assert row.output_to == "Belfor"
    assert row.vendor_assignee == "Nobody Here (Belfor)"
    assert row.service_type == "SMR27 - Belfor"
    assert row.schedule_date == "7/29/2026"
    assert row.description == "Fix couch"
    assert row.legacy is False
    assert row.supervisor_id is None  # no matching supervisor
    assert row.status == "created"
    assert row.created_by_id == admin.id


def test_import_missing_task_uses_replaceable_work_order_link(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    number = _num()
    blank_task = _csv([[
        number, "Commons: 8B", "Belfor", "", "SMR27", "7/29/2026", "   "
    ]])

    first = wos.import_work_orders(db, csv_bytes=blank_task, user=admin)
    assert first["created"] == 1
    work_order = wos.find_by_number(db, number)
    assert work_order.description == wo.work_order_task_fallback(number)

    real_task = _csv([[
        number, "Commons: 8B", "Belfor", "", "SMR27", "7/29/2026", "Fix couch"
    ]])
    second = wos.import_work_orders(db, csv_bytes=real_task, user=admin)
    assert second["opened"] == 1
    db.refresh(work_order)
    assert work_order.description == "Fix couch"

    # The fallback is replaceable, but an explicit Admin edit remains authoritative.
    wos.update_work_order(
        db,
        work_order.id,
        user=admin,
        fields={"description": "Manual task"},
    )
    wos.import_work_orders(db, csv_bytes=blank_task, user=admin)
    wos.import_work_orders(
        db,
        csv_bytes=_csv([[
            number, "Commons: 8B", "Belfor", "", "SMR27", "7/29/2026", "Different task"
        ]]),
        user=admin,
    )
    db.refresh(work_order)
    assert work_order.description == "Manual task"


def test_import_missing_task_column_uses_work_order_link(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    number = _num()
    csv_bytes = (
        f"WORK ORDER,LOCATION\r\n{number},Commons 101\r\n".encode("utf-8")
    )

    result = wos.import_work_orders(db, csv_bytes=csv_bytes, user=admin)

    assert result["created"] == 1
    assert wos.find_by_number(db, number).description == wo.work_order_task_fallback(number)


def test_duplicate_import_rows_prefer_real_task_over_generated_link(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    number = _num()
    csv_bytes = _csv([
        [number, "Loc", "Belfor", "", "SMR27", "7/1/2026", ""],
        [number, "Loc", "Belfor", "", "SMR27", "7/1/2026", "Real task"],
    ])

    result = wos.import_work_orders(db, csv_bytes=csv_bytes, user=admin)

    assert result["created"] == 1
    assert result["opened"] == 1
    assert wos.find_by_number(db, number).description == "Real task"


@pytest.mark.parametrize(
    "csv_template",
    (
        "",
        "NUMBER,LOCATION\r\n{number},Commons\r\n",
        "WORK ORDER;LOCATION\r\n{number};Commons\r\n",
    ),
)
def test_import_rejects_missing_work_order_header_before_writes(db, csv_template):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    number = _num()
    csv_bytes = csv_template.format(number=number).encode("utf-8")

    with pytest.raises(WorkOrderStateError, match="WORK ORDER"):
        wos.import_work_orders(db, csv_bytes=csv_bytes, user=admin)

    assert wos.find_by_number(db, number) is None


def test_import_rejects_non_utf8_file_before_writes(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    number = _num()

    with pytest.raises(WorkOrderStateError, match="UTF-8"):
        wos.import_work_orders(
            db,
            csv_bytes=(
                f"WORK ORDER,SYMPTOM/TASK\r\n{number},".encode("utf-8")
                + b"\xff\r\n"
            ),
            user=admin,
        )

    assert wos.find_by_number(db, number) is None


def test_import_does_not_add_task_link_to_closed_work_order(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    number = _num()
    work_order = wos.get_or_create_work_order(
        db,
        number=number,
        created_by_id=admin.id,
        description=None,
    )
    wos.archive_work_order(db, work_order.id, user=admin)

    result = wos.import_work_orders(
        db,
        csv_bytes=_csv([[number, "Loc", "Belfor", "", "SMR27", "7/1/2026", ""]]),
        user=admin,
    )

    assert result["closed"] == 1
    db.refresh(work_order)
    assert work_order.description is None


def test_reimport_preserves_a_manual_supervisor_change(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    imported_supervisor, csv_name = _seed_named_supervisor(db)
    manual_supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    n1 = _num()
    csv_bytes = _csv([[
        n1, "Loc", "Belfor", csv_name, "SMR27", "7/1/2026", "Task"
    ]])

    first = wos.import_work_orders(db, csv_bytes=csv_bytes, user=admin)
    assert first["created"] == 1
    row = wos.find_by_number(db, n1)
    assert row.supervisor_id == imported_supervisor.id

    # A manual reroute between imports must be authoritative, even though the
    # repeated CSV still matches the original supervisor.
    wos.update_work_order(
        db,
        row.id,
        user=admin,
        fields={"supervisor_id": manual_supervisor.id},
        expected_supervisor_id=imported_supervisor.id,
    )

    second = wos.import_work_orders(db, csv_bytes=csv_bytes, user=admin)
    assert second["created"] == 0
    assert second["opened"] == 1
    # Fill-blank re-import never clobbered the manual routing.
    routed = wos.find_by_number(db, n1)
    assert routed.supervisor_id == manual_supervisor.id
    assert routed.status == "created"  # supervisor routing is not tech assignment


def test_import_counts_and_ignores_closed_work_orders(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    technician = _seed_user(db, roles.ROLE_TECHNICIAN)
    item = Item(
        id=uuid.uuid4(),
        barcode=f"BC-{uuid.uuid4().hex[:8]}",
        name="Closed WO material",
        quantity=Decimal("10"),
        location="Warehouse",
        price=Decimal("2.50"),
    )
    db.add(item)
    db.flush()
    number = _num()
    work_order = wos.get_or_create_work_order(
        db,
        number=number,
        created_by_id=admin.id,
        supervisor_id=supervisor.id,
        assigned_to_id=technician.id,
        location="Original location",
        description="Original task",
    )
    wos.update_work_order(
        db, work_order.id, user=admin, fields={"notes": "Keep this note."}
    )
    notes_before_import = work_order.notes
    wos.add_work_order_item(
        db,
        work_order.id,
        user=technician,
        item_id=item.id,
        quantity=Decimal("2"),
    )
    wos.add_work_order_labor(
        db,
        work_order.id,
        user=supervisor,
        technician_id=technician.id,
        minutes=45,
    )
    wos.archive_work_order(db, work_order.id, user=admin)
    archived_at = work_order.archived_at

    result = wos.import_work_orders(
        db,
        csv_bytes=_csv([[
            number,
            "Replacement location",
            "Replacement output",
            "Replacement Vendor",
            "Replacement service",
            "8/4/2026",
            "Replacement task",
        ]]),
        user=admin,
    )

    assert result == {
        "total": 1,
        "created": 0,
        "opened": 0,
        "closed": 1,
        "supervisors_matched": 0,
        "supervisors_unmatched": 0,
        "skipped": 0,
    }
    db.refresh(work_order)
    assert work_order.archived_at == archived_at
    assert work_order.location == "Original location"
    assert work_order.description == "Original task"
    assert work_order.notes == notes_before_import
    assert work_order.notes.endswith("[Name unavailable] Keep this note.")
    assert len(work_order.items) == 1
    assert work_order.items[0].quantity == Decimal("2")
    assert len(work_order.labor_entries) == 1
    assert work_order.labor_entries[0].minutes == 45


def _seed_named_supervisor(db):
    """A supervisor whose login differs from the matching human name."""
    suffix = uuid.uuid4().hex[:6]
    first_name = "Hayden"
    last_name = f"Hurst-{suffix}"
    sup = _seed_user(
        db,
        roles.ROLE_SUPERVISOR,
        username=f"supervisor-{suffix}",
        first_name=first_name,
        last_name=last_name,
    )
    return sup, f"{first_name} {last_name} (Belfor)"


def test_import_matches_supervisor_by_name(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    sup, csv_name = _seed_named_supervisor(db)
    hit, miss = _num(), _num()
    csv_bytes = _csv([
        [hit, "Loc1", "Belfor", csv_name, "SMR27", "7/1/2026", "A"],
        [miss, "Loc2", "Belfor", "Unknown Person (Belfor)", "SMR27", "7/2/2026", "B"],
    ])
    result = wos.import_work_orders(db, csv_bytes=csv_bytes, user=admin)
    assert result["supervisors_matched"] == 1
    assert result["supervisors_unmatched"] == 1
    matched = wos.find_by_number(db, hit)
    unmatched = wos.find_by_number(db, miss)
    assert matched.supervisor_id == sup.id
    assert matched.status == "created"
    assert unmatched.supervisor_id is None
    assert unmatched.status == "created"


def test_import_matches_admin_as_supervisor_by_name(db):
    importing_admin = _seed_user(db, roles.ROLE_ADMIN)
    routed_admin = _seed_user(
        db,
        roles.ROLE_ADMIN,
        first_name="Morgan",
        last_name=f"Admin-{uuid.uuid4().hex[:6]}",
    )
    number = _num()
    csv_name = f"{routed_admin.first_name} {routed_admin.last_name} (Belfor)"

    result = wos.import_work_orders(
        db,
        csv_bytes=_csv([[
            number,
            "Loc",
            "Belfor",
            csv_name,
            "SMR27",
            "7/1/2026",
            "A",
        ]]),
        user=importing_admin,
    )

    assert result["supervisors_matched"] == 1
    assert wos.find_by_number(db, number).supervisor_id == routed_admin.id


def test_import_does_not_match_username_or_incomplete_human_name(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    username_match = _seed_user(
        db,
        roles.ROLE_SUPERVISOR,
        username=f"Hayden Hurst {uuid.uuid4().hex[:6]}",
    )
    number = _num()
    csv_bytes = _csv([[
        number,
        "Loc",
        "Belfor",
        f"{username_match.username} (Belfor)",
        "SMR27",
        "7/1/2026",
        "A",
    ]])

    result = wos.import_work_orders(db, csv_bytes=csv_bytes, user=admin)

    assert result["supervisors_matched"] == 0
    assert result["supervisors_unmatched"] == 1
    assert wos.find_by_number(db, number).supervisor_id is None


def test_import_ignores_whitespace_only_name_parts(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _seed_user(
        db,
        roles.ROLE_SUPERVISOR,
        first_name="   ",
        last_name="Smith",
    )
    number = _num()
    csv_bytes = _csv([[
        number,
        "Loc",
        "Belfor",
        "Smith (Belfor)",
        "SMR27",
        "7/1/2026",
        "A",
    ]])

    result = wos.import_work_orders(db, csv_bytes=csv_bytes, user=admin)

    assert result["supervisors_matched"] == 0
    assert result["supervisors_unmatched"] == 1
    assert wos.find_by_number(db, number).supervisor_id is None


def test_import_leaves_duplicate_full_name_unassigned(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    shared_first = "Alissa"
    shared_last = f"Stephens-{uuid.uuid4().hex[:6]}"
    for suffix in ("one", "two"):
        _seed_user(
            db,
            roles.ROLE_SUPERVISOR,
            username=f"duplicate-{suffix}-{uuid.uuid4().hex[:6]}",
            first_name=shared_first,
            last_name=shared_last,
        )
    number = _num()
    csv_bytes = _csv([[
        number,
        "Loc",
        "Belfor",
        f"{shared_first} {shared_last} (Belfor)",
        "SMR27",
        "7/1/2026",
        "A",
    ]])

    result = wos.import_work_orders(db, csv_bytes=csv_bytes, user=admin)

    assert result["supervisors_matched"] == 0
    assert result["supervisors_unmatched"] == 1
    assert wos.find_by_number(db, number).supervisor_id is None


def test_import_ignores_archived_and_non_supervisor_name_matches(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    first_name = "Casey"
    last_name = f"Morgan-{uuid.uuid4().hex[:6]}"
    archived = _seed_user(
        db,
        roles.ROLE_SUPERVISOR,
        first_name=first_name,
        last_name=last_name,
    )
    archived.archived_at = datetime.now(timezone.utc)
    _seed_user(
        db,
        roles.ROLE_TECHNICIAN,
        first_name=first_name,
        last_name=last_name,
    )
    db.flush()
    number = _num()
    csv_bytes = _csv([[
        number,
        "Loc",
        "Belfor",
        f"{first_name} {last_name} (Belfor)",
        "SMR27",
        "7/1/2026",
        "A",
    ]])

    result = wos.import_work_orders(db, csv_bytes=csv_bytes, user=admin)

    assert result["supervisors_matched"] == 0
    assert wos.find_by_number(db, number).supervisor_id is None


def test_import_accepts_excel_sep_preamble(db):
    """Excel writes an optional `sep=,` dialect hint above the header row (and a
    BOM). The vendor's export has it; the file must still import."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    number = _num()
    body = _csv([[
        number,
        "Scholars Inn: Exterior Building, Basement Storage",
        "Belfor",
        "Belfor Dispatch (Belfor)",
        "Maintenance",
        "2026-08-03",
        "Assemble the chairs",
    ]])
    csv_bytes = "﻿".encode("utf-8") + b"sep=,\r\n" + body

    result = wos.import_work_orders(db, csv_bytes=csv_bytes, user=admin)

    assert result["skipped"] == 0
    assert result["created"] == 1
    row = wos.find_by_number(db, number)
    assert row is not None
    assert row.location == "Scholars Inn: Exterior Building, Basement Storage"
    assert row.description == "Assemble the chairs"


def test_import_skips_blank_number_rows(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    good = _num()
    csv_bytes = _csv([
        ["", "Loc", "Belfor", "X", "SMR27", "7/1/2026", "no number"],
        [good, "Loc", "Belfor", "X", "SMR27", "7/1/2026", "ok"],
    ])
    result = wos.import_work_orders(db, csv_bytes=csv_bytes, user=admin)
    assert result["skipped"] == 1
    assert result["created"] == 1
    assert result["total"] == 2


def test_routed_supervisor_can_see_imported_work_order(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    sup, csv_name = _seed_named_supervisor(db)
    other_sup = _seed_user(db, roles.ROLE_SUPERVISOR)
    n1 = _num()
    csv_bytes = _csv([[n1, "Loc", "Belfor", csv_name, "SMR27", "7/1/2026", "A"]])
    wos.import_work_orders(db, csv_bytes=csv_bytes, user=admin)
    row = wos.find_by_number(db, n1)

    # The routed supervisor sees it; another supervisor does not (404 scope).
    assert wos.get_work_order(db, row.id, user=sup).id == row.id
    from app.domain.errors import WorkOrderNotFoundError
    with pytest.raises(WorkOrderNotFoundError):
        wos.get_work_order(db, row.id, user=other_sup)


# --- router gate ---------------------------------------------------------

def _upload(csv_bytes):
    return UploadFile(filename="wo.csv", file=io.BytesIO(csv_bytes))


def test_import_route_requires_admin(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    csv_bytes = _csv([[_num(), "Loc", "Belfor", "", "SMR27", "7/1/2026", "A"]])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(import_route(file=_upload(csv_bytes), user=supervisor, db=db))
    assert exc.value.status_code == 403


def test_import_route_admin_succeeds(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    csv_bytes = _csv([[_num(), "Loc", "Belfor", "", "SMR27", "7/1/2026", "A"]])
    result = asyncio.run(import_route(file=_upload(csv_bytes), user=admin, db=db))
    assert result.created == 1
    assert result.closed == 0
