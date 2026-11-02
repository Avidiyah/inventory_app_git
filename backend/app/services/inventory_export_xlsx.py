"""The item list and every User Requests tab as one print-ready workbook.

Layer: services. Reads through the same list services the pages use
(`items.list_items`, `user_requests.list_user_requests`), so the file holds
the rows the screens do. Styling and print setup live in `_xlsx_theme.py`.

A field handoff: an employee walks it, fills the shaded write-in columns by
hand, and the admin keys the findings back into the app. Sheets: Items, then
one per request type in User Requests tab order. Resolved requests are
omitted -- only open and stocked ones need a real-world check.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.orm import Session

from app.domain.labor_day import CENTRAL
from app.domain.material_requests import STATUS_RESOLVED
from app.models import Item, ItemBarcode, UserRequest
from app.services import _xlsx_theme as theme
from app.services import items as items_service
from app.services import user_requests as request_service

HEADER_ROW = 4
_WRAP = Alignment(wrap_text=True, vertical="top")
# Write-in cells: pale tint + a box so the blanks read as "fill me" on paper.
_WRITE_IN_FILL = PatternFill("solid", fgColor="F3F3F4")
_BOX = Side(style="thin", color=theme.MUTED)
_WRITE_IN_BORDER = Border(left=_BOX, right=_BOX, top=_BOX, bottom=_BOX)
_ROW_HEIGHT = 30  # room to handwrite
SIGN_OFF = "Checked by: ____________________    Date: ____________"

ITEM_HEADERS = ("NAME", "BARCODE", "QTY", "LOW", "LOCATION", "NOTES")
ITEM_WRITE_INS = ("COUNTED", "OK ✓", "FIELD NOTES")
ITEM_WIDTHS = {"A": 36, "B": 18, "C": 7, "D": 6, "E": 16, "F": 24, "G": 10, "H": 7, "I": 32}

REQUEST_SHEETS = (
    (request_service.REQUEST_MATERIAL, "Material requests"),
    (request_service.REQUEST_CATALOGUE, "Catalogue requests"),
    (request_service.REQUEST_INVENTORY_RECOUNT, "Stock recounts"),
    (request_service.REQUEST_MISSING_ITEM_PRICE, "Missing price - link"),
)
REQUEST_HEADERS = (
    "FILED", "STATUS", "ITEM", "BARCODE", "QTY", "WORK ORDER", "FILED BY", "NOTE",
)
REQUEST_WRITE_INS = ("DONE ✓", "FINDING")
REQUEST_WIDTHS = {
    "A": 15, "B": 9, "C": 30, "D": 15, "E": 6, "F": 12,
    "G": 16, "H": 26, "I": 8, "J": 34,
}


def export_xlsx(db: Session, *, now: datetime) -> bytes:
    workbook = Workbook()
    stamp = f"Exported {_when(now)}"

    items = sorted(items_service.list_items(db), key=lambda item: item.name.casefold())
    low_ids = {item.id for item, _, _ in items_service.list_low_stock(db)}
    _sheet(
        workbook.active, "Items", f"{stamp}  ·  {len(low_ids)} low stock", ITEM_HEADERS, ITEM_WRITE_INS, ITEM_WIDTHS,
        [_item_cells(item, item.id in low_ids) for item in items], "No items.",
    )
    # Low-stock rows in brand red; the LOW column carries it on a mono printer.
    for row in workbook.active.iter_rows(min_row=HEADER_ROW + 1, max_col=len(ITEM_HEADERS)):
        if row[3].value == "LOW":
            for cell in row:
                cell.font = theme.font(bold=True, color=theme.BRAND_RED)
    for request_type, title in REQUEST_SHEETS:
        rows = [
            row for row in request_service.list_user_requests(
                db, status=None, request_type=request_type,
            )
            if row.status != STATUS_RESOLVED
        ]
        _sheet(
            workbook.create_sheet(), title, stamp, REQUEST_HEADERS, REQUEST_WRITE_INS,
            REQUEST_WIDTHS,
            [_request_cells(row) for row in rows], "Nothing open.",
        )

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def export_filename(now: datetime) -> str:
    return f"inventory-export_{now.astimezone(CENTRAL).date().isoformat()}.xlsx"


ITEMS_CSV_HEADERS = (
    "Barcode", "Name", "Quantity", "Low stock threshold", "Location", "Price",
    "Product link", "Additional barcodes", "Notes", "Created at",
)


def items_csv(db: Session) -> str:
    """Every live item, every field, as CSV: one header row, no title line
    (a spreadsheet import gets a title line wrong). Ignores any search."""
    extra: dict = {}
    for code in db.query(ItemBarcode).order_by(ItemBarcode.created_at, ItemBarcode.code):
        extra.setdefault(code.item_id, []).append(code.code)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(ITEMS_CSV_HEADERS)
    for item in sorted(items_service.list_items(db), key=lambda item: item.name.casefold()):
        writer.writerow([_csv_text(cell) for cell in (
            item.barcode, item.name, _number(item.quantity), item.low_stock_threshold,
            item.location, _number(item.price), item.product_link,
            "; ".join(extra.get(item.id, ())), _notes_text(item), _when(item.created_at),
        )])
    return buffer.getvalue()


def items_csv_filename(now: datetime) -> str:
    return f"items_{now.astimezone(CENTRAL).date().isoformat()}.csv"


def _csv_text(value):
    """Neutralise spreadsheet formulas: a text cell opening with = + - @ is
    run as a formula by Excel, and item names are typed by technicians."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return "" if value is None else value


