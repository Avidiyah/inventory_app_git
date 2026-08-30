"""The daily report's Excel render.

`report_xlsx` is a pure function of a `DailyReport` (spec X3), so these tests
hand-build frozen payloads instead of touching the database -- no `db` fixture,
no dev-Postgres fencing.

Spec: docs/superpowers/specs/2026-08-30-hub-report-xlsx-export-design.md
"""

import csv
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import openpyxl

from app.domain import work_orders as wo
from app.services import work_order_report as report
from app.services import work_order_report_xlsx as xlsx


def _row(
    *,
    number="WO-1",
    status=wo.STATUS_COMPLETED,
    community=None,
    service_type=None,
    labor_total="0.00",
    materials_total="0.00",
):
    """A `ReportRow` whose `export_cells` are shaped like `export_row`'s: 26
    values, three of them genuine ints, money as fixed-point strings."""
    labor = Decimal(labor_total)
    materials = Decimal(materials_total)
    cells = [
        number,
        "Bldg A",
        "",
        "",
        service_type or "",
        "",
        "Leaky faucet",
        status,
        "Tech One; Tech Two",
        "Sue",
        community or "",
        "3",
        "12",
        "manual",
        2,
        f"{materials:.2f}",
        60,
        60,
        f"{labor:.2f}",
        f"{materials + labor:.2f}",
        "",
        "2026-08-25 14:00",
        "2026-08-25 15:00",
        "2026-08-25 15:00",
        "2026-08-25 15:30",
    ]
    assert len(cells) == len(wo.EXPORT_HEADERS)
    return report.ReportRow(
        work_order_id=uuid4(),
        number=number,
        status=status,
        community=community,
        location="Bldg A",
        building_number="3",
        unit_number="12",
        service_type=service_type,
        priority=None,
        supervisor_name="Sue",
        technician_names=["Tech One", "Tech Two"],
        materials_total=materials,
        labor_minutes=60,
        labor_total=labor,
        total=materials + labor,
        created_at=datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc),
        archived_at=datetime(2026, 8, 25, 15, 30, tzinfo=timezone.utc),
        auto_closed=False,
        legacy=False,
        export_cells=cells,
    )


def _payload(
    *,
    closed_today=(),
    closed_week=(),
    closing=(),
    new_today=(),
    new_week=(),
    auto_closed_today=0,
    by_status=None,
    closing_count=None,
    truncated=False,
):
    closing_rows = list(closing)
    return report.DailyReport(
        generated_at=datetime(2026, 8, 25, 22, 30, tzinfo=timezone.utc),
        day=date(2026, 8, 25),
        week=report.ReportWeek(start=date(2026, 8, 24), end=date(2026, 8, 30)),
        sections=report.ReportSections(
            closed_today=report.ClosedSection(
                count=len(closed_today),
                auto_closed_count=auto_closed_today,
                rows=list(closed_today),
            ),
            closed_week=report.ClosedSection(
                count=len(closed_week), auto_closed_count=0, rows=list(closed_week)
            ),
            closing=report.ClosingSection(
                count=(closing_count if closing_count is not None else len(closing_rows)),
                by_status=(by_status if by_status is not None else {}),
                truncated=truncated,
                rows=closing_rows,
            ),
            new_today=report.NewSection(count=len(new_today), rows=list(new_today)),
            new_week=report.NewSection(count=len(new_week), rows=list(new_week)),
        ),
    )


def _workbook(payload):
    return openpyxl.load_workbook(io.BytesIO(xlsx.report_xlsx(payload)))


def _cells(sheet):
    """Every cell value as a grid, `None` intact."""
    return [[cell.value for cell in row] for row in sheet.iter_rows()]


def test_data_sheet_matches_report_csv():
    """The load-bearing pin (X5): the Data sheet is `report_csv`, cell for
    cell, so save-as-CSV from Excel still round-trips through the importer."""
    closed = _row(number="WO-1", community="North", service_type="Plumbing")
    payload = _payload(
        closed_today=[closed],
        closed_week=[closed, _row(number="WO-2", service_type="HVAC")],
        closing=[_row(number="WO-3", status=wo.STATUS_REVIEW)],
        new_today=[_row(number="WO-4")],
        new_week=[_row(number="WO-4")],
        by_status={wo.STATUS_REVIEW: 1},
    )

    expected = list(csv.reader(io.StringIO(report.report_csv(payload))))
    actual = [
        ["" if value is None else str(value) for value in row]
        for row in _cells(_workbook(payload)["Data"])
    ]

    assert actual == expected


