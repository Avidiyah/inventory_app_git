"""The Admin daily report as an Excel workbook: charts up front, rows behind.

Layer: services. The third renderer of `work_order_report.daily_report`'s
payload, beside the JSON route and `report_csv` -- a pure function of that
payload, no queries and no clock, so the file and the screen cannot disagree
(parent spec R9). It lives in its own module because `work_order_report.py` is
already 324 lines and a four-chart builder would push it past the 500-line rule.

Spec: docs/superpowers/specs/2026-08-30-hub-report-xlsx-export-design.md

Two things about this module are load-bearing:

**openpyxl discards charts across a load/save cycle.** So there is no committed
`.xlsx` template to fill in -- a template's charts would vanish, silently, from
every download. The workbook is built programmatically instead, which openpyxl
does fully support. The same limitation means the charts here cannot be read
back through openpyxl: `tests/test_work_order_report_xlsx.py` asserts their
presence over the saved bytes with `zipfile`.

**The `Data` sheet is `report_csv`, cell for cell**, money-as-text included, so
save-as-CSV from Excel still round-trips through `parse_import_row`. Charts
never read it; they read the `Summary` blocks, which hold real numerics.
"""

from __future__ import annotations

import io
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference, Series
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from app.domain import labor_day
from app.domain import work_orders as wo
from app.services.work_order_report import (
    CLOSING_STATUSES,
    CSV_SECTION_HEADER,
    SECTION_ORDER,
    DailyReport,
    ReportRow,
)

XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

# The page's own labels, so the workbook and the screen name the same things.
STATUS_LABELS: dict[str, str] = {
    wo.STATUS_READY_TO_COMPLETE: "Ready to complete",
    wo.STATUS_COMPLETED: "Completed",
    wo.STATUS_REVIEW: "Review",
}

NO_SERVICE_TYPE = "(no service type)"
NO_COMMUNITY = "(no community)"
PLACEHOLDER = "(none)"

# Brand red primary, neutral grey secondary (docs/design-system.md). Series
# colors are the only styling here beyond bold headers and money formats.
BRAND_RED = "C8102E"
NEUTRAL = "5A5C60"

MONEY_FORMAT = "#,##0.00"

# The first block's addresses are fixed because the header above it is: rows
# 1-4 are the title block, row 6 the block's own heading, row 7 its column
# labels. Every later block is laid out by cursor -- blocks 3 and 4 are
# variable-length -- so nothing below here has a fixed address.
ACTIVITY_ROW = 7

# A default openpyxl chart is about this many rows tall. The cursor advances by
# at least this much between blocks so a chart anchored beside one block cannot
# land on top of the next one's.
CHART_ROWS = 15

BOLD = Font(bold=True)


def report_xlsx(payload: DailyReport) -> bytes:
    """The whole report as a two-sheet workbook: `Summary` then `Data`.

    Sheet order is the reading order -- Excel opens on the first sheet, so the
    Admin lands on the charts and reaches the rows deliberately."""
    workbook = Workbook()
    # Workbook() ships one sheet; reuse it rather than creating and deleting.
    summary = workbook.active
    summary.title = "Summary"
    _summary_sheet(summary, payload)
    _data_sheet(workbook.create_sheet("Data"), payload)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def report_xlsx_filename(payload: DailyReport) -> str:
    """Named for the period it covers, not the moment of export -- the same
    timesheet convention `report_filename` follows (user-hub-design.md D14)."""
    return f"wo-report_{payload.day.isoformat()}.xlsx"


# --------------------------------------------------------------------------
# Data sheet
# --------------------------------------------------------------------------


def _data_sheet(sheet: Worksheet, payload: DailyReport) -> None:
    """`report_csv` as cells: same header, same section order, same values.

    Deliberately not coerced to numbers. The money columns stay the strings
    `export_row` produced, so Excel shows its "number stored as text" hint on
    them -- that is the price of the CSV being byte-identical, and the charts
    are immune because they read the Summary blocks instead."""
    sheet.append([CSV_SECTION_HEADER, *wo.EXPORT_HEADERS])
    for cell in sheet[1]:
        cell.font = BOLD
    sheet.freeze_panes = "A2"

    for key in SECTION_ORDER:
        # All five sections, so a row appears under both `closed_today` and
        # `closed_week` -- the CSV's filter-on-SECTION property, preserved.
        for row in getattr(payload.sections, key).rows:
            sheet.append([key, *row.export_cells])