def _sheet(
    sheet: Worksheet,
    title: str,
    stamp: str,
    headers: tuple[str, ...],
    write_ins: tuple[str, ...],
    widths: dict[str, int],
    rows: list[list],
    empty_text: str,
) -> None:
    sheet.title = title
    theme.setup_sheet(sheet, tab_color=theme.BRAND_RED, freeze=f"A{HEADER_ROW + 1}")
    theme.set_widths(sheet, widths)
    theme.title_block(sheet, title, [f"{stamp}  ·  {len(rows)} rows", SIGN_OFF])
    theme.header_row(sheet, HEADER_ROW, headers + write_ins)
    # The header repeats at the top of every printed page.
    sheet.print_title_rows = f"{HEADER_ROW}:{HEADER_ROW}"
    if rows:
        last = theme.write_rows(sheet, HEADER_ROW + 1, rows, alignment=_WRAP)
        for row in range(HEADER_ROW + 1, last + 1):
            sheet.row_dimensions[row].height = _ROW_HEIGHT
            for column in range(len(headers) + 1, len(headers) + len(write_ins) + 1):
                cell = sheet.cell(row=row, column=column)
                cell.fill = _WRITE_IN_FILL
                cell.border = _WRITE_IN_BORDER
    else:
        theme.empty_state(sheet, HEADER_ROW + 1, empty_text)


def _notes_text(item: Item) -> str:
    return "; ".join(f"{key}: {value}" for key, value in (item.notes or {}).items())


def _item_cells(item: Item, low: bool) -> list:
    return [
        item.name,
        item.barcode,
        _number(item.quantity),
        "LOW" if low else None,
        item.location,
        _notes_text(item) or None,
    ]


def _request_cells(request: UserRequest) -> list:
    details = request.details or {}
    work_order = (
        request.work_order.number if request.work_order
        else details.get("work_order_number")
        or ", ".join(details.get("work_order_numbers") or []) or None
    )
    return [
        _when(request.created_at),
        request.status,
        request.item.name if request.item else details.get("searched_text"),
        request.item.barcode if request.item else None,
        _number(details.get("quantity") or details.get("shortage_quantity")),
        work_order,
        request.creator.full_name if request.creator else None,
        details.get("note") or request.message,
    ]


def _number(value) -> Optional[float]:
    return None if value in (None, "") else float(value)


def _when(moment: Optional[datetime]) -> Optional[str]:
    return moment.astimezone(CENTRAL).strftime("%Y-%m-%d %H:%M") if moment else None
