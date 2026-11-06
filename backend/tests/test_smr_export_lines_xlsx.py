"""The paper-correction record in the Owner's SMR workbook (spec 2026-11-04
`## Export`): nine Orders columns and five sheets (Paper Readings, Labor
Lines, Line History, Correction Blocks, Workers)."""

from __future__ import annotations

import io
import uuid
from datetime import date, datetime
from decimal import Decimal

import openpyxl

from app.domain import roles
from app.domain import work_orders as wo
from app.domain import work_orders_smr_lines as rules
from app.models import SmrLaborLine, SmrLineEdit, User
from app.schemas.work_orders_smr_lines import SmrLineEditIn, SmrLineIn, SmrReadingIn, SmrWorkerIn
from app.services import auth
from app.services import work_orders as wos
from app.services import work_orders_smr as smr_service
from app.services import work_orders_smr_lines as lines_service
from app.services import work_orders_smr_xlsx as xlsx


def _user(db, role=roles.ROLE_OWNER):
    user = User(username=f"u-{uuid.uuid4().hex[:8]}", first_name="Ola", last_name="Owner",
                password_hash=auth.hash_password("x"), role=role)
    db.add(user)
    db.flush()
    return user


def _sheet(numbers):
    head = "WORK ORDER,CREATOR,SERVICE TYPE,SCHEDULE DATE,COMPLETION DATE,ASSIGNED TO,FILED STATUS,LOCATION\r\n"
    rows = "".join(f"{n},Uri,SMR27 - Belfor,05/15/2026,05/21/2026,a,Closed,\"B:1,U 1,x\"\r\n" for n in numbers)
    return (head + rows).encode()


def _book(db):
    return openpyxl.load_workbook(io.BytesIO(xlsx.smr_workbook(db)))


def _rows(sheet, number=None):
    values = list(sheet.iter_rows(values_only=True))
    header = list(values[0])
    rows = [dict(zip(header, row)) for row in values[1:]]
    return header, [r for r in rows if number is None or r["WORK ORDER"] == number]


def _import(db, owner):
    number = f"SMR-{uuid.uuid4().hex[:8]}"
    smr_service.import_smr(db, csv_bytes=_sheet([number]), user=owner)
    return number, wos.find_by_number(db, number)


def _order_with_paper(db, owner):
    """One order: 1.0 h billed before, a reading, a charged line re-read to
    2.5 h, an excluded BT line, a block generated and pasted."""
    number = f"SMR-{uuid.uuid4().hex[:8]}"
    order = wos.get_or_create_work_order(db, number=number, created_by_id=owner.id)
    wos.add_work_order_labor(db, order.id, user=owner, technician_id=owner.id, minutes=60)
    smr_service.import_smr(db, csv_bytes=_sheet([number]), user=owner)
    order = wos.find_by_number(db, number)
    worker = lines_service.add_worker(db, payload=SmrWorkerIn(display_name="Ana Ruiz", vendor="Belfor", alias="A. Ruiz"))
    reading = lines_service.add_reading(db, work_order_id=order.id, payload=SmrReadingIn(
        printing_no=1, work_date=date(2026, 5, 18), hours_as_read=Decimal("3.0"), raw_note="Ana Ruiz 2 h; 1 BT x 1 h"), user=owner)
    charged = lines_service.add_line(db, work_order_id=order.id, payload=SmrLineIn(
        reading_id=reading.id, work_date=date(2026, 5, 18), vendor="Belfor", worker_id=worker.id,
        hours_each=Decimal("2.0"), reason_code="as_read", reason="paper"), user=owner)
    lines_service.add_line(db, work_order_id=order.id, payload=SmrLineIn(
        reading_id=reading.id, work_date=date(2026, 5, 18), vendor="BT Restoration", headcount=1,
        hours_each=Decimal("1.0"), reason_code="as_read", status="excluded",
        exclusion_ground="awaiting invoice (GC, Week 7)", reason="paper"), user=owner)
    lines_service.edit_line(db, line_id=charged.id, payload=SmrLineEditIn(hours_each=Decimal("2.5"), reason="paper re-read"), user=owner)
    block = lines_service.generate_block(db, work_order_id=order.id, user=owner)
    lines_service.mark_pasted(db, block_id=block.id, user=owner)
    db.expire_all()
    return number, wos.find_by_number(db, number), charged.id


