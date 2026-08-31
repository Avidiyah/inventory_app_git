"""The Admin daily report as an Excel workbook.

Layer: services. The third renderer of `work_order_report.daily_report`'s
payload, beside the JSON route and `report_csv` -- a pure function of that
payload, no queries and no clock, so the file and the screen cannot disagree
(parent spec R9 / X3, redesign E13). Styling lives in `_xlsx_theme.py` (E12);
this module is sheet composition only.

Spec: docs/superpowers/specs/2026-08-30-hub-report-xlsx-redesign-design.md

Sheet order is the reading order: `Report`, one sheet per community, `Work
Orders`, then the machine sheets -- hidden `Chart Data`, and `Data` last.

Three things about this module are load-bearing:

**openpyxl discards charts across a load/save cycle.** So there is no
committed `.xlsx` template -- the workbook is built in code, and the charts
cannot be read back in tests: `tests/test_work_order_report_xlsx.py` asserts
them over the saved bytes with `zipfile`.

**Every chart reads the hidden `Chart Data` sheet (E7)**, one labelled block
per chart written by cursor, with `visible_cells_only = False` so Excel plots
it. The designed sheets carry the same numbers as styled tables, from the
same payload -- never as chart sources.

**`Data` is `report_csv`, cell for cell (E10 / X5)**, money-as-text included,
so save-as-CSV from Excel still round-trips through `parse_import_row`.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from openpyxl import Workbook
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.worksheet.worksheet import Worksheet

from app.domain import labor_day
from app.domain import work_orders as wo
from app.services import _xlsx_theme as theme
from app.services.work_order_report import (
    CLOSING_STATUSES,
    CSV_SECTION_HEADER,
    SECTION_ORDER,
    STATUS_LABELS,
    DailyReport,
    ReportRow,
)
from app.services.work_order_report_buckets import (
    BUCKET_CLOSED,
    BUCKET_KEYS,
    BUCKET_LABELS,
    CommunityDistribution,
    communities_of,
    grid_of,
    primary_community,
    row_bucket,
)

XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

CHART_DATA_SHEET = "Chart Data"

# Physical order. Excel opens on the first; `Chart Data` is hidden, so the
# tab strip shows eight and ends on `Data` (E6, plan P5).
SHEET_NAMES: tuple[str, ...] = (
    "Report",
    *(wo.COMMUNITY_LABELS[key] for key in wo.ALL_COMMUNITY_FILTERS),
    "Work Orders",
    CHART_DATA_SHEET,
    "Data",
)

PLACEHOLDER = "(none)"
EMPTY_STATE = "No live or recently closed work orders."
EMPTY_COMMUNITY_STATE = "No live or recently closed work orders in this community."

BUCKET_COLOR_ORDER = [theme.BUCKET_COLORS[key] for key in BUCKET_KEYS]


def report_xlsx(payload: DailyReport) -> bytes:
    workbook = Workbook()
    report_sheet = workbook.active
    report_sheet.title = "Report"
    community_sheets = {
        key: workbook.create_sheet(wo.COMMUNITY_LABELS[key])
        for key in wo.ALL_COMMUNITY_FILTERS
    }
    work_orders_sheet = workbook.create_sheet("Work Orders")
    chart_data = _ChartData(workbook.create_sheet(CHART_DATA_SHEET))
    chart_data.sheet.sheet_state = "hidden"
    data_sheet = workbook.create_sheet("Data")

    _report_sheet(report_sheet, payload, chart_data)
    for community in payload.distribution.communities:
        _community_sheet(community_sheets[community.key], payload, community, chart_data)
    _work_orders_sheet(work_orders_sheet, payload)
    _data_sheet(data_sheet, payload)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def report_xlsx_filename(payload: DailyReport) -> str:
    """Named for the period it covers, not the moment of export -- the same
    timesheet convention `report_filename` follows (user-hub-design.md D14)."""
    return f"wo-report_{payload.day.isoformat()}.xlsx"


# --------------------------------------------------------------------------
# Shared pieces
# --------------------------------------------------------------------------


class _ChartData:
    """Cursor over the hidden source sheet: one named block per chart (E7).

    Each block is a one-cell name, a header row, then its rows, then a blank
    row -- so a person who unhides the sheet can find what a chart reads."""

    def __init__(self, sheet: Worksheet) -> None:
        self.sheet = sheet
        self.row = 1

    def block(self, name: str, header: list, rows: list[list]) -> tuple[int, int]:
        """Write the block; return `(header_row, last_row)` for a `Reference`."""
        self.sheet.cell(row=self.row, column=1, value=name)
        header_row = self.row + 1
        for offset, value in enumerate(header, start=1):
            self.sheet.cell(row=header_row, column=offset, value=value)
        for index, values in enumerate(rows, start=1):
            for offset, value in enumerate(values, start=1):
                self.sheet.cell(row=header_row + index, column=offset, value=value)
        last_row = header_row + len(rows)
        self.row = last_row + 2
        return header_row, last_row


def _population_caveat(payload: DailyReport) -> str:
    """§2.1, on every designed sheet: what the population is, and why the
    community totals do not sum to the company total."""
    generated = payload.generated_at.astimezone(labor_day.CENTRAL)
    week = payload.week
    return (
        f"Live work orders as of {generated:%Y-%m-%d %H:%M} Central, plus work "
        f"orders closed {week.start.isoformat()} – {week.end.isoformat()}. A work "
        "order named in two communities is counted in both; community totals do "
        "not sum to the company total."
    )


def _bucket_rows(group: CommunityDistribution) -> list[list]:
    """Label / count / share, in bucket order. Shares are real fractions."""
    return [
        [
            BUCKET_LABELS[key],
            group.counts[key],
            (group.counts[key] / group.total) if group.total else 0,
        ]
        for key in BUCKET_KEYS
    ]


def _pie(
    sheet: Worksheet,
    chart_data: _ChartData,
    *,
    name: str,
    title: str,
    group,
    cells: str,
    legend: Optional[str],
    percent_labels: bool,
    empty_text: str = EMPTY_STATE,
) -> None:
    """A bucket pie for `group` (anything with `.total` and `.counts`) filling
    `cells`, or the empty-state line at the range's top-left when there is
    nothing to plot -- a pie with no area is a rendering bug, not a data point
    (§4.2)."""
    min_col, min_row, _, _ = range_boundaries(cells)
    if group.total == 0:
        theme.empty_state(sheet, min_row, empty_text, column=min_col)
        return
    header_row, last_row = chart_data.block(
        name,
        ["Bucket", "Count"],
        [[BUCKET_LABELS[key], group.counts[key]] for key in BUCKET_KEYS],
    )
    chart = theme.pie_of(
        chart_data.sheet,
        title=title,
        header_row=header_row,
        last_row=last_row,
        colors=BUCKET_COLOR_ORDER,
        legend=legend,
        percent_labels=percent_labels,
    )
    theme.place(sheet, chart, cells)


# --------------------------------------------------------------------------
# Report  (body added in Task 5)
# --------------------------------------------------------------------------


def _report_sheet(sheet: Worksheet, payload: DailyReport, chart_data: _ChartData) -> None:
    theme.setup_sheet(sheet, tab_color=theme.BRAND_RED)
    week = payload.week
    generated = payload.generated_at.astimezone(labor_day.CENTRAL)
    theme.title_block(
        sheet,
        "Weekly Work Order Report",
        [
            f"{payload.day.strftime('%a, %b %d, %Y')} · week of "
            f"{week.start.isoformat()} – {week.end.isoformat()} (week to date)",
            f"Generated {generated.strftime('%Y-%m-%d %H:%M')} Central",
            _population_caveat(payload),
        ],
    )


# --------------------------------------------------------------------------
# Community sheets  (body added in Task 6)
# --------------------------------------------------------------------------


def _community_sheet(
    sheet: Worksheet,
    payload: DailyReport,
    community: CommunityDistribution,
    chart_data: _ChartData,
) -> None:
    theme.setup_sheet(sheet, tab_color=theme.MUTED)
    theme.title_block(
        sheet,
        community.label,
        [
            f"Weekly status · {community.total:,} work orders",
            _population_caveat(payload),
        ],
    )


# --------------------------------------------------------------------------
# Work Orders
# --------------------------------------------------------------------------

WORK_ORDERS_HEADER_ROW = 5

WORK_ORDER_HEADERS: tuple[str, ...] = (
    "WORK ORDER",
    "LOCATION",
    "NOTES",
    "BUCKET",
    "STATUS",
    "COMMUNITIES",
    "SERVICE TYPE",
    "PRIORITY",
    "BUILDING",
    "UNIT",
    "SUPERVISOR",
    "TECHNICIANS",
    "MATERIAL LINES",
    "MATERIALS TOTAL",
    "LABOR MINUTES",
    "LABOR TOTAL",
    "TOTAL",
    "CREATED AT",
    "COMPLETED AT",
    "CLOSED AT",
    "SECTIONS",
)

WORK_ORDER_WIDTHS: tuple[int, ...] = (
    14, 34, theme.NOTES_WIDTH, 14, 16, 22, 18, 12, 10, 10, 18, 24, 12, 14, 12, 14, 14, 18, 18, 18, 20,
)

# 0-based column offset -> number format.
WORK_ORDER_FORMATS: dict[int, str] = {
    12: theme.COUNT,
    13: theme.MONEY,
    14: theme.COUNT,
    15: theme.MONEY,
    16: theme.MONEY,
    17: theme.DATE,
    18: theme.DATE,
    19: theme.DATE,
}


def _excel_utc(value: Optional[datetime]) -> Optional[datetime]:
    """UTC, naive: openpyxl refuses tz-aware datetimes. UTC on purpose -- the
    same seam `export_row` writes (§5); the covered period is in the title."""
    if value is None:
        return None
    return labor_day.as_utc(value).astimezone(timezone.utc).replace(tzinfo=None)


def _sections_of(payload: DailyReport) -> dict[UUID, list[str]]:
    """Which report sections each work order appeared in, in SECTION_ORDER --
    the `Data` sheet's SECTION filter folded into one deduped row."""
    seen: dict[UUID, list[str]] = {}
    for key in SECTION_ORDER:
        for row in getattr(payload.sections, key).rows:
            seen.setdefault(row.work_order_id, []).append(key)
    return seen


