"""SMR27: material keyed on SMR orders during the audit took real stock off the shelf count
(user 2026-11-13). It is a paper backfill of work done months ago, so this puts it right.

In scope: every live stock-moving row on an SMR order (a dispense, or the `adjust` a line
edit wrote) keyed on or after that order's SMR import. Rows keyed before the import
(June-August, live at the time) are not touched.

- Units go back on hand. An item counted by hand since (a count correction: an `adjust`
  with no work order) gets back only the rows keyed after its last count; the count already
  absorbed the earlier ones.
- The rows become stock-neutral, their material lines and every SMR order's entry mode
  become retroactive.
- Open recount requests those rows raised are closed, unless the item is still below zero.
- An open material request on an item that comes back above zero turns stocked, as any
  restock does; no push is sent from here.

Safe to run again: a fixed row no longer moves stock, so it is never picked up twice.
Take a snapshot first and keep the output; the per-item table and row ids are the undo.

Dry run (figures only, no writes) unless --apply; a database that is not local also needs
--not-local.
Run from backend/:  venv\\Scripts\\python.exe scripts\\smr_materials_retroactive.py [--apply] [--not-local]
"""
import sys
sys.path.insert(0, ".")

NOTE = "SMR27 audit entry made retroactive: a paper backfill, no stock left the shelf."


def main():
    flags = set(sys.argv[1:])
    apply = "--apply" in flags
    from collections import defaultdict
    from datetime import datetime, timezone
    from decimal import Decimal

    from sqlalchemy import func, tuple_

    from app.database import SessionLocal, engine
    from app.domain import material_requests as policy
    from app.domain import work_orders as wo
    from app.models import Item, Transaction, UserRequest, WorkOrder, WorkOrderItem
    from app.services import material_requests
    from app.services.user_requests import REQUEST_INVENTORY_RECOUNT

    print(f"database: {engine.url.host}:{engine.url.port}/{engine.url.database}")
    if apply and engine.url.host not in ("localhost", "127.0.0.1") and "--not-local" not in flags:
        sys.exit("not a local database; add --not-local to write there. nothing written")
    db = SessionLocal()

    rows = (
        db.query(Transaction)
        .join(WorkOrder, WorkOrder.id == Transaction.work_order_id)
        .filter(
            WorkOrder.smr_imported_at.isnot(None),
            Transaction.created_at >= WorkOrder.smr_imported_at,
            Transaction.affects_stock.is_(True),
            Transaction.voided_at.is_(None),
            Transaction.transaction_type.in_(("dispense", "adjust")),
        )
        .order_by(Transaction.created_at)
        .all()
    )
    orders = db.query(WorkOrder).filter(
        WorkOrder.smr_imported_at.isnot(None), WorkOrder.entry_mode != wo.MODE_RETROACTIVE
    )
    print(f"orders:   {orders.count()} SMR orders switch to retroactive entry mode")
    print(f"rows:     {len(rows)} stock-moving rows on {len({t.work_order_id for t in rows})} SMR orders")
    if not rows:
        if apply:
            orders.update({WorkOrder.entry_mode: wo.MODE_RETROACTIVE}, synchronize_session=False)
            db.commit()
        return print("no rows to fix" + ("; entry modes written" if apply else " (dry run)"))

    item_ids = {t.item_id for t in rows}
    held = db.query(Item).filter(Item.id.in_(item_ids))
    # On a real run the item rows stay locked until commit, so a live write waits its turn.
    items = {i.id: i for i in (held.with_for_update() if apply else held)}
    last_count = dict(
        db.query(Transaction.item_id, func.max(Transaction.created_at))
        .filter(
            Transaction.item_id.in_(item_ids),
            Transaction.work_order_id.is_(None),
            Transaction.transaction_type == "adjust",
            Transaction.voided_at.is_(None),
        )
        .group_by(Transaction.item_id)
    )

    give, absorbed = defaultdict(Decimal), defaultdict(Decimal)
    for t in rows:
        # A dispense took `quantity` off; an edit `adjust` stores the signed amount it added.
        units = t.quantity if t.transaction_type == "dispense" else -t.quantity
        counted = last_count.get(t.item_id)
        (give if counted is None or t.created_at > counted else absorbed)[t.item_id] += units

    before = {i: items[i].quantity for i in item_ids}
    after = {i: before[i] + give[i] for i in item_ids}
    lines = (
        db.query(WorkOrderItem)
        .filter(
            tuple_(WorkOrderItem.work_order_id, WorkOrderItem.item_id).in_(
                {(t.work_order_id, t.item_id) for t in rows}
            ),
            WorkOrderItem.mode != wo.MODE_RETROACTIVE,
        )
        .all()
    )
    item_of = {t.id: t.item_id for t in rows}
    recounts = (
        db.query(UserRequest)
        .filter(
            UserRequest.transaction_id.in_(list(item_of)),
            UserRequest.request_type == REQUEST_INVENTORY_RECOUNT,
            UserRequest.status == policy.STATUS_OPEN,
        )
        .all()
    )
    closing = [r for r in recounts if after[item_of[r.transaction_id]] >= 0]
    back_in = [i for i in item_ids if policy.restocked(before[i], after[i])]
    waiting = (
        db.query(func.count(UserRequest.id))
        .filter(
            UserRequest.request_type == policy.REQUEST_MATERIAL,
            UserRequest.status == policy.STATUS_OPEN,
            UserRequest.item_id.in_(back_in),
        )
        .scalar()
    )

    print(f"stock:    {sum(give.values())} units go back on {len(item_ids)} items; "
          f"{sum(absorbed.values())} already absorbed by a later hand count")
    print(f"below 0:  {sum(1 for q in before.values() if q < 0)} items now, {sum(1 for q in after.values() if q < 0)} after")
    print(f"lines:    {len(lines)} material lines become retroactive")
    print(f"recounts: {len(closing)} of {len(recounts)} open recount requests close; the rest stay (item still below zero)")
    print(f"requests: {waiting} open material requests turn stocked ({len(back_in)} items come back above zero)")
    print("\nitem | on hand | given back | absorbed by count | after")
    for i in sorted(item_ids, key=lambda i: items[i].name):
        print(f"{items[i].name} | {before[i]} | {give[i]} | {absorbed[i]} | {after[i]}")
    if not apply:
        return print("\ndry run: nothing written (add --apply)")

    print("\nrow ids made stock-neutral:")
    now = datetime.now(timezone.utc)
    for t in rows:
        print(f"{t.id} {t.transaction_type} {t.quantity} item={t.item_id}")
        t.affects_stock = False
    for i in item_ids:
        items[i].quantity = after[i]
        material_requests.record_stock_change(db, items[i], quantity_before=before[i])
    for line in lines:
        line.mode = wo.MODE_RETROACTIVE
    for r in closing:
        r.status, r.resolved_at, r.resolution_note = policy.STATUS_RESOLVED, now, NOTE
    orders.update({WorkOrder.entry_mode: wo.MODE_RETROACTIVE}, synchronize_session=False)
    db.commit()
    print(f"\nwritten: {len(rows)} rows, {sum(give.values())} units back on {len(item_ids)} items")


if __name__ == "__main__":
    main()
