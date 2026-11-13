"""SMR orders as the tile list reads them (2026-11-13).

Layer: services (leaf under `work_orders_smr`). The SMR page tiles every SMR
order on each load; mapping about 11,000 lines, materials and blocks to
objects was most of that request. Here those three collections are plain
rows carrying exactly the fields `tile_for` and the domain rules read; the
order itself and its few labor rows stay mapped.

A field the tile maths starts to read must be added to the matching row
below. `tests/test_smr_tile_orders.py` builds the same orders both ways and
fails when the two part. The card and the workbook export do not come
through here."""

from __future__ import annotations

from collections import defaultdict, namedtuple

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Item,
    SmrCorrectionBlock,
    SmrLaborLine,
    WorkOrder,
    WorkOrderItem,
    WorkOrderLabor,
    WorkOrderLaborSession,
)
from app.models_smr import SmrWorker

_Worker = namedtuple("_Worker", "display_name")
_Line = namedtuple(
    "_Line",
    "work_date date_basis week vendor headcount hours_each kind reason_code status exclusion_ground worker",
)
_Stock = namedtuple("_Stock", "name barcode price")
_Material = namedtuple("_Material", "id item_id quantity billable_quantity created_at item")
_Block = namedtuple("_Block", "version pasted_at lines_digest")


class TileOrder:
    """A mapped SMR order whose `smr_lines`, `items` and `smr_blocks` are
    plain rows; every other attribute is the order's own."""

    def __init__(self, order: WorkOrder, lines: list, items: list, blocks: list):
        self._order = order
        self.smr_lines, self.items, self.smr_blocks = lines, items, blocks

    def __getattr__(self, name):
        return getattr(self._order, name)


def tile_orders(db: Session) -> list[TileOrder]:
    """Every SMR order, archived or not, ready for `tile_for`."""
    is_smr = WorkOrder.smr_imported_at.is_not(None)
    ids = select(WorkOrder.id).where(is_smr)
    orders = db.query(WorkOrder).filter(is_smr).options(
        selectinload(WorkOrder.labor_entries).selectinload(WorkOrderLabor.technician),
        selectinload(WorkOrder.labor_entries).selectinload(WorkOrderLabor.recorded_by),
        selectinload(WorkOrder.labor_sessions).selectinload(WorkOrderLaborSession.technician),
        selectinload(WorkOrder.labor_sessions).selectinload(WorkOrderLaborSession.labor),
        selectinload(WorkOrder.smr_paper_checked_by),
        selectinload(WorkOrder.smr_ready_by),
    ).all()

    line, worker = SmrLaborLine, SmrWorker
    lines = defaultdict(list)
    for row in db.execute(
        select(
            line.work_order_id, line.work_date, line.date_basis, line.week, line.vendor, line.headcount,
            line.hours_each, line.kind, line.reason_code, line.status, line.exclusion_ground,
            line.worker_id, worker.display_name,
        )
        .outerjoin(worker, worker.id == line.worker_id)
        .where(line.work_order_id.in_(ids))
        .order_by(line.created_at)
    ):
        # The worker's name feeds the block digest: without it a block reads stale.
        lines[row[0]].append(_Line(*row[1:11], _Worker(row[12]) if row[11] is not None else None))

    material = WorkOrderItem
    items = defaultdict(list)
    for row in db.execute(
        select(
            material.work_order_id, material.id, material.item_id, material.quantity,
            material.billable_quantity, material.created_at, Item.name, Item.barcode, Item.price,
        )
        .join(Item, Item.id == material.item_id)
        .where(material.work_order_id.in_(ids))
        # No ORDER BY, like the `WorkOrder.items` relationship: `is_edited`
        # compares material lines in order against the baseline, and sorting
        # here flipped `edited` on ten production orders (2026-11-13).
    ):
        items[row[0]].append(_Material(*row[1:6], _Stock(*row[6:9])))

    block = SmrCorrectionBlock
    blocks = defaultdict(list)
    for row in db.execute(
        select(block.work_order_id, block.version, block.pasted_at, block.lines_digest)
        .where(block.work_order_id.in_(ids))
        .order_by(block.version)
    ):
        blocks[row[0]].append(_Block(*row[1:4]))

    return [TileOrder(order, lines[order.id], items[order.id], blocks[order.id]) for order in orders]
