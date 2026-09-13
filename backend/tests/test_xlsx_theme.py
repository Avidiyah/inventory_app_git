"""The workbook's house style helpers.

Spec: docs/superpowers/specs/2026-09-13-weekly-closed-report-design.md §6.
"""

import io

import openpyxl
from openpyxl import Workbook

from app.services import _xlsx_theme as theme


def _reloaded(workbook):
    buffer = io.BytesIO()
    workbook.save(buffer)
    return openpyxl.load_workbook(io.BytesIO(buffer.getvalue())).active


def test_setup_sheet_applies_the_shared_furniture():
    workbook = Workbook()
    theme.setup_sheet(workbook.active, tab_color=theme.MUTED)

    sheet = _reloaded(workbook)

    assert sheet.sheet_properties.tabColor.rgb.endswith(theme.MUTED)
    assert sheet.sheet_view.showGridLines is False
    assert sheet.freeze_panes is None
    assert sheet.page_setup.orientation == "landscape"
    assert sheet.page_setup.fitToWidth == 1
    assert sheet.sheet_properties.pageSetUpPr.fitToPage is True
    assert sheet.page_margins.left == 0.5


def test_setup_sheet_can_freeze_and_leave_gridlines_on():
    workbook = Workbook()
    theme.setup_sheet(workbook.active, tab_color=theme.INK, freeze="A2", gridlines=True)

    sheet = _reloaded(workbook)

    assert sheet.freeze_panes == "A2"
    assert sheet.sheet_view.showGridLines is not False


def test_title_block_section_and_header_styles():
    workbook = Workbook()
    sheet = workbook.active
    theme.title_block(sheet, "Maintenance", ["Closed …", "Completed …"])
    theme.section(sheet, 5, "Scholars", span=3)
    theme.header_row(sheet, 6, ("A", "B"))

    assert sheet["A1"].font.size == 18 and sheet["A1"].font.color.rgb.endswith(theme.BRAND_RED)
    assert sheet["A2"].font.italic and sheet["A2"].font.size == 9
    assert sheet["A3"].value == "Completed …"
    assert sheet["A5"].font.bold and sheet["C5"].border.bottom.style == "thin"
    assert sheet["D5"].border.bottom.style is None
    assert sheet["A6"].font.bold and sheet["A6"].font.color.rgb.endswith(theme.WHITE)
    assert sheet["B6"].fill.fgColor.rgb.endswith(theme.INK)


def test_write_rows_returns_the_last_row_and_uses_the_body_font():
    workbook = Workbook()
    sheet = workbook.active

    last = theme.write_rows(sheet, 7, [["1", None], ["2", "x"]])
    none = theme.write_rows(sheet, 20, [])

    assert last == 8
    assert none == 19
    assert sheet["A8"].value == "2" and sheet["B7"].value is None
    assert sheet["A7"].font.name == theme.FONT_NAME and sheet["A7"].font.size == 10


def test_empty_state_and_widths():
    workbook = Workbook()
    sheet = workbook.active
    theme.empty_state(sheet, 5, "Nothing")
    theme.set_widths(sheet, {"A": 14, "C": 34})

    assert sheet["A5"].value == "Nothing" and sheet["A5"].font.italic
    assert sheet.column_dimensions["A"].width == 14
    assert sheet.column_dimensions["C"].width == 34
