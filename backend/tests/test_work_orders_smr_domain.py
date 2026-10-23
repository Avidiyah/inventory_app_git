"""Pure tests for `domain.work_orders_smr` (spec 2026-10-23): sheet parsing,
the snapshot serializer, the edited check, deltas and split labor rounding.
No database: work orders are stand-ins with the attributes the module reads."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace as NS

from app.domain import work_orders as wo
from app.domain import work_orders_smr as smr


HEADERS = [
    "WORK ORDER", "CREATOR", "SERVICE TYPE", "SCHEDULE DATE", "COMPLETION DATE",
    "ASSIGNED TO", "FILED STATUS", "LOCATION",
    "Reccomended time and material needing added to WO for correct billing. ",
    "Reason for added time and material.",
]


def _row(**overrides):
    row = dict(zip(HEADERS, [
        "23281563", "Uri Butler", "SMR27 - Belfor", "05/15/2026", "05/21/2026",
        "Chris Coburn", "Closed", "Young Hall:1st Floor,Young Hall 108A-A,drawer",
        ".5 can WD-40", "WD-40 for treating drawer",
    ]))
    row.update(overrides)
    return row


def test_parse_smr_row_maps_sheet_headers():
    parsed = smr.parse_smr_row(_row())
    assert parsed["number"] == "23281563"
    assert parsed["closed"] is True
    assert parsed["attrs"] == {
        "location": "Young Hall:1st Floor,Young Hall 108A-A,drawer",
        "vendor_assignee": "Chris Coburn",
        "service_type": "SMR27 - Belfor",
        "schedule_date": "05/15/2026",
    }
    assert parsed["source_row"][HEADERS[8]] == ".5 can WD-40"
    assert parsed["source_row"]["CREATOR"] == "Uri Butler"


def test_parse_smr_row_canceled_is_not_closed_and_blank_number_is_none():
    assert smr.parse_smr_row(_row(**{"FILED STATUS": "Canceled"}))["closed"] is False
    assert smr.parse_smr_row(_row(**{"WORK ORDER": "  "}))["number"] is None


def _entry(minutes, technician_id="real", name="Pat Tech"):
    tech = None if technician_id is None else NS(id=technician_id, full_name=name)
    return NS(id=uuid.uuid4(), technician_id=technician_id, technician=tech,
              minutes=minutes, recorded_by=None, created_at=None, session=None)


def test_labor_split_rounds_skilled_separately():
    split = smr.labor_split([_entry(20), _entry(10, None)])
    assert (split.real_minutes, split.skilled_minutes) == (20, 10)
    assert (split.real_billed, split.skilled_billed) == (30, 30)
    assert split.labor_total == wo.labor_charge(30) * 2
    assert split.labor_total != wo.labor_charge(30)  # pooled 30 min would bill half


def _order(lines=(), entries=(), sessions=()):
    return NS(
        id=uuid.uuid4(), number="23281563", status="completed", archived_at=None,
        notes="n", smr_baseline=None, items=list(lines), labor_entries=list(entries),
        labor_sessions=list(sessions),
    )


def _line(qty="2", price="1.50", billable=None, name="Rags"):
    return NS(id=uuid.uuid4(), item_id=uuid.uuid4(), quantity=Decimal(qty),
              billable_quantity=None if billable is None else Decimal(billable),
              item=NS(name=name, barcode="BC1", price=Decimal(price)), created_at=None)


def test_snapshot_is_json_serialisable_and_totals_lines():
    order = _order(lines=[_line(), _line("1", "4.00", "0.5")], entries=[_entry(45), _entry(10, None)])
    snap = smr.snapshot(order, taken_at=datetime(2026, 10, 23, tzinfo=timezone.utc), source_row={"CREATOR": "x"})
    json.dumps(snap)
    assert snap["totals"] == {
        "materials_total": "5.00", "real_minutes": 45, "skilled_minutes": 10,
        "real_billed_minutes": 60, "skilled_billed_minutes": 30,
        "labor_total": str(wo.labor_charge(60) + wo.labor_charge(30)),
        "total": str(Decimal("5.00") + wo.labor_charge(60) + wo.labor_charge(30)),
    }
    assert snap["labor_entries"][1]["technician"] == smr.SKILLED_TECHNICIAN_LABEL
    assert snap["material_lines"][0]["line_total"] == "3.00"
    assert snap["source_row"] == {"CREATOR": "x"}


def test_is_edited_false_when_unchanged_and_without_baseline():
    order = _order(lines=[_line()], entries=[_entry(30)])
    assert smr.is_edited(order) is False
    order.smr_baseline = smr.snapshot(order, taken_at=datetime.now(timezone.utc), source_row=None)
    assert smr.is_edited(order) is False


def test_is_edited_detects_removed_line():
    order = _order(lines=[_line(), _line("1", "4.00")])
    order.smr_baseline = smr.snapshot(order, taken_at=datetime.now(timezone.utc), source_row=None)
    order.items.pop()
    assert smr.is_edited(order) is True


def test_deltas_subtract_baseline():
    before = _order(lines=[_line()], entries=[_entry(30)])
    base = smr.snapshot(before, taken_at=datetime.now(timezone.utc), source_row=None)
    after = _order(lines=[], entries=[_entry(30), _entry(15, None)])
    cur = smr.snapshot(after, taken_at=datetime.now(timezone.utc), source_row=None)
    d = smr.deltas(base, cur)
    assert d["materials_total"] == Decimal("-3.00")
    assert d["real_minutes"] == 0 and d["skilled_minutes"] == 15
    assert d["labor_total"] == wo.labor_charge(15)
    assert d["material_lines"] == -1
    assert d["total"] == wo.labor_charge(15) - Decimal("3.00")