def _work_order_cells(row: ReportRow, sections: dict[UUID, list[str]]) -> list:
    return [
        row.number,
        row.location,
        row.notes,
        BUCKET_LABELS[row_bucket(row)],
        STATUS_LABELS.get(row.status, row.status),
        "; ".join(communities_of(row)),
        row.service_type,
        row.priority,
        row.building_number,
        row.unit_number,
        row.supervisor_name,
        "; ".join(row.technician_names),
        row.material_lines,
        row.materials_total,
        row.labor_minutes,
        row.labor_total,
        row.total,
        _excel_utc(row.created_at),
        _excel_utc(row.completed_at),
        _excel_utc(row.archived_at),
        "; ".join(sections.get(row.work_order_id, [])),
    ]


def _work_orders_sheet(sheet: Worksheet, payload: DailyReport) -> None:
    """One row per work order over the E1 population, deduped, in reading
    order (§4.3). Money is numeric here -- this sheet is for reading and
    pivoting, and it is not the re-import path."""
    theme.setup_sheet(
        sheet,
        tab_color=theme.INK,
        freeze=f"D{WORK_ORDERS_HEADER_ROW + 1}",
        print_title_rows=f"{WORK_ORDERS_HEADER_ROW}:{WORK_ORDERS_HEADER_ROW}",
    )
    theme.set_widths(
        sheet,
        {get_column_letter(index): width for index, width in enumerate(WORK_ORDER_WIDTHS, start=1)},
    )
    week = payload.week
    theme.title_block(
        sheet,
        "Work Orders",
        [
            f"{len(payload.all_rows):,} work orders · live now plus closed "
            f"{week.start.isoformat()} – {week.end.isoformat()}",
            "One row per work order. Timestamps are UTC; the covered period is "
            "in the line above and in the filename.",
        ],
    )

    sections = _sections_of(payload)
    rows = [_work_order_cells(row, sections) for row in payload.all_rows]
    theme.table_of(
        sheet,
        name="WorkOrders",
        row=WORK_ORDERS_HEADER_ROW,
        headers=WORK_ORDER_HEADERS,
        rows=rows,
        formats=WORK_ORDER_FORMATS,
        alignment=theme.TOP,
    )
    first = WORK_ORDERS_HEADER_ROW + 1
    for index, row in enumerate(payload.all_rows, start=first):
        sheet.cell(row=index, column=3).alignment = theme.TOP_WRAPPED
        height = theme.notes_row_height(row.notes)
        if height is not None:
            sheet.row_dimensions[index].height = height
    if not rows:
        theme.empty_state(sheet, first, EMPTY_STATE)


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------


def _data_sheet(sheet: Worksheet, payload: DailyReport) -> None:
    """`report_csv` as cells: same header, same section order, same values.

    Deliberately not coerced to numbers. The money columns stay the strings
    `export_row` produced, so Excel shows its "number stored as text" hint on
    them -- that is the price of the CSV being byte-identical, and the charts
    are immune because they read `Chart Data` instead."""
    theme.setup_sheet(sheet, tab_color=theme.TAB_GRAY, freeze="A2", gridlines=True)
    sheet.append([CSV_SECTION_HEADER, *wo.EXPORT_HEADERS])
    for cell in sheet[1]:
        cell.font = theme.font(bold=True)
    for key in SECTION_ORDER:
        # All five sections, so a row appears under both `closed_today` and
        # `closed_week` -- the CSV's filter-on-SECTION property, preserved.
        for row in getattr(payload.sections, key).rows:
            sheet.append([key, *row.export_cells])