# --------------------------------------------------------------------------
# Summary sheet
# --------------------------------------------------------------------------


def _summary_sheet(sheet: Worksheet, payload: DailyReport) -> None:
    sheet.column_dimensions["A"].width = 26
    sheet.column_dimensions["B"].width = 14
    sheet.column_dimensions["C"].width = 14

    _header(sheet, payload)

    cursor = 6
    for block in (
        _activity_block,
        _pipeline_block,
        _service_type_block,
        _community_money_block,
    ):
        height = block(sheet, payload, cursor)
        cursor += max(height, CHART_ROWS) + 2


def _header(sheet: Worksheet, payload: DailyReport) -> None:
    week = payload.week
    generated = payload.generated_at.astimezone(labor_day.CENTRAL)
    sheet["A1"] = "Daily Report"
    sheet["A1"].font = Font(bold=True, size=16)
    sheet["A2"] = payload.day.strftime("%a, %b %d, %Y")
    sheet["A3"] = (
        f"Week of {week.start.isoformat()} - {week.end.isoformat()} - week to date"
    )
    # Central, the zone the report's windows are cut in and the page renders.
    sheet["A4"] = f"Generated {generated.strftime('%Y-%m-%d %H:%M')} Central"


def _write(sheet: Worksheet, row: int, values: list, *, bold: bool = False) -> None:
    for offset, value in enumerate(values, start=1):
        cell = sheet.cell(row=row, column=offset, value=value)
        if bold:
            cell.font = BOLD


def _heading(sheet: Worksheet, row: int, text: str) -> None:
    sheet.cell(row=row, column=1, value=text).font = BOLD


def _anchor(row: int) -> str:
    """Charts live in column E, clear of the A-C blocks they read."""
    return f"E{row}"


def _styled(series: Series, color: str) -> Series:
    series.graphicalProperties = GraphicalProperties(solidFill=color)
    return series


def _activity_block(sheet: Worksheet, payload: DailyReport, top: int) -> int:
    """Block 1 -- the four section counts as a Closed/New by Today/Week matrix.

    Counts come from the sections' own `count` fields, never from tallying
    rows: `closing` can be capped, and the page follows the same rule."""
    sections = payload.sections
    # `top + 1` is `ACTIVITY_ROW`: this is the one block whose address is fixed,
    # because everything above it is.
    _heading(sheet, top, "Activity")
    _write(sheet, ACTIVITY_ROW, [None, "Today", "Week to date"], bold=True)
    _write(
        sheet,
        ACTIVITY_ROW + 1,
        ["Closed", sections.closed_today.count, sections.closed_week.count],
    )
    _write(
        sheet,
        ACTIVITY_ROW + 2,
        ["New", sections.new_today.count, sections.new_week.count],
    )

    height = (ACTIVITY_ROW + 2) - top + 1
    auto_today = sections.closed_today.auto_closed_count
    auto_week = sections.closed_week.auto_closed_count
    if auto_today or auto_week:
        # The page's own phrasing, so the file reads like the screen.
        note = (
            f"Closed today includes ({auto_today} in NetFacilities); "
            f"this week ({auto_week} in NetFacilities)"
        )
        sheet.cell(row=ACTIVITY_ROW + 3, column=1, value=note)
        height += 1

    chart = BarChart()
    chart.type = "col"
    chart.title = "Activity"
    chart.y_axis.title = "Work orders"
    data = Reference(
        sheet, min_col=2, max_col=3, min_row=ACTIVITY_ROW, max_row=ACTIVITY_ROW + 2
    )
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(
        Reference(sheet, min_col=1, min_row=ACTIVITY_ROW + 1, max_row=ACTIVITY_ROW + 2)
    )
    for series, color in zip(chart.series, (BRAND_RED, NEUTRAL)):
        _styled(series, color)
    sheet.add_chart(chart, _anchor(top))
    return height


