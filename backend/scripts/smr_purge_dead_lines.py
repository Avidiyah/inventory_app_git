"""SMR27: delete the labor lines that do not bill and every history row (user 2026-11-12:
the card lists labor entries only; old entries and their history go for good).

Deletes every `smr_labor_lines` row whose status is not `charged` (removed and excluded
alike) and every `smr_line_edits` row. A block that matched its order's lines before the
purge is re-stamped with the digest of the lines left, so it does not read "lines changed";
a block that was already stale stays stale. Charged lines are not touched: if their count
or hours move, the run aborts with nothing written.

Nothing here can be undone, and the tagged undo of every earlier bulk run stops working
(they read the history). Take a snapshot first.

Dry run (counts only, no writes) unless --apply; a database that is not local also needs
--not-local.
Run from backend/:  venv\\Scripts\\python.exe scripts\\smr_purge_dead_lines.py [--apply] [--not-local]
"""
import sys
sys.path.insert(0, ".")


def main():
    flags = set(sys.argv[1:])
    from sqlalchemy import func
    from sqlalchemy.orm import selectinload

    from app.database import SessionLocal, engine
    from app.domain import work_orders_smr as smr
    from app.domain.work_orders_smr_block import lines_digest
    from app.domain.work_orders_smr_lines import STATUS_CHARGED
    from app.models import SmrLaborLine, SmrLineEdit, WorkOrder

    print(f"database: {engine.url.host}:{engine.url.port}/{engine.url.database}")
    if "--apply" in flags and engine.url.host not in ("localhost", "127.0.0.1") and "--not-local" not in flags:
        sys.exit("not a local database; add --not-local to write there. nothing written")
    db = SessionLocal()
    hours = func.coalesce(func.sum(SmrLaborLine.headcount * SmrLaborLine.hours_each), 0)

    def figures(charged: bool):
        column = SmrLaborLine.status == STATUS_CHARGED
        return tuple(db.query(func.count(SmrLaborLine.id), hours).filter(column if charged else ~column).one())

    keep, dead = figures(True), figures(False)
    edits = db.query(func.count(SmrLineEdit.id)).scalar()
    print(f"keep:   {keep[0]} charged lines, {keep[1]} h")
    print(f"delete: {dead[0]} lines that do not bill ({dead[1]} h on them), {edits} history rows")

    orders = (
        db.query(WorkOrder).filter(WorkOrder.smr_imported_at.isnot(None))
        .options(selectinload(WorkOrder.smr_lines).selectinload(SmrLaborLine.worker), selectinload(WorkOrder.smr_blocks))
        .all()
    )
    latest = [(order, max(order.smr_blocks, key=lambda b: b.version)) for order in orders if order.smr_blocks]
    current = [(order, block) for order, block in latest if block.lines_digest == lines_digest(smr.correction_lines(order))]
    print(f"blocks: {len(current)} of {len(latest)} match their lines now and are re-stamped; the rest stay stale")
    if "--apply" not in flags:
        return print("dry run: nothing written (add --apply)")

    db.query(SmrLineEdit).delete(synchronize_session=False)
    db.query(SmrLaborLine).filter(SmrLaborLine.status != STATUS_CHARGED).delete(synchronize_session=False)
    db.expire_all()
    for order, block in current:
        block.lines_digest = lines_digest(smr.correction_lines(order))
    db.flush()
    if figures(True) != keep or figures(False)[0] or db.query(func.count(SmrLineEdit.id)).scalar():
        db.rollback()
        sys.exit("the charged lines moved or rows were left behind; rolled back, nothing written")
    db.commit()
    print(f"written: {figures(True)[0]} lines left, {figures(True)[1]} h charged, 0 history rows")


if __name__ == "__main__":
    main()
