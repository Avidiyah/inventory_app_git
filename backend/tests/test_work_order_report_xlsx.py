"""The weekly closed report as an Excel workbook: one tab per service type,
community blocks inside, six raw columns.

Spec: docs/superpowers/specs/2026-09-13-weekly-closed-report-design.md §6.

Pure: payloads are built directly, no database.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, datetime, timezone

import openpyxl

from app.domain import labor_day
from app.schemas.hub import HubReportResponse, HubReportRow
from app.services import _xlsx_theme as theme
from app.services import work_order_report_xlsx as xlsx

WEEK_START = date(2026, 9, 7)
WEEK_END = date(2026, 9, 13)
GENERATED = datetime(2026, 9, 14, 5, 12, tzinfo=timezone.utc)  # 00:12 Central


def _row(**overrides) -> HubReportRow:
    fields = dict(
        work_order_id=uuid.uuid4(),
        number="7001",
        assigned_to="Belfor Dispatch",
        location="Scholars 12-304",
        service_type="Maintenance",
        service_type_label="Maintenance",
        community="scholars",
        schedule_date="7/21/2026",
        priority="Normal",
        archived_at=GENERATED,
    )
    fields.update(overrides)
    return HubReportRow(**fields)


def _payload(rows, *, status="completed", frozen=True, new_work_orders=()) -> HubReportResponse:
    return HubReportResponse(
        week_start=WEEK_START,
        week_end=WEEK_END,
        status=status,
        generated_at=GENERATED,
        frozen_at=GENERATED if frozen else None,
        count=len(rows),
        rows=rows,
        new_work_order_count=len(new_work_orders),
        new_work_order_rows=list(new_work_orders),
    )


def _workbook(payload):
    return openpyxl.load_workbook(io.BytesIO(xlsx.report_xlsx(payload)))


def _values(sheet, row):
    return tuple(cell.value for cell in sheet[row])[:6]


def test_one_tab_per_service_type_alphabetical():
    payload = _payload([
        _row(service_type_label="Window Repair"),
        _row(service_type_label="Maintenance"),
        _row(service_type_label="SMR27 - Belfor"),
    ])

    assert _workbook(payload).sheetnames == [
        "Maintenance", "SMR27 - Belfor", "Window Repair", xlsx.NEW_WORK_ORDERS_SHEET,
    ]


def test_sheet_name_strips_forbidden_characters_caps_length_and_dedupes():
    assert xlsx.sheet_name("A/B: C?", set()) == "A B  C"
    assert len(xlsx.sheet_name("x" * 40, set())) == 31
    assert xlsx.sheet_name("Maintenance", {"Maintenance"}) == "Maintenance (2)"


def test_a_tab_has_title_block_then_community_blocks_in_fixed_order():
    payload = _payload([
        _row(number="7002", community="academics", location="Library"),
        _row(number="7001", community="scholars"),
    ])

    sheet = _workbook(payload)["Maintenance"]
    generated = GENERATED.astimezone(labor_day.CENTRAL).strftime("%Y-%m-%d %H:%M")

    assert sheet["A1"].value == "Maintenance"
    assert sheet["A2"].value == "Closed 2026-09-07 – 2026-09-13 · 2 work orders"
    assert sheet["A3"].value == f"Completed · frozen {generated} Central"
    assert sheet["A5"].value == "Scholars"
    assert _values(sheet, 6) == xlsx.HEADERS
    assert _values(sheet, 7) == (
        "7001", "Belfor Dispatch", "Scholars 12-304", "Maintenance", "7/21/2026", "Normal",
    )
    assert sheet["A8"].value is None  # the blank row between blocks
    assert sheet["A9"].value == "Academics"
    assert _values(sheet, 10) == xlsx.HEADERS
    assert sheet["A11"].value == "7002"
    headings = [sheet.cell(row=r, column=1).value for r in range(5, 12)]
    for absent in ("Centennial", "Commons", "Young Hall"):
        assert absent not in headings


def test_in_progress_status_line():
    sheet = _workbook(_payload([_row()], status="in_progress", frozen=False))["Maintenance"]
    generated = GENERATED.astimezone(labor_day.CENTRAL).strftime("%Y-%m-%d %H:%M")

    assert sheet["A3"].value == f"In progress · generated {generated} Central"


def test_cells_are_raw_strings_and_none_is_empty():
    payload = _payload([_row(schedule_date="7/21/2026", priority=None, assigned_to=None)])

    sheet = _workbook(payload)["Maintenance"]

    assert sheet["E7"].value == "7/21/2026"
    assert isinstance(sheet["E7"].value, str)
    assert sheet["B7"].value is None
    assert sheet["F7"].value is None


def test_empty_closed_week_keeps_report_and_new_work_orders_sheets():
    workbook = _workbook(_payload([]))

    assert workbook.sheetnames == [xlsx.EMPTY_SHEET, xlsx.NEW_WORK_ORDERS_SHEET]
    assert workbook[xlsx.EMPTY_SHEET]["A5"].value == xlsx.EMPTY_TEXT


def test_house_style_widths_gridlines_and_filename():
    payload = _payload([_row()])
    sheet = _workbook(payload)["Maintenance"]

    assert {c: sheet.column_dimensions[c].width for c in xlsx.WIDTHS} == xlsx.WIDTHS
    assert sheet.sheet_view.showGridLines is False
    assert sheet.freeze_panes is None
    assert sheet.sheet_properties.tabColor.rgb.endswith(theme.MUTED)
    assert xlsx.report_xlsx_filename(payload) == "wo-report_2026-09-07.xlsx"


# --- the New Work Orders tab (W14) --------------------------------------------


def test_new_work_orders_tab_is_last_with_community_blocks_by_number():
    payload = _payload(
        [_row()],
        new_work_orders=[
            _row(number="7005", community="academics", location="Library", archived_at=None),
            _row(number="7004", archived_at=None),
        ],
    )

    workbook = _workbook(payload)
    sheet = workbook[xlsx.NEW_WORK_ORDERS_SHEET]
    generated = GENERATED.astimezone(labor_day.CENTRAL).strftime("%Y-%m-%d %H:%M")

    assert workbook.sheetnames == ["Maintenance", "New Work Orders"]
    assert sheet["A1"].value == "New Work Orders"
    assert sheet["A2"].value == "New work orders 2026-09-07 – 2026-09-13 · 2 total"
    assert sheet["A3"].value == f"Completed · frozen {generated} Central"
    assert sheet["A5"].value == "Scholars"
    assert _values(sheet, 6) == xlsx.HEADERS
    assert _values(sheet, 7) == (
        "7004", "Belfor Dispatch", "Scholars 12-304", "Maintenance", "7/21/2026", "Normal",
    )
    assert sheet["A8"].value is None
    assert sheet["A9"].value == "Academics"
    assert sheet["A11"].value == "7005"
    assert sheet.sheet_view.showGridLines is False
    assert {c: sheet.column_dimensions[c].width for c in xlsx.WIDTHS} == xlsx.WIDTHS


def test_new_work_orders_tab_with_no_new_rows_says_so():
    sheet = _workbook(_payload([_row()]))[xlsx.NEW_WORK_ORDERS_SHEET]

    assert sheet["A2"].value == "New work orders 2026-09-07 – 2026-09-13 · 0 total"
    assert sheet["A5"].value == xlsx.EMPTY_NEW_WORK_ORDERS_TEXT


def test_a_service_type_named_like_the_new_work_orders_tab_gets_the_suffix():
    payload = _payload([_row(service_type_label="New Work Orders")])

    assert _workbook(payload).sheetnames == ["New Work Orders (2)", "New Work Orders"]