def test_data_sheet_header_is_the_section_prefixed_export_headers():
    sheet = _workbook(_payload())["Data"]

    assert tuple(cell.value for cell in sheet[1]) == (
        report.CSV_SECTION_HEADER,
    ) + wo.EXPORT_HEADERS
    assert sheet.freeze_panes == "A2"


def test_headline_block_matches_the_payload_counts():
    payload = _payload(
        closed_today=[_row(number="WO-1")],
        closed_week=[_row(number="WO-1"), _row(number="WO-2")],
        new_today=[_row(number="WO-3")],
        new_week=[_row(number="WO-3"), _row(number="WO-4"), _row(number="WO-5")],
    )
    sheet = _workbook(payload)["Summary"]

    assert [cell.value for cell in sheet[xlsx.ACTIVITY_ROW]] [:3] == [
        None,
        "Today",
        "Week to date",
    ]
    assert [
        [sheet.cell(row=row, column=col).value for col in (1, 2, 3)]
        for row in (xlsx.ACTIVITY_ROW + 1, xlsx.ACTIVITY_ROW + 2)
    ] == [["Closed", 1, 2], ["New", 1, 3]]


def test_headline_block_notes_auto_closed_work_orders():
    payload = _payload(closed_today=[_row()], auto_closed_today=1)
    values = [row[0] for row in _cells(_workbook(payload)["Summary"])]

    assert any(
        isinstance(value, str) and "(1 in NetFacilities)" in value for value in values
    )


def test_pipeline_block_zero_fills_by_status():
    """Counts come from `by_status`, never from the rows (X8): the block stays
    true when the cap bites, and every lifecycle status is always charted."""
    payload = _payload(
        closing=[_row(number="WO-1", status=wo.STATUS_REVIEW)],
        by_status={wo.STATUS_REVIEW: 4, wo.STATUS_READY_TO_COMPLETE: 2},
        closing_count=6,
        truncated=True,
    )
    sheet = _workbook(payload)["Summary"]
    grid = _cells(sheet)

    start = next(
        index for index, row in enumerate(grid) if row and row[0] == "In the pipeline"
    )
    assert grid[start][1] == 6
    assert [row[:2] for row in grid[start + 1 : start + 4]] == [
        ["Ready to complete", 2],
        ["Completed", 0],
        ["Review", 4],
    ]
    assert any(
        isinstance(row[0], str) and "counts above are complete" in row[0]
        for row in grid
    )


def test_service_type_and_community_blocks_aggregate_closed_week():
    week = [
        _row(number="WO-1", service_type="Plumbing", community="North",
             labor_total="100.00", materials_total="10.00"),
        _row(number="WO-2", service_type="Plumbing", community=None,
             labor_total="5.00", materials_total="0.00"),
        _row(number="WO-3", service_type=None, community="North",
             labor_total="50.00", materials_total="20.00"),
    ]

    assert xlsx._service_type_counts(week) == [
        ("Plumbing", 2),
        ("(no service type)", 1),
    ]
    assert xlsx._community_money(week) == [
        ("North", Decimal("150.00"), Decimal("30.00")),
        ("(no community)", Decimal("5.00"), Decimal("0.00")),
    ]

    grid = _cells(_workbook(_payload(closed_week=week))["Summary"])
    assert ["Plumbing", 2] in [row[:2] for row in grid]
    assert ["North", Decimal("150.00"), Decimal("30.00")] in [row[:3] for row in grid]


def test_empty_report_renders_placeholders():
    grid = _cells(_workbook(_payload())["Summary"])
    rows = [row[:3] for row in grid]

    assert ["(none)", 0, None] in rows
    assert ["(none)", Decimal("0.00"), Decimal("0.00")] in rows


def test_workbook_contains_four_charts():
    """Asserted at the zip level: openpyxl cannot read back charts it wrote
    (spec §3), so the file itself is the only honest witness."""
    with zipfile.ZipFile(io.BytesIO(xlsx.report_xlsx(_payload()))) as archive:
        charts = [
            name
            for name in archive.namelist()
            if name.startswith("xl/charts/chart") and name.endswith(".xml")
        ]

    assert len(charts) == 4


def test_sheet_order_opens_on_summary():
    assert _workbook(_payload()).sheetnames == ["Summary", "Data"]


def test_filename_is_the_covered_day():
    assert xlsx.report_xlsx_filename(_payload()) == "wo-report_2026-08-25.xlsx"
