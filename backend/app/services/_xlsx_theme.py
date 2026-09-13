"""House style for the weekly closed report workbook.

Layer: services (pure -- openpyxl objects in, openpyxl objects out). Fonts,
fills, and the small sheet-furniture helpers, so `work_order_report_xlsx.py`
is sheet composition and nothing else.

Spec: docs/superpowers/specs/2026-09-13-weekly-closed-report-design.md §6
"""

from __future__ import annotations

from typing import Optional, Sequence

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet

# --- palette ----------------------------------------------------------------

BRAND_RED = "C8102E"  # titles: the brand
INK = "1C1D20"
MUTED = "5A5C60"
RULE = "D8D9DB"
WHITE = "FFFFFF"

# --- type -------------------------------------------------------------------

FONT_NAME = "Aptos Narrow"  # Excel falls back to Calibri where it is missing


def font(**overrides) -> Font:
    return Font(**{"name": FONT_NAME, "size": 10, **overrides})


BODY = font()
TITLE = font(size=18, bold=True, color=BRAND_RED)
SUBTITLE = font(size=9, italic=True, color=MUTED)
SECTION = font(size=11, bold=True, color=INK)
HEADER = font(bold=True, color=WHITE)

HEADER_FILL = PatternFill("solid", fgColor=INK)
SECTION_RULE = Border(bottom=Side(style="thin", color=RULE))


# --- sheet furniture --------------------------------------------------------


def setup_sheet(
    sheet: Worksheet,
    *,
    tab_color: str,
    freeze: Optional[str] = None,
    gridlines: bool = False,
) -> None:
    """Tab color, gridlines, freeze panes, and the print setup every sheet
    shares: landscape, one page wide, half-inch margins."""
    sheet.sheet_properties.tabColor = tab_color
    sheet.sheet_view.showGridLines = gridlines
    sheet.freeze_panes = freeze
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    for side in ("left", "right", "top", "bottom"):
        setattr(sheet.page_margins, side, 0.5)


def set_widths(sheet: Worksheet, widths: dict[str, float]) -> None:
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width


def title_block(sheet: Worksheet, title: str, lines: Sequence[str]) -> None:
    """Rows 1-3: the title, then up to two subtitle lines."""
    sheet.cell(row=1, column=1, value=title).font = TITLE
    for offset, line in enumerate(lines, start=2):
        sheet.cell(row=offset, column=1, value=line).font = SUBTITLE


def section(sheet: Worksheet, row: int, text: str, *, span: int = 6) -> None:
    """A section heading with a 1pt rule under it across `span` columns."""
    sheet.cell(row=row, column=1, value=text).font = SECTION
    for column in range(1, span + 1):
        sheet.cell(row=row, column=column).border = SECTION_RULE


def empty_state(sheet: Worksheet, row: int, text: str, *, column: int = 1) -> None:
    sheet.cell(row=row, column=column, value=text).font = font(italic=True, color=MUTED)


def header_row(
    sheet: Worksheet, row: int, headers: Sequence[str], *, column: int = 1
) -> None:
    """White-on-ink header cells."""
    for offset, header in enumerate(headers):
        cell = sheet.cell(row=row, column=column + offset, value=header)
        cell.font = HEADER
        cell.fill = HEADER_FILL


def write_rows(
    sheet: Worksheet,
    row: int,
    rows: Sequence[Sequence],
    *,
    column: int = 1,
    alignment: Optional[Alignment] = None,
) -> int:
    """Write `rows` from `row` down. Returns the last row written (`row - 1`
    if none)."""
    for index, values in enumerate(rows):
        for offset, value in enumerate(values):
            cell = sheet.cell(row=row + index, column=column + offset, value=value)
            cell.font = BODY
            if alignment is not None:
                cell.alignment = alignment
    return row + len(rows) - 1
