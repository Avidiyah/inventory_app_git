"""The weekly closed report as an Excel workbook.

Layer: services. A pure function of `HubReportResponse` -- no queries, no
clock -- so the file and the screen render the same record (W4). Styling
lives in `_xlsx_theme.py`; this module is sheet composition only.

Spec: docs/superpowers/specs/2026-09-13-weekly-closed-report-design.md §6

One tab per service type label, alphabetical (W8), followed by a New Work
Orders tab (W14). Each tab uses community blocks in
`ALL_COMMUNITY_FILTERS` order, primary community only (W9), and six raw
vendor-text columns (W10). No Excel Table objects: a tab holds several
blocks, and a Table cannot span a heading row.
"""

from __future__ import annotations

import io
import re
from itertools import groupby

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from app.domain import labor_day
from app.domain import work_orders as wo
from app.schemas.hub import HubReportResponse, HubReportRow
from app.services import _xlsx_theme as theme
from app.services.work_order_report import new_work_order_sort_key, row_sort_key

XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

HEADERS: tuple[str, ...] = (
    "WORK ORDER",
    "ASSIGNED TO",
    "LOCATION",
    "SERVICE TYPE",
    "SCHEDULE DATE",
    "PRIORITY",
)
WIDTHS: dict[str, int] = {"A": 14, "B": 22, "C": 34, "D": 18, "E": 14, "F": 10}

EMPTY_SHEET = "Report"
EMPTY_TEXT = "No work orders closed this week."
NEW_WORK_ORDERS_SHEET = "New Work Orders"
EMPTY_NEW_WORK_ORDERS_TEXT = "No new work orders this week."

# Excel forbids these in a sheet name and caps it at 31 characters.
_FORBIDDEN = re.compile(r"[:\\/?*\[\]]")
_MAX_NAME = 31

FIRST_BLOCK_ROW = 5


def report_xlsx(payload: HubReportResponse) -> bytes:
    workbook = Workbook()
    first = workbook.active
    # Reserve the final sheet's name before sanitising service-type labels.
    taken: set[str] = {NEW_WORK_ORDERS_SHEET}
    # Sorted here as well as in the service: a stored payload is trusted for
    # its rows, never for their order (W8, W9).
    ordered = sorted(payload.rows, key=row_sort_key)
    groups = [
        (label, list(rows))
        for label, rows in groupby(ordered, key=lambda row: row.service_type_label)
    ]
    if not groups:
        first.title = EMPTY_SHEET
        _title_block(first, EMPTY_SHEET, payload)
        theme.empty_state(first, FIRST_BLOCK_ROW, EMPTY_TEXT)
    for index, (label, rows) in enumerate(groups):
        name = sheet_name(label, taken)
        taken.add(name)
        sheet = first if index == 0 else workbook.create_sheet()
        sheet.title = name
        _service_type_sheet(sheet, payload, label, rows)

    new_work_orders_sheet = workbook.create_sheet(NEW_WORK_ORDERS_SHEET)
    _new_work_orders_sheet(new_work_orders_sheet, payload)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def report_xlsx_filename(payload: HubReportResponse) -> str:
    """Named for the Monday of the week it covers, not the moment of export
    (the timesheet convention, user-hub-design.md D14)."""
    return f"wo-report_{payload.week_start.isoformat()}.xlsx"


def sheet_name(label: str, taken: set[str]) -> str:
    """`label` made legal for Excel: forbidden characters become spaces, the
    result is cut to 31, and a collision with `taken` gets a ` (2)`, ` (3)`
    suffix so no service type silently overwrites another's tab."""
    base = _FORBIDDEN.sub(" ", label).strip()[:_MAX_NAME].strip() or EMPTY_SHEET
    name, attempt = base, 1
    while name in taken:
        attempt += 1
        suffix = f" ({attempt})"
        name = f"{base[: _MAX_NAME - len(suffix)].rstrip()}{suffix}"
    return name


def _status_line(payload: HubReportResponse) -> str:
    if payload.status == "completed" and payload.frozen_at is not None:
        stamp = payload.frozen_at.astimezone(labor_day.CENTRAL)
        return f"Completed · frozen {stamp:%Y-%m-%d %H:%M} Central"
    stamp = payload.generated_at.astimezone(labor_day.CENTRAL)
    label = "Completed" if payload.status == "completed" else "In progress"
    return f"{label} · generated {stamp:%Y-%m-%d %H:%M} Central"


def _title_block(sheet: Worksheet, title: str, payload: HubReportResponse) -> None:
    theme.setup_sheet(sheet, tab_color=theme.MUTED, freeze=None)
    theme.set_widths(sheet, WIDTHS)
    theme.title_block(
        sheet,
        title,
        [
            f"Closed {payload.week_start.isoformat()} – {payload.week_end.isoformat()}"
            f" · {payload.count:,} work orders",
            _status_line(payload),
        ],
    )


def _cells(row: HubReportRow) -> list:
    return [
        row.number,
        row.assigned_to,
        row.location,
        row.service_type,
        row.schedule_date,
        row.priority,
    ]


def _service_type_sheet(
    sheet: Worksheet, payload: HubReportResponse, label: str, rows: list[HubReportRow]
) -> None:
    _title_block(sheet, label, payload)
    _community_blocks(sheet, rows)


def _new_work_orders_sheet(sheet: Worksheet, payload: HubReportResponse) -> None:
    theme.setup_sheet(sheet, tab_color=theme.MUTED, freeze=None)
    theme.set_widths(sheet, WIDTHS)
    theme.title_block(
        sheet,
        NEW_WORK_ORDERS_SHEET,
        [
            f"New work orders {payload.week_start.isoformat()} – "
            f"{payload.week_end.isoformat()} · {payload.new_work_order_count:,} total",
            _status_line(payload),
        ],
    )
    rows = sorted(payload.new_work_order_rows, key=new_work_order_sort_key)
    if not rows:
        theme.empty_state(sheet, FIRST_BLOCK_ROW, EMPTY_NEW_WORK_ORDERS_TEXT)
        return
    _community_blocks(sheet, rows)


def _community_blocks(sheet: Worksheet, rows: list[HubReportRow]) -> None:
    cursor = FIRST_BLOCK_ROW
    for key in wo.ALL_COMMUNITY_FILTERS:
        block = [row for row in rows if row.community == key]
        if not block:
            continue
        theme.section(sheet, cursor, wo.COMMUNITY_LABELS[key], span=len(HEADERS))
        theme.header_row(sheet, cursor + 1, HEADERS)
        last = theme.write_rows(sheet, cursor + 2, [_cells(row) for row in block])
        cursor = last + 2  # one blank row between blocks