def _pipeline_block(sheet: Worksheet, payload: DailyReport, top: int) -> int:
    """Block 2 -- what is sitting in a closing status, by status.

    Zero-filled from `CLOSING_STATUSES` so the chart always shows all three
    lifecycle categories, and read from `by_status` rather than from `rows` so
    it stays true when the cap bites."""
    closing = payload.sections.closing
    _heading(sheet, top, "Closing pipeline")
    total_row = top + 1
    _write(sheet, total_row, ["In the pipeline", closing.count])

    first = total_row + 1
    for offset, status in enumerate(CLOSING_STATUSES):
        _write(
            sheet,
            first + offset,
            [STATUS_LABELS.get(status, status), closing.by_status.get(status, 0)],
        )
    last = first + len(CLOSING_STATUSES) - 1

    height = last - top + 1
    if closing.truncated:
        sheet.cell(
            row=last + 1,
            column=1,
            value=(
                "Showing the first rows only on the Data sheet -- more are in the "
                "pipeline than it lists. The counts above are complete."
            ),
        )
        height += 1

    chart = BarChart()
    chart.type = "bar"
    chart.title = "Closing pipeline"
    chart.add_data(Reference(sheet, min_col=2, min_row=first, max_row=last))
    chart.set_categories(Reference(sheet, min_col=1, min_row=first, max_row=last))
    chart.legend = None
    _styled(chart.series[0], BRAND_RED)
    sheet.add_chart(chart, _anchor(top))
    return height


def _service_type_counts(rows: list[ReportRow]) -> list[tuple[str, int]]:
    """Closed rows per service type, busiest first then alphabetical."""
    counts: dict[str, int] = {}
    for row in rows:
        key = row.service_type or NO_SERVICE_TYPE
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))


def _service_type_block(sheet: Worksheet, payload: DailyReport, top: int) -> int:
    """Block 3 -- the week's closures by service type. Variable-length, so the
    chart's `Reference` is built from the block's actual extent."""
    counts = _service_type_counts(payload.sections.closed_week.rows) or [
        (PLACEHOLDER, 0)
    ]
    _heading(sheet, top, "Closed this week by service type")
    header = top + 1
    _write(sheet, header, ["Service type", "Closed"], bold=True)
    for offset, (name, count) in enumerate(counts, start=1):
        _write(sheet, header + offset, [name, count])
    last = header + len(counts)

    chart = BarChart()
    chart.type = "bar"
    chart.title = "Closed this week by service type"
    chart.add_data(
        Reference(sheet, min_col=2, min_row=header, max_row=last), titles_from_data=True
    )
    chart.set_categories(Reference(sheet, min_col=1, min_row=header + 1, max_row=last))
    chart.legend = None
    _styled(chart.series[0], BRAND_RED)
    sheet.add_chart(chart, _anchor(top))
    return last - top + 1


def _community_money(
    rows: list[ReportRow],
) -> list[tuple[str, Decimal, Decimal]]:
    """Labor and materials dollars per community, biggest combined first.

    Decimals throughout -- openpyxl writes them natively, and the report's
    money is never a float anywhere else either."""
    totals: dict[str, list[Decimal]] = {}
    for row in rows:
        key = row.community or NO_COMMUNITY
        bucket = totals.setdefault(key, [Decimal("0.00"), Decimal("0.00")])
        bucket[0] += row.labor_total
        bucket[1] += row.materials_total
    return sorted(
        ((name, labor, materials) for name, (labor, materials) in totals.items()),
        key=lambda entry: (-(entry[1] + entry[2]), entry[0]),
    )


def _community_money_block(sheet: Worksheet, payload: DailyReport, top: int) -> int:
    """Block 4 -- where the week's money went, split labor vs materials.

    Stacked rather than side-by-side: one chart answers both "which community"
    and "how much of it was labor" (X11)."""
    money = _community_money(payload.sections.closed_week.rows) or [
        (PLACEHOLDER, Decimal("0.00"), Decimal("0.00"))
    ]
    _heading(sheet, top, "Closed this week: dollars by community")
    header = top + 1
    _write(sheet, header, ["Community", "Labor $", "Materials $"], bold=True)
    for offset, (name, labor, materials) in enumerate(money, start=1):
        _write(sheet, header + offset, [name, labor, materials])
        for column in (2, 3):
            sheet.cell(row=header + offset, column=column).number_format = MONEY_FORMAT
    last = header + len(money)

    chart = BarChart()
    chart.type = "col"
    chart.grouping = "stacked"
    chart.overlap = 100
    chart.title = "Closed this week: dollars by community"
    chart.y_axis.title = "Dollars"
    chart.add_data(
        Reference(sheet, min_col=2, max_col=3, min_row=header, max_row=last),
        titles_from_data=True,
    )
    chart.set_categories(Reference(sheet, min_col=1, min_row=header + 1, max_row=last))
    for series, color in zip(chart.series, (BRAND_RED, NEUTRAL)):
        _styled(series, color)
    sheet.add_chart(chart, _anchor(top))
    return last - top + 1

