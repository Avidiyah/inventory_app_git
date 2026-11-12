"""SMR27: one labor entry per person per week on an order (user 2026-11-12).

The post-audit allocation and the 2026-11-11 put-back runs placed hours in 0.5 h pieces and
wrote one charged line per piece, so a person shows several entries on one order in one week.
This merges the charged post-audit allocation lines that share order, week, vendor, person
and kind into the largest of them, which then carries the summed hours; the others are
deleted. Where the merged pieces had other reasons, the kept line's note says so. Paper
lines and weekly-report placements are not touched. Hours per order, week, vendor, person
and kind do not move: if they do, the run aborts with nothing written.

The printed block names no person, so its text does not change; a block that matched its
order's lines before the merge is re-stamped, a stale one stays stale.

Rows are deleted outright (no history, no undo): take a snapshot first. Do not rerun
`smr_line_quality.py allocate` afterwards: it would recreate the merged-away rows.

Dry run unless --apply; a database that is not local also needs --not-local.
Run from backend/:  venv\\Scripts\\python.exe scripts\\smr_merge_person_week.py [selfcheck] [--apply] [--not-local]
"""
import sys
sys.path.insert(0, ".")
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace as NS


def cell(line):
    return (line.work_order_id, line.week, line.vendor, line.worker_id, line.alias_on_paper, line.kind)


def merge_plan(lines):
    """[(kept line, its new hours, [lines to delete])] for every cell holding more than one line."""
    cells = defaultdict(list)
    for line in lines:
        cells[cell(line)].append(line)
    out = []
    for group in cells.values():
        if len(group) > 1:
            group.sort(key=lambda l: (-Decimal(l.hours_each), l.created_at, str(l.id)))
            out.append((group[0], sum((Decimal(l.hours_each) for l in group), Decimal(0)), group[1:]))
    return out


def selfcheck():
    def L(i, hours, worker="w1", kind="field", week=4):
        return NS(id=i, work_order_id="A", week=week, vendor="BT Restoration", worker_id=worker, alias_on_paper=None,
                  kind=kind, hours_each=Decimal(hours), created_at=i)
    lines = [L(1, "0.5"), L(2, "2.5"), L(3, "0.5"), L(4, "0.5", worker="w2"), L(5, "0.5", kind="clean-up"),
             L(6, "0.5", week=5), L(7, "0.5", worker=None), L(8, "1.0", worker=None)]
    got = {keep.id: (hours, [l.id for l in gone]) for keep, hours, gone in merge_plan(lines)}
    # w1's three field lines in Week 4 become the 2.5 h line at 3.5 h; the two nameless lines become one;
    # another person, kind or week stays its own line.
    assert got == {2: (Decimal("3.5"), [1, 3]), 8: (Decimal("1.5"), [7])}, got
    print("selfcheck ok")


def main():
    flags = set(sys.argv[1:])
    if "selfcheck" in flags:
        return selfcheck()
    from sqlalchemy.orm import selectinload

    from app.database import SessionLocal, engine
    from app.domain import work_orders_smr as smr
    from app.domain.work_orders_smr_block import lines_digest, reason_text
    from app.domain.work_orders_smr_lines import ALLOCATION_BASIS, STATUS_CHARGED, validate_line_state
    from app.models import SmrLaborLine, WorkOrder

    print(f"database: {engine.url.host}:{engine.url.port}/{engine.url.database}")
    if "--apply" in flags and engine.url.host not in ("localhost", "127.0.0.1") and "--not-local" not in flags:
        sys.exit("not a local database; add --not-local to write there. nothing written")
    db = SessionLocal()

    def totals():
        out = defaultdict(Decimal)
        for l in db.query(SmrLaborLine).filter(SmrLaborLine.status == STATUS_CHARGED):
            out[cell(l)] += l.headcount * Decimal(l.hours_each)
        return out

    orders = (
        db.query(WorkOrder).filter(WorkOrder.smr_imported_at.isnot(None))
        .options(selectinload(WorkOrder.smr_lines).selectinload(SmrLaborLine.worker), selectinload(WorkOrder.smr_blocks))
        .all()
    )
    latest = [(order, max(order.smr_blocks, key=lambda b: b.version)) for order in orders if order.smr_blocks]
    current = [(order, block) for order, block in latest if block.lines_digest == lines_digest(smr.correction_lines(order))]

    before = totals()
    charged = db.query(SmrLaborLine).filter(SmrLaborLine.status == STATUS_CHARGED).count()
    plan = merge_plan(db.query(SmrLaborLine).filter(
        SmrLaborLine.status == STATUS_CHARGED, SmrLaborLine.date_basis == ALLOCATION_BASIS, SmrLaborLine.headcount == 1).all())
    gone = [l.id for _, _, rest in plan for l in rest]
    print(f"charged: {charged} lines, {sum(before.values())} h")
    print(f"merge:   {len(plan)} entries absorb {len(gone)} others; {charged - len(gone)} lines left, hours unchanged")
    print(f"blocks:  {len(current)} of {len(latest)} match their lines now and are re-stamped; the rest stay stale")
    if "--apply" not in flags:
        return print("dry run: nothing written (add --apply)")

    now = datetime.now(timezone.utc)
    for keep, hours, rest in plan:
        other = defaultdict(Decimal)
        for l in rest:
            if l.reason_code != keep.reason_code:
                other[l.reason_code] += Decimal(l.hours_each)
        if other:
            keep.note = (keep.note or "") + " | includes " + ", ".join(f"{h} h {reason_text(c)}" for c, h in sorted(other.items()))
        keep.hours_each, keep.updated_at = hours, now
        validate_line_state(status=keep.status, work_date=keep.work_date, date_basis=keep.date_basis,
                            exclusion_ground=keep.exclusion_ground, headcount=keep.headcount, hours_each=keep.hours_each,
                            vendor=keep.vendor, kind=keep.kind, reason_code=keep.reason_code, week=keep.week)
    db.flush()
    for i in range(0, len(gone), 500):
        db.query(SmrLaborLine).filter(SmrLaborLine.id.in_(gone[i:i + 500])).delete(synchronize_session=False)
    db.expire_all()
    for order, block in current:
        block.lines_digest = lines_digest(smr.correction_lines(order))
    db.flush()
    after = totals()
    left = db.query(SmrLaborLine).filter(SmrLaborLine.status == STATUS_CHARGED).count()
    if left != charged - len(gone) or any(before[k] != after[k] for k in set(before) | set(after)):
        db.rollback()
        sys.exit("hours moved between orders, weeks, vendors, people or kinds; rolled back, nothing written")
    db.commit()
    print(f"written: {left} charged lines, {sum(after.values())} h")


if __name__ == "__main__":
    main()
