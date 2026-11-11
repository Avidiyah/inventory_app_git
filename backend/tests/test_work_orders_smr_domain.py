"""Pure tests for `domain.work_orders_smr` (spec 2026-10-23): sheet parsing,
the snapshot serializer, the edited check, deltas and split labor rounding.
No database: work orders are stand-ins with the attributes the module reads."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from app.domain import work_orders as wo
from app.domain.errors import WorkOrderStateError
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


# --- target match (spec 2026-10-23-smr-target-match) ----------------------

BREAKDOWN = ["WO#", "Unit#", "Closed Date", "Labor Type", "BELFOR HRS", "Add HRS",
             "Duplicate HRS", "Hours", "Labor $", "OT Hours", "OT $", "Total Material Cost", "Total L&M", ""]


def _brow(**o):
    row = dict(zip(BREAKDOWN, ["23281585", "Young Hall 108", "05/21/26", "SL", "", "", "", "1", "$62.50", "", "$0.00", "$9.38", "$71.88", ""]))
    row.update(o)
    return row


def test_parse_target_row_reads_hours_and_money():
    p = smr.parse_target_row(_brow(**{"Labor $": "$1,656.25", "Hours": "26.5"}))
    assert (p["number"], p["hours"], p["labor_total"], p["materials_total"], p["total"]) == (
        "23281585", Decimal("26.5"), Decimal("1656.25"), Decimal("9.38"), Decimal("71.88"))
    assert p["source_row"]["Unit#"] == "Young Hall 108"


def test_parse_target_row_blank_number_is_none_and_blank_money_is_zero():
    assert smr.parse_target_row(_brow(**{"WO#": ""})) is None
    parsed = smr.parse_target_row(_brow(**{"Total Material Cost": "", "Hours": ""}))
    assert parsed["materials_total"] == Decimal(0) and parsed["hours"] == Decimal(0)


def test_parse_target_row_rejects_non_numeric():
    with pytest.raises(WorkOrderStateError, match="23281585: Hours"):
        smr.parse_target_row(_brow(Hours="abc"))


def test_target_record_is_json_safe():
    rec = smr.target_record(smr.parse_target_row(_brow()), imported_at=datetime(2026, 10, 23, tzinfo=timezone.utc))
    assert rec["hours"] == "1" and rec["materials_total"] == "9.38" and rec["imported_at"].startswith("2026-10-23")
    assert rec["source_row"]["Unit#"] == "Young Hall 108"
    json.dumps(rec)


def _target(hours="2", material="67.16"):
    return {"hours": hours, "labor_total": "0.00", "materials_total": material, "total": "0.00", "source_row": {}}


def test_target_gap_short_order():
    g = smr.target_gap(_target(), billed_minutes=60, materials_total=Decimal("40.00"))
    assert g["current_hours"] == Decimal(1) and g["current_materials_total"] == Decimal("46.00")
    assert g["remaining_hours"] == Decimal(1) and g["remaining_materials_total"] == Decimal("21.16")
    assert g["gap_hours"] == Decimal(-1) and g["matched"] is False
    assert g["hours"] == Decimal(2) and g["materials_total"] == Decimal("67.16")


def test_target_gap_within_band_is_matched():
    g = smr.target_gap(_target(), billed_minutes=90, materials_total=Decimal("50.00"))  # 57.50 marked, 9.66 short
    assert g["matched"] is True and g["remaining_hours"] == Decimal("0.5")


def test_target_gap_just_outside_band_is_short():
    assert smr.target_gap(_target(), billed_minutes=60, materials_total=Decimal("58.40"))["matched"] is False
    assert smr.target_gap(_target(), billed_minutes=120, materials_total=Decimal("49.00"))["matched"] is False  # 56.35, 10.81 short


def test_target_gap_overshoot_is_matched():
    g = smr.target_gap(_target(), billed_minutes=240, materials_total=Decimal("100.00"))
    assert g["matched"] is True and g["remaining_hours"] == 0 and g["remaining_materials_total"] == 0
    assert g["gap_hours"] == Decimal(2)


def test_target_gap_zero_target_is_matched():
    assert smr.target_gap(_target("0", "0.00"), billed_minutes=0, materials_total=Decimal(0))["matched"] is True


def test_target_gap_none_without_target():
    assert smr.target_gap(None, billed_minutes=30, materials_total=Decimal(1)) is None


# --- paper-correction lines (spec 2026-11-04) -----------------------------

from datetime import date  # noqa: E402

from app.domain import work_orders_smr_lines as lines_rules  # noqa: E402


def _cline(**overrides):
    fields = dict(work_date=date(2026, 6, 20), date_basis="paper", vendor="Belfor", worker=None, headcount=1,
                  hours_each=Decimal("1.5"), kind="field", reason_code="accurate", status="charged",
                  exclusion_ground=None)
    fields.update(overrides)
    return NS(**fields)


def test_lines_charge_sums_charged_lines_at_the_rate_without_rounding():
    charge = lines_rules.lines_charge([
        _cline(headcount=2, hours_each=Decimal("3.0")),
        _cline(hours_each=Decimal("0.5")),
        _cline(hours_each=Decimal("-1.0")),
        _cline(status="excluded", exclusion_ground="undated", hours_each=Decimal("7.0")),
    ])
    assert (charge.charged_hours, charge.excluded_hours, charge.count) == (Decimal("5.5"), Decimal("7.0"), 4)
    assert charge.labor_total == Decimal("5.5") * wo.LABOR_RATE == Decimal("343.75")


def test_general_labor_kinds_charge_at_43_50_and_everything_else_at_62_50():
    # User 2026-11-11: audit, staging, material preparation and clean-up are
    # GL; field, assessment and a leftover mixed line stay ST.
    charge = lines_rules.lines_charge([
        _cline(hours_each=Decimal("2.0")),
        _cline(kind="assessment", hours_each=Decimal("0.5")),
        _cline(kind="audit, staging", hours_each=Decimal("0.5")),
        _cline(kind="audit", hours_each=Decimal("0.5")),
        _cline(kind="staging", hours_each=Decimal("0.5")),
        _cline(kind="material preparation", headcount=2, hours_each=Decimal("1.5")),
        _cline(kind="clean-up", hours_each=Decimal("0.5")),
    ])
    assert charge.charged_hours == Decimal("7.5")
    assert charge.labor_total == Decimal("3.0") * Decimal("62.50") + Decimal("4.5") * Decimal("43.50") == Decimal("383.25")


def test_a_new_line_carries_one_kind():
    lines_rules.require_one_kind("audit")
    for bad in ("assessment, audit", "audit, staging", ""):
        with pytest.raises(WorkOrderStateError):
            lines_rules.require_one_kind(bad)


def test_labor_figures_without_lines_is_the_legacy_split():
    figures = smr.labor_figures([_entry(20), _entry(10, None)], [])
    split = smr.labor_split([_entry(20), _entry(10, None)])
    assert (figures.labor_total, figures.billed_minutes, figures.legacy_minutes) == (split.labor_total, 60, 0)
    assert figures.lines is None


def test_labor_figures_with_lines_charges_lines_only_and_reports_legacy_minutes():
    figures = smr.labor_figures([_entry(20), _entry(10, None)], [_cline(hours_each=Decimal("2.5"))])
    assert figures.labor_total == Decimal("2.5") * wo.LABOR_RATE
    assert figures.billed_minutes == 150
    assert figures.legacy_minutes == 30
    assert figures.lines.charged_hours == Decimal("2.5")


def test_snapshot_labor_follows_the_lines_and_keeps_the_legacy_minute_keys():
    order = _order(entries=[_entry(45)])
    order.smr_imported_at = datetime.now(timezone.utc)
    order.smr_lines = []
    base = smr.snapshot(order, taken_at=datetime.now(timezone.utc), source_row=None)
    order.smr_baseline = base
    assert smr.is_edited(order) is False

    order.smr_lines = [_cline(hours_each=Decimal("4.0"))]
    cur = smr.snapshot(order, taken_at=datetime.now(timezone.utc), source_row=None)
    assert cur["totals"]["labor_total"] == "250.00"
    assert cur["totals"]["real_minutes"] == 45 and cur["totals"]["real_billed_minutes"] == 60
    assert set(cur["totals"]) == set(base["totals"])
    assert smr.is_edited(order) is True
    assert smr.deltas(base, cur)["labor_total"] == Decimal("250.00") - wo.labor_charge(45)


def test_correction_lines_are_only_read_on_smr_orders():
    live = _order()
    live.smr_lines = [_cline()]
    assert smr.correction_lines(live) == ()
    assert smr.labor_figures([], smr.correction_lines(live)).lines is None


def test_week_of_counts_mon_sun_weeks_from_may_25():
    assert lines_rules.week_of(date(2026, 5, 25)) == 1 and lines_rules.week_of(date(2026, 5, 31)) == 1
    assert lines_rules.week_of(date(2026, 6, 1)) == 2
    assert lines_rules.week_of(date(2026, 7, 6)) == 7 and lines_rules.week_of(date(2026, 7, 12)) == 7
    assert lines_rules.week_of(date(2026, 5, 24)) == 0 and lines_rules.week_of(date(2026, 7, 13)) == 8
    assert [lines_rules.week_label(w) for w in (0, 3, 8, None)] == ["Before W1", "Week 3", "After W7", ""]
    assert lines_rules.week_for(None, lines_rules.WEEK1_PLACEMENT_BASIS) == 1
    assert lines_rules.week_for(None, "paper") is None
    assert lines_rules.week_for(date(2026, 6, 10), "paper") == 3


def _state(**overrides):
    fields = dict(status="charged", work_date=date(2026, 6, 20), date_basis="paper", exclusion_ground=None,
                  headcount=1, hours_each=Decimal("1.5"), vendor="Belfor", kind="field", reason_code="accurate")
    fields.update(overrides)
    return fields


def test_status_rules_in_words():
    lines_rules.validate_line_state(**_state())
    lines_rules.validate_line_state(**_state(work_date=None, date_basis=lines_rules.WEEK1_PLACEMENT_BASIS))
    lines_rules.validate_line_state(**_state(status="excluded", exclusion_ground="vendor unknown"))
    lines_rules.validate_line_state(**_state(status="excluded"))  # no ground needed
    lines_rules.validate_line_state(**_state(kind="assessment, audit", hours_each=Decimal("-0.5")))
    for bad in (
        dict(work_date=None), dict(status="pending"), dict(headcount=0),
        dict(hours_each=Decimal("1.3")), dict(vendor="Acme"), dict(kind="assessment, lunch"),
        dict(reason_code="vibes"), dict(exclusion_ground="removed"), dict(date_basis="guess"),
        dict(status="excluded", exclusion_ground="because"),
    ):
        with pytest.raises(WorkOrderStateError):
            lines_rules.validate_line_state(**_state(**bad))


def test_dating_an_undated_line_charges_it_and_nothing_else_moves():
    assert lines_rules.apply_date("excluded", "undated", date(2026, 6, 1)) == ("charged", None)
    assert lines_rules.apply_date("excluded", "undated", None) == ("excluded", "undated")
    assert lines_rules.apply_date("excluded", "note only", date(2026, 6, 1)) == ("excluded", "note only")
    assert lines_rules.apply_date("charged", None, date(2026, 6, 1)) == ("charged", None)


def _reading(hours="6.0", work_date=date(2026, 6, 20)):
    return {"reading_id": "R1", "wo": "23281563", "printing_no": 1, "work_date": work_date,
            "hours_as_read": None if hours is None else Decimal(hours)}


def _tline(hours="3.0", headcount=1, status="charged", ground=None, work_date=date(2026, 6, 20)):
    return {"status": status, "exclusion_ground": ground, "work_date": work_date,
            "headcount": headcount, "hours_each": Decimal(hours)}


def test_tie_passes_exactly_and_within_half_an_hour():
    assert lines_rules.check_tie(_reading("6.0"), [_tline("3.0", 2)]) is None
    assert lines_rules.check_tie(_reading("6.5"), [_tline("3.0", 2)]) is None
    assert lines_rules.check_tie(_reading("5.5"), [_tline("3.0", 2)]) is None
    assert lines_rules.check_tie(_reading(None), [_tline("99.0")]) is None


def test_tie_counts_undated_before_and_after_grounds_but_not_the_rest():
    counted = [_tline("2.0", ground="undated", status="excluded"),
               _tline("2.0", ground="before Week 1", status="excluded"),
               _tline("2.0", ground="after 07/12 (no invoices)", status="excluded"),
               # Inside the paper's figure, dropped by the Week Reports (2026-11-06).
               _tline("2.0", ground="read, not charged (weekly reports)", status="excluded")]
    skipped = [_tline("10.0", ground="awaiting invoice (GC, Week 7)", status="excluded"),
               _tline("10.0", ground="reprint (no hours added)", status="excluded"),
               _tline("10.0", ground="read, not charged (user)", status="excluded"),
               _tline("10.0", ground="admin, never charged", status="excluded"),
               _tline("10.0", ground="note only", status="excluded")]
    assert lines_rules.tie_hours(_reading(), counted + skipped) == Decimal("8.0")
    assert lines_rules.check_tie(_reading("8.0"), counted + skipped) is None
    assert "read, not charged (weekly reports)" in lines_rules.GROUNDS


def test_tie_leaves_out_a_line_the_note_dated_into_another_week():
    other_week = _tline("4.0", work_date=date(2026, 6, 6))
    assert lines_rules.check_tie(_reading("3.0"), [_tline("3.0"), other_week]) is None
    # A reading with no date has no week, so the exception does not apply.
    failure = lines_rules.check_tie(_reading("3.0", work_date=None), [_tline("3.0"), other_week])
    assert failure is not None and failure.found == Decimal("7.0")


def test_tie_failure_names_the_reading():
    failure = lines_rules.check_tie(_reading("6.0"), [_tline("2.0", 2)])
    assert (failure.reading_id, failure.wo, failure.printing_no) == ("R1", "23281563", 1)
    assert (failure.expected, failure.found) == (Decimal("6.0"), Decimal("4.0"))
    assert str(failure) == "Reading R1 (WO 23281563, printing 1): lines total 4.0 h, paper read 6.0 h."


def test_parse_rows_accept_the_draft_columns_and_name_bad_cells():
    reading = lines_rules.parse_reading_row({
        "reading_id": "R7", "wo": " 23281563 ", "printing_no": "2", "work_date": "06/20/2026",
        "hours_as_read": "3.5", "raw_note": " note ", "reviewer": "JM", "csv_row": "212", "extra": "ignored",
    })
    assert (reading["wo"], reading["printing_no"], reading["work_date"]) == ("23281563", 2, date(2026, 6, 20))
    assert (reading["hours_as_read"], reading["raw_note"], reading["csv_row"]) == (Decimal("3.5"), "note", "212")

    line = lines_rules.parse_line_row({
        "line_id": "L9", "reading_id": "R7", "wo": "23281563", "work_date": "2026-06-20", "date_basis": "",
        "week": "4", "vendor": "XXL Construction", "worker": "Trinton Smith", "alias_on_paper": "Trint",
        "headcount": "2", "hours_each": "1.5", "kind": " audit ", "status": "Charged",
        "exclusion_ground": "", "reason_code": "crew_as_one", "note": "crew as one", "surprise": "x",
    })
    assert line["date_basis"] == "paper" and line["week"] == 4 and line["status"] == "charged"
    assert line["kind"] == "audit" and line["headcount"] == 2 and line["hours_each"] == Decimal("1.5")

    with pytest.raises(WorkOrderStateError, match="Line L9b.*one kind"):  # user 2026-11-11
        lines_rules.parse_line_row({
            "line_id": "L9b", "reading_id": "R7", "wo": "23281563", "work_date": "2026-06-20", "vendor": "Belfor",
            "headcount": "1", "hours_each": "1.0", "kind": "assessment,audit", "status": "charged",
            "exclusion_ground": "", "reason_code": "as_read",
        })

    placement = lines_rules.parse_line_row({
        "line_id": "L10", "reading_id": "R7", "wo": "23281563", "work_date": "", "vendor": "Belfor",
        "worker": "", "headcount": "3", "hours_each": "2", "kind": "field", "status": "charged",
        "exclusion_ground": "", "reason_code": "accurate", "date_basis": lines_rules.WEEK1_PLACEMENT_BASIS,
    })
    assert placement["work_date"] is None and placement["week"] == 1

    with pytest.raises(WorkOrderStateError, match="Line L11.*work date"):
        lines_rules.parse_line_row({
            "line_id": "L11", "reading_id": "R7", "wo": "23281563", "work_date": "", "vendor": "Belfor",
            "worker": "", "headcount": "1", "hours_each": "2", "kind": "field", "status": "charged",
            "exclusion_ground": "", "reason_code": "accurate",
        })
    with pytest.raises(WorkOrderStateError, match="Reading R8.*not a date"):
        lines_rules.parse_reading_row({"reading_id": "R8", "wo": "1", "printing_no": "1", "work_date": "June",
                                       "hours_as_read": "", "raw_note": ""})


def test_a_blank_reason_code_is_taken_as_read():
    # User 2026-11-06: paper_lines.csv carries no code on most lines; the
    # import fills `as_read` rather than refusing or storing a blank.
    line = lines_rules.parse_line_row({
        "line_id": "L12", "reading_id": "R7", "wo": "23281563", "work_date": "2026-06-20", "vendor": "Belfor",
        "worker": "", "headcount": "1", "hours_each": "2", "kind": "field", "status": "charged",
        "exclusion_ground": "", "reason_code": "  ",
    })
    assert line["reason_code"] == lines_rules.REASON_AS_READ == "as_read"
    assert lines_rules.REASON_AS_READ in lines_rules.REASON_CODES


def test_a_week_placement_charges_with_its_week_and_no_date():
    # User 2026-11-06: decision 13 generalised to weeks 2-7 for the hours the
    # weekly reports placed (the 0.5 h clean-up, the no-name lines). The week
    # is read from the CSV for this basis only; a date always wins.
    basis = lines_rules.WEEK_PLACEMENT_BASIS
    assert basis in lines_rules.DATE_BASES and basis in lines_rules.PLACEMENT_BASES
    assert lines_rules.week_for(None, basis, 3) == 3
    assert lines_rules.week_for(date(2026, 6, 20), basis, 3) == 4
    assert lines_rules.week_for(None, "paper", 3) is None
    lines_rules.validate_line_state(**_state(work_date=None, date_basis=basis, week=3))
    with pytest.raises(WorkOrderStateError, match="week"):
        lines_rules.validate_line_state(**_state(work_date=None, date_basis=basis))

    row = {"line_id": "L13", "reading_id": "R9", "wo": "23281563", "work_date": "", "date_basis": basis,
           "vendor": "Belfor", "worker": "", "headcount": "1", "hours_each": "0.5", "kind": "field",
           "status": "charged", "exclusion_ground": "", "reason_code": "", "week": "3"}
    assert lines_rules.parse_line_row(row)["week"] == 3
    for bad in ("", "8", "two"):
        with pytest.raises(WorkOrderStateError, match="Line L13.*week"):
            lines_rules.parse_line_row({**row, "week": bad})
    with pytest.raises(WorkOrderStateError, match="Line L13.*work date"):
        lines_rules.parse_line_row({**row, "date_basis": "paper"})
    # Outside the placement basis the column is not read at all, whatever it holds.
    ignored = lines_rules.parse_line_row({**row, "date_basis": "paper", "status": "excluded",
                                          "exclusion_ground": "before Week 1", "week": "Before W1"})
    assert ignored["week"] is None


def test_a_weekly_reports_hold_out_lands_charged():
    # User 2026-11-06: paper hours bill where read, so the load needs no
    # second pass; the retired ground maps to charged at parse time.
    line = lines_rules.parse_line_row({
        "line_id": "L13", "reading_id": "R7", "wo": "23281563", "work_date": "2026-06-07", "vendor": "XXL Construction",
        "worker": "Chris Bryan", "headcount": "1", "hours_each": "4", "kind": "field", "status": "excluded",
        "exclusion_ground": lines_rules.GROUND_NOT_CHARGED_REPORTS, "reason_code": "",
    })
    assert (line["status"], line["exclusion_ground"]) == ("charged", None)
