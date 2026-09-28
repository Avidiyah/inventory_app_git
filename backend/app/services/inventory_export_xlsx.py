"""The item list and every User Requests tab as one print-ready workbook.

Layer: services. Reads through the same list services the pages use
(`items.list_items`, `user_requests.list_user_requests`), so the file holds
the rows the screens do. Styling and print setup live in `_xlsx_theme.py`.

Sheets: Items, then one per request type in User Requests tab order. Every
status is included (open, stocked, resolved), with a Status column.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.orm import Session

from app.domain.labor_day import CENTRAL
from app.models import Item, UserRequest
from app.services import _xlsx_theme as theme
from app.services import items as items_service
from app.services import user_requests as request_service

HEADER_ROW = 4
_WRAP = Alignment(wrap_text=True, vertical="top")

ITEM_HEADERS = ("NAME", "BARCODE", "QTY", "LOCATION", "PRICE", "PRODUCT LINK", "NOTES")
ITEM_WIDTHS = {"A": 40, "B": 18, "C": 8, "D": 18, "E": 10, "F": 36, "G": 36}

REQUEST_SHEETS = (
    (request_service.REQUEST_MATERIAL, "Material requests"),
    (request_service.REQUEST_CATALOGUE, "Catalogue requests"),
    (request_service.REQUEST_INVENTORY_RECOUNT, "Stock recounts"),
    (request_service.REQUEST_MISSING_ITEM_PRICE, "Missing price - link"),
)
REQUEST_HEADERS = (
    "FILED", "STATUS", "ITEM", "BARCODE", "QTY", "WORK ORDER",
    "FILED BY", "NOTE", "RESOLVED", "RESOLVED BY", "RESOLUTION",
)
REQUEST_WIDTHS = {
    "A": 16, "B": 10, "C": 34, "D": 16, "E": 8, "F": 14,
    "G": 18, "H": 30, "I": 16, "J": 18, "K": 30,
}


def export_xlsx(db: Session, *, now: datetime) -> bytes:
    workbook = Workbook()
    stamp = f"Exported {_when(now)}"

    items = sorted(items_service.list_items(db), key=lambda item: item.name.casefold())
    _sheet(
        workbook.active, "Items", stamp, ITEM_HEADERS, ITEM_WIDTHS,
        [_item_cells(item) for item in items], "No items.",
    )
    for request_type, title in REQUEST_SHEETS:
        rows = request_service.list_user_requests(db, status=None, request_type=request_type)
        _sheet(
            workbook.create_sheet(), title, stamp, REQUEST_HEADERS, REQUEST_WIDTHS,
            [_request_cells(row) for row in rows], "No requests.",
        )

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def export_filename(now: datetime) -> str:
    return f"inventory-export_{now.astimezone(CENTRAL).date().isoformat()}.xlsx"


def _sheet(
    sheet: Worksheet,
    title: str,
    stamp: str,
    headers: tuple[str, ...],
    widths: dict[str, int],
    rows: list[list],
    empty_text: str,
) -> None:
    sheet.title = title
    theme.setup_sheet(sheet, tab_color=theme.BRAND_RED, freeze=f"A{HEADER_ROW + 1}")
    theme.set_widths(sheet, widths)
    theme.title_block(sheet, title, [stamp, f"{len(rows)} rows"])
    theme.header_row(sheet, HEADER_ROW, headers)
    # The header repeats at the top of every printed page.
    sheet.print_title_rows = f"{HEADER_ROW}:{HEADER_ROW}"
    if rows:
        theme.write_rows(sheet, HEADER_ROW + 1, rows, alignment=_WRAP)
    else:
        theme.empty_state(sheet, HEADER_ROW + 1, empty_text)


def _item_cells(item: Item) -> list:
    notes = "; ".join(f"{key}: {value}" for key, value in (item.notes or {}).items())
    return [
        item.name,
        item.barcode,
        _number(item.quantity),
        item.location,
        _number(item.price),
        item.product_link,
        notes or None,
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
        _when(request.resolved_at),
        request.resolver.full_name if request.resolver else None,
        request.resolution_note,
    ]


def _number(value) -> Optional[float]:
    return None if value in (None, "") else float(value)


def _when(moment: Optional[datetime]) -> Optional[str]:
    return moment.astimezone(CENTRAL).strftime("%Y-%m-%d %H:%M") if moment else None
