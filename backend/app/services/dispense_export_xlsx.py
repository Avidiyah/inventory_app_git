"""Weekly export: every item dispensed since the previous export, as a
print-ready workbook in the `inventory_export_xlsx` Items layout plus a
DISPENSED column.

Layer: services. Each `create_export` records its window in
`dispense_exports`; the next one starts where the latest ended, so a
dispense prints on exactly one sheet. `latest_export` re-renders the last
window without moving it (Reprint weekly). Voided dispenses are left out.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Optional

from openpyxl import Workbook
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domain.labor_day import CENTRAL
from app.models import DispenseExport, Item, Transaction, User
from app.services import items as items_service
from app.services.inventory_export_xlsx import (
    ITEM_HEADERS, ITEM_WRITE_INS, _item_cells, _number, _sheet, _when,
)

# The first export covers everything dispensed from the day the feature shipped.
FIRST_WINDOW_START = datetime(2026, 9, 28, tzinfo=CENTRAL)
HEADERS = ITEM_HEADERS + ("DISPENSED",)
WIDTHS = {"A": 36, "B": 18, "C": 7, "D": 6, "E": 16, "F": 24, "G": 11, "H": 10, "I": 7, "J": 32}


def create_export(db: Session, *, user: User, now: datetime) -> tuple[bytes, str]:
    latest = _latest(db)
    run = DispenseExport(
        window_start=latest.window_end if latest else FIRST_WINDOW_START,
        window_end=now,
        created_by_id=user.id,
    )
    db.add(run)
    db.commit()
    return _render(db, run)


def latest_export(db: Session) -> Optional[tuple[bytes, str]]:
    latest = _latest(db)
    return _render(db, latest) if latest else None


def _latest(db: Session) -> Optional[DispenseExport]:
    return db.query(DispenseExport).order_by(DispenseExport.window_end.desc()).first()


def _render(db: Session, run: DispenseExport) -> tuple[bytes, str]:
    dispensed = (
        db.query(Item, func.sum(Transaction.quantity))
        .join(Transaction, Transaction.item_id == Item.id)
        .filter(
            Transaction.transaction_type == "dispense",
            Transaction.voided_at.is_(None),
            Transaction.created_at >= run.window_start,
            Transaction.created_at < run.window_end,
        )
        .group_by(Item.id)
        .all()
    )
    low_ids = {item.id for item, _, _ in items_service.list_low_stock(db)}
    rows = [
        _item_cells(item, item.id in low_ids) + [_number(total)]
        for item, total in sorted(dispensed, key=lambda pair: pair[0].name.casefold())
    ]
    workbook = Workbook()
    _sheet(
        workbook.active, "Dispensed items",
        f"Dispensed {_when(run.window_start)} to {_when(run.window_end)}",
        HEADERS, ITEM_WRITE_INS, WIDTHS, rows, "Nothing dispensed.",
    )
    buffer = io.BytesIO()
    workbook.save(buffer)
    day = run.window_end.astimezone(CENTRAL).date().isoformat()
    return buffer.getvalue(), f"weekly-export_{day}.xlsx"