def test_smr_export_orders_line_columns(db):
    owner = _user(db)
    number, _, _ = _order_with_paper(db, owner)
    other, other_order = _import(db, owner)
    lines_service.add_reading(db, work_order_id=other_order.id, payload=SmrReadingIn(printing_no=1, raw_note="note only"), user=owner)

    header, rows = _rows(_book(db)["Orders"])
    assert header.index("CORRECTED HOURS") == header.index("PAPER CHECKED BY") + 1
    assert header[header.index("CORRECTED HOURS"):header.index("BLOCK PASTED AT") + 1] == list(xlsx._LINES)
    assert header[-6:] == ["EDITED", "SMR IMPORTED AT", "BASELINE AT", "LAST EDITED AT", "LAST EDITED BY", "ARCHIVED AT"]

    row = next(r for r in rows if r["WORK ORDER"] == number)
    corrected = float(Decimal("2.5") * wo.LABOR_RATE)
    assert row["CORRECTED HOURS"] == 2.5 and row["CORRECTED LABOR $"] == corrected
    assert row["CHANGE HOURS"] == 1.5
    assert row["CHANGE $"] == corrected - row["LABOR TOTAL BEFORE"]
    assert row["EXCLUDED HOURS"] == 1.0 and row["LINES"] == 2 and row["READINGS"] == 1
    assert row["BLOCK VERSION"] == 1 and isinstance(row["BLOCK PASTED AT"], datetime)

    row = next(r for r in rows if r["WORK ORDER"] == other)
    assert [row[h] for h in xlsx._LINES] == [None, None, None, None, None, 0, 1, None, None]


def test_smr_export_paper_sheets(db):
    owner = _user(db)
    number, order, charged_id = _order_with_paper(db, owner)
    # A dateless placement line keyed in the app (no reading, no worker).
    db.add(SmrLaborLine(work_order_id=order.id, work_date=None, date_basis=rules.WEEK_PLACEMENT_BASIS, week=3,
                        vendor="Belfor", hours_each=Decimal("0.5"), reason_code="as_read", status="charged"))
    db.add(SmrLineEdit(line_id=charged_id, edited_by_id=owner.id, field="created", reason="import 0dc2a170e862"))
    db.commit()
    # A second re-read makes v1 stale; v2 is fresh and unpasted.
    lines_service.edit_line(db, line_id=charged_id, payload=SmrLineEditIn(hours_each=Decimal("3.0"), reason="third look"), user=owner)
    lines_service.generate_block(db, work_order_id=order.id, user=owner)

    book = _book(db)
    assert book.sheetnames == ["Orders", "Material Lines", "Labor Entries", "Labor Sessions",
                               "Paper Readings", "Labor Lines", "Line History", "Correction Blocks", "Workers"]

    _, readings = _rows(book["Paper Readings"], number)
    assert len(readings) == 1
    r = readings[0]
    assert (r["PRINTING"], r["HOURS AS READ"], r["WORK DATE"], r["LINES"], r["CREATED BY"]) == (1, 3.0, datetime(2026, 5, 18), 2, "Ola Owner")
    assert r["RAW NOTE"] == "Ana Ruiz 2 h; 1 BT x 1 h"

    _, lines = _rows(book["Labor Lines"], number)
    assert [l["STATUS"] for l in lines] == ["charged", "excluded", "charged"]
    ana, bt, placed = lines
    assert (ana["WORKER"], ana["ALIASES"], ana["HOURS EACH"], ana["HOURS"], ana["PRINTING"], ana["LINE ID"]) == \
        ("Ana Ruiz", "A. Ruiz", 3.0, 3.0, 1, str(charged_id))
    assert (bt["WORKER"], bt["EXCLUSION GROUND"], bt["HOURS"]) == (None, "awaiting invoice (GC, Week 7)", 1.0)
    assert (placed["WORK DATE"], placed["WEEK"], placed["PRINTING"], placed["DATE BASIS"]) == (None, 3, None, rules.WEEK_PLACEMENT_BASIS)

    _, history = _rows(book["Line History"], number)
    mine = [h for h in history if h["LINE ID"] == str(charged_id)]
    assert [h["FIELD"] for h in mine] == ["created", "hours_each", "created", "hours_each"]
    assert (mine[1]["OLD VALUE"], mine[1]["NEW VALUE"], mine[1]["REASON"], mine[1]["RUN ID"], mine[1]["EDITED BY"]) == \
        ("2.0", "2.5", "paper re-read", None, "Ola Owner")
    assert mine[2]["RUN ID"] == "import 0dc2a170e862"

    _, blocks = _rows(book["Correction Blocks"], number)
    assert [(b["VERSION"], b["LATEST"], b["STALE"]) for b in blocks] == [(1, "NO", None), (2, "YES", "NO")]
    assert blocks[0]["PASTED BY"] == "Ola Owner" and blocks[1]["PASTED AT"] is None
    assert number in blocks[1]["TEXT"] and len(blocks[1]["LINES DIGEST"]) == 64

    _, workers = _rows(book["Workers"])
    w = next(w for w in workers if w["NAME"] == "Ana Ruiz")
    assert (w["VENDOR"], w["ALIASES"], w["ADMIN"], w["LINKED USER"], w["ARCHIVED AT"]) == ("Belfor", "A. Ruiz", "NO", None, None)
