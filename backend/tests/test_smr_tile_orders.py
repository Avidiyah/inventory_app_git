"""Guards for the SMR tiles' row loader (`work_orders_smr_tile_orders`,
2026-11-13). The tile list reads lines, materials and blocks as plain rows
for speed; the card and the export keep the mapped objects. These tests pin
the three ways the two paths could part: a tile that differs from the one
the objects build, a block that reads stale because a row lost its worker,
and a per-order query creeping back in."""

from __future__ import annotations

import uuid
from collections import Counter
from decimal import Decimal

from sqlalchemy import event

from app.database import engine
from app.models import Item, WorkOrder, WorkOrderItem
from app.models_smr import SmrWorker
from app.schemas.work_orders_smr_lines import SmrLineEditIn
from app.services import work_orders as wos
from app.services import work_orders_smr as smr_service
from app.services import work_orders_smr_lines as lines_service
from app.services.work_orders_smr_tile_orders import tile_orders
from tests.test_smr_tiles import _breakdown, _line_in, _sheet, _user
from tests.test_work_order_open_queries import _TX_CONTROL


def _order(db, owner, *, target=True):
    number = f"SMR-{uuid.uuid4().hex[:8]}"
    smr_service.import_smr(db, csv_bytes=_sheet([number]), user=owner)
    if target:
        smr_service.import_smr_targets(db, csv_bytes=_breakdown([(number, "1", "$3.00")]), user=owner)
    return wos.find_by_number(db, number)


def _materials(db, owner, order):
    """Three lines: priced, priced with a billing override, and unpriced."""
    for price, billable in ((Decimal("1.50"), None), (Decimal("4.00"), Decimal("0.5")), (None, None)):
        item = Item(barcode=f"BC-{uuid.uuid4().hex[:8]}", name=f"Part {uuid.uuid4().hex[:4]}",
                    quantity=Decimal(100), location="Bay", price=price)
        db.add(item)
        db.flush()
        db.add(WorkOrderItem(work_order_id=order.id, item_id=item.id, quantity=Decimal(2),
                             billable_quantity=billable, mode="retroactive", created_by_id=owner.id))
    db.flush()


def _lines(db, owner, order):
    """A charged line with a named worker, an undated excluded one, a removed one."""
    worker = SmrWorker(display_name=f"Worker {uuid.uuid4().hex[:8]}", vendor="Belfor")
    db.add(worker)
    db.flush()
    lines_service.add_line(db, work_order_id=order.id, payload=_line_in(worker_id=worker.id), user=owner)
    lines_service.add_line(
        db, work_order_id=order.id, user=owner,
        payload=_line_in(work_date=None, hours_each=Decimal("1.0"), status="excluded", exclusion_ground="undated"))
    removed = lines_service.add_line(db, work_order_id=order.id, payload=_line_in(vendor="XXL Construction"), user=owner)
    lines_service.edit_line(db, line_id=removed.id, user=owner,
                            payload=SmrLineEditIn(status="excluded", exclusion_ground="removed", reason="x"))


def _seed(db):
    """One order per shape the tile maths branches on; ids by name."""
    owner = _user(db)
    ids = {}

    pasted = _order(db, owner)
    _materials(db, owner, pasted)
    _lines(db, owner, pasted)
    wos.add_work_order_labor(db, pasted.id, user=owner, technician_id=None, minutes=45)
    wos.add_work_order_labor(db, pasted.id, user=owner, technician_id=owner.id, minutes=30)
    block = lines_service.generate_block(db, work_order_id=pasted.id, user=owner)
    lines_service.mark_pasted(db, block_id=block.id, user=owner)
    smr_service.set_paper_check(db, work_order_id=pasted.id, checked=True, user=owner)
    smr_service.set_ready(db, work_order_id=pasted.id, ready=True, user=owner)
    ids["pasted"] = pasted.id

    stale = _order(db, owner)
    _lines(db, owner, stale)
    lines_service.generate_block(db, work_order_id=stale.id, user=owner)
    lines_service.add_line(db, work_order_id=stale.id, payload=_line_in(hours_each=Decimal("0.5")), user=owner)
    ids["stale"] = stale.id

    materials_only = _order(db, owner, target=False)
    _materials(db, owner, materials_only)
    ids["materials_only"] = materials_only.id

    ids["bare"] = _order(db, owner).id

    archived = _order(db, owner)
    _lines(db, owner, archived)
    wos.archive_work_order(db, archived.id, user=owner)
    ids["archived"] = archived.id

    db.commit()
    return ids


def test_row_built_tiles_equal_object_built_tiles(db):
    ids = _seed(db)
    db.expunge_all()
    views = {view.id: view for view in tile_orders(db)}
    for name, order_id in ids.items():
        from_rows = smr_service.tile_for(views[order_id]).model_dump()
        from_objects = smr_service.tile_for(db.get(WorkOrder, order_id)).model_dump()
        assert from_rows == from_objects, name


def test_a_pasted_block_reads_current_and_a_moved_one_reads_stale(db):
    """The likeliest silent failure: a row without its worker changes the
    digest, and every block on the page turns stale."""
    ids = _seed(db)
    db.expunge_all()
    tiles = {t.id: t for t in smr_service.list_smr_tiles(db).tiles}
    pasted, stale = tiles[ids["pasted"]].lines, tiles[ids["stale"]].lines
    assert (pasted.block_version, pasted.block_stale) == (1, False) and pasted.block_pasted_at is not None
    assert (stale.block_version, stale.block_stale) == (1, True)
    assert tiles[ids["materials_only"]].after_line_count == 3 and tiles[ids["materials_only"]].lines is None
    assert tiles[ids["pasted"]].stage == "ready" and tiles[ids["archived"]].archived_at is not None


def test_the_tile_list_runs_no_per_order_query(db):
    """Five seeded orders: a query that ran once per order would repeat."""
    _seed(db)
    db.expunge_all()
    statements = []

    def listener(conn, cursor, statement, params, context, executemany):
        if not statement.lstrip().upper().startswith(_TX_CONTROL):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", listener)
    try:
        smr_service.list_smr_tiles(db)
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    statement, times = Counter(statements).most_common(1)[0]
    assert times <= 3, f"{times}x {statement[:120]}"
