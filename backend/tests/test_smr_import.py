"""The Owner-only SMR27 sheet import (spec 2026-10-23 D2/D3/D9): every Closed
row becomes a closed-but-unarchived SMR order with a baseline frozen once;
Canceled rows and live rows that are not in the sheet are left alone."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.domain import roles
from app.domain.errors import WorkOrderStateError
from app.models import User
from app.services import auth
from app.services import work_orders as wos
from app.services import work_orders_smr as smr_service


HEADERS = (
    "WORK ORDER,CREATOR,SERVICE TYPE,SCHEDULE DATE,COMPLETION DATE,ASSIGNED TO,"
    "FILED STATUS,LOCATION,\"Reccomended time and material needing added to WO for correct billing. \","
    "Reason for added time and material."
)


def _csv(rows):
    lines = [HEADERS]
    for number, status, extra in rows:
        lines.append(
            f'{number},Uri Butler,SMR27 - Belfor,05/15/2026,05/21/2026,Chris Coburn,{status},'
            f'"Young Hall:1st Floor,Young Hall 108A-A,drawer",{extra},reason'
        )
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def _user(db, role):
    user = User(username=f"u-{uuid.uuid4().hex[:8]}", password_hash=auth.hash_password("x"), role=role)
    db.add(user)
    db.flush()
    return user


def _num():
    return f"SMR-{uuid.uuid4().hex[:8]}"


def test_smr_import_creates_restores_and_baselines(db):
    owner = _user(db, roles.ROLE_OWNER)
    new_number, old_number = _num(), _num()
    archived = wos.get_or_create_work_order(db, number=old_number, created_by_id=owner.id)
    archived.archived_at = datetime.now(timezone.utc)
    db.flush()

    result = smr_service.import_smr(db, csv_bytes=_csv([(new_number, "Closed", ".5 SL hours"), (old_number, "Closed", "")]), user=owner)

    assert (result.created, result.restored, result.opened, result.skipped, result.baselined) == (1, 1, 0, 0, 2)
    assert result.total == 2
    restored = wos.find_by_number(db, old_number)
    assert restored.archived_at is None
    created = wos.find_by_number(db, new_number)
    for order in (created, restored):
        assert order.smr_imported_at is not None
        assert order.smr_baseline["source_row"]["CREATOR"] == "Uri Butler"
    assert created.smr_baseline["source_row"]["Reccomended time and material needing added to WO for correct billing. "] == ".5 SL hours"
    assert created.location == "Young Hall:1st Floor,Young Hall 108A-A,drawer"
    assert created.service_type == "SMR27 - Belfor"


def test_smr_import_rerun_keeps_baseline_and_edits(db):
    owner = _user(db, roles.ROLE_OWNER)
    number = _num()
    sheet = _csv([(number, "Closed", "")])
    smr_service.import_smr(db, csv_bytes=sheet, user=owner)
    order = wos.find_by_number(db, number)
    baseline = dict(order.smr_baseline)
    imported_at = order.smr_imported_at
    wos.add_work_order_labor(db, order.id, user=owner, technician_id=None, minutes=30)

    result = smr_service.import_smr(db, csv_bytes=sheet, user=owner)

    assert (result.created, result.opened, result.restored, result.baselined) == (0, 1, 0, 0)
    order = wos.find_by_number(db, number)
    assert order.smr_baseline == baseline
    assert order.smr_imported_at == imported_at
    assert [e.minutes for e in order.labor_entries] == [30]


def test_smr_import_canceled_row_leaves_live_row_alone(db):
    owner = _user(db, roles.ROLE_OWNER)
    number = _num()
    live = wos.get_or_create_work_order(db, number=number, created_by_id=owner.id)

    result = smr_service.import_smr(db, csv_bytes=_csv([(number, "Canceled", ""), ("", "Closed", "")]), user=owner)

    assert (result.skipped, result.created, result.opened) == (2, 0, 0)
    db.refresh(live)
    assert live.smr_imported_at is None and live.smr_baseline is None


def test_smr_import_requires_filed_status_header(db):
    owner = _user(db, roles.ROLE_OWNER)
    with pytest.raises(WorkOrderStateError, match="FILED STATUS"):
        smr_service.import_smr(db, csv_bytes=b"WORK ORDER,LOCATION\r\n1,x\r\n", user=owner)


# --- target import (spec 2026-10-23-smr-target-match) ---------------------

BREAKDOWN_HEADERS = "WO#,Unit#,Closed Date,Labor Type,BELFOR HRS,Add HRS,Duplicate HRS,Hours,Labor $,OT Hours,OT $,Total Material Cost,Total L&M,"


def _breakdown(rows):
    # Money cells are quoted: "$1,067.16" carries a comma.
    lines = [BREAKDOWN_HEADERS] + [f'{n},Young Hall 108,05/21/26,SL,,,,{h},$0.00,,$0.00,"{m}",$0.00,' for n, h, m in rows]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def test_import_targets_attaches_last_row_wins(db):
    owner = _user(db, roles.ROLE_OWNER)
    number = _num()
    smr_service.import_smr(db, csv_bytes=_csv([(number, "Closed", "")]), user=owner)

    result = smr_service.import_smr_targets(
        db, csv_bytes=_breakdown([(number, "0.5", "$31.25"), (number, "1.5", "$1,067.16")]), user=owner
    )

    assert (result.total, result.targeted, result.unknown, result.skipped) == (2, 2, 0, 0)
    order = wos.find_by_number(db, number)
    assert order.smr_target["hours"] == "1.5" and order.smr_target["materials_total"] == "1067.16"
    assert order.smr_target["source_row"]["Unit#"] == "Young Hall 108"
    assert order.smr_baseline is not None and "hours" not in order.smr_baseline


def test_import_targets_skips_footer_and_unknown(db):
    owner = _user(db, roles.ROLE_OWNER)
    smr_number, live_number, ghost = _num(), _num(), _num()
    smr_service.import_smr(db, csv_bytes=_csv([(smr_number, "Closed", "")]), user=owner)
    wos.get_or_create_work_order(db, number=live_number, created_by_id=owner.id)  # not SMR
    sheet = _breakdown([(smr_number, "1", "$9.38"), (live_number, "1", "$1.00"), (ghost, "1", "$1.00"), ("", "4455.5", "$149,961.19")])

    result = smr_service.import_smr_targets(db, csv_bytes=sheet, user=owner)

    assert (result.total, result.targeted, result.unknown, result.skipped) == (4, 1, 2, 1)
    assert sorted(result.unknown_numbers) == sorted([live_number, ghost])
    assert wos.find_by_number(db, live_number).smr_target is None
    assert wos.find_by_number(db, ghost) is None


def test_import_targets_requires_breakdown_headers(db):
    owner = _user(db, roles.ROLE_OWNER)
    with pytest.raises(WorkOrderStateError, match="Total Material Cost"):
        smr_service.import_smr_targets(db, csv_bytes=_csv([]), user=owner)


def test_import_targets_rerun_overwrites(db):
    owner = _user(db, roles.ROLE_OWNER)
    number = _num()
    smr_service.import_smr(db, csv_bytes=_csv([(number, "Closed", "")]), user=owner)
    smr_service.import_smr_targets(db, csv_bytes=_breakdown([(number, "1", "$5.00")]), user=owner)
    smr_service.import_smr_targets(db, csv_bytes=_breakdown([(number, "2", "$6.00")]), user=owner)
    assert wos.find_by_number(db, number).smr_target["hours"] == "2"
