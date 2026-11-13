"""Paper-correction lines on SMR27 orders, after the import (spec
docs/superpowers/specs/2026-11-04-smr-paper-import-design.md, Editor and
Workflow stages 4–5).

Readings and lines are added, lines are edited or deleted, vendor workers
are searched, added and merged, correction blocks are generated and marked
pasted, and the Hours tab is read. Every write checks that the order carries
`smr_imported_at` (400 otherwise, as `set_paper_check` does) and commits
once. A line keeps no history and a deleted line is gone (user 2026-11-12);
`history()` stays for the bulk scripts, whose undo reads their run tag.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.domain import work_orders as wo
from app.domain import receipt
from app.domain import work_orders_smr as smr
from app.domain import work_orders_smr_block as block_rules
from app.domain import work_orders_smr_lines as rules
from app.domain.errors import WorkOrderNotFoundError, WorkOrderStateError
from app.models import (
    SmrCorrectionBlock, SmrLaborLine, SmrLineEdit, SmrPaperReading, SmrWorker, User, WorkOrder, WorkOrderItem,
)
from app.schemas.work_orders_smr_lines import (
    SmrBlockOut,
    SmrRegenerateOut,
    SmrHoursOut,
    SmrHoursRow,
    SmrLineEditIn,
    SmrLineIn,
    SmrLineOut,
    SmrReadingEditIn,
    SmrReadingIn,
    SmrReadingOut,
    SmrWorkerIn,
    SmrWorkerOut,
)

# The editable columns of a line, in the order the history rows are written.
LINE_FIELDS: tuple[str, ...] = (
    "reading_id", "work_date", "date_basis", "vendor", "worker_id", "alias_on_paper", "headcount",
    "hours_each", "kind", "reason_code", "status", "exclusion_ground", "note",
)
UNNAMED = "Skilled Technician"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_smr(order: Optional[WorkOrder]) -> WorkOrder:
    if order is None:
        raise WorkOrderNotFoundError("Work order not found.")
    if order.smr_imported_at is None:
        raise WorkOrderStateError("Only SMR orders carry paper corrections.")
    return order


def smr_order(db: Session, work_order_id: uuid.UUID) -> WorkOrder:
    return _require_smr(db.get(WorkOrder, work_order_id))


# --- history -------------------------------------------------------------

def _text(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def line_json(line: SmrLaborLine) -> str:
    """The whole line as JSON for a `created` / `deleted` history row."""
    return json.dumps(SmrLineOut.from_row(line).model_dump(mode="json"), sort_keys=True)


def history(db: Session, *, line: SmrLaborLine, actor: User, field: str, old: Optional[str],
            new: Optional[str], reason: Optional[str], now: datetime) -> None:
    db.add(SmrLineEdit(
        id=uuid.uuid4(), line_id=line.id, edited_by_id=actor.id, edited_at=now,
        field=field, old_value=old, new_value=new, reason=(reason or None),
    ))


# --- readings ------------------------------------------------------------

def add_reading(db: Session, *, work_order_id: uuid.UUID, payload: SmrReadingIn, user: User) -> SmrReadingOut:
    """Paper read after the import (the post-07/12 orders) enters here; its
    lines are added under it."""
    order = smr_order(db, work_order_id)
    if any(reading.printing_no == payload.printing_no for reading in order.smr_readings):
        raise WorkOrderStateError(f"Printing {payload.printing_no} is already read on this order.")
    row = SmrPaperReading(
        id=uuid.uuid4(), work_order_id=order.id, printing_no=payload.printing_no, work_date=payload.work_date,
        hours_as_read=payload.hours_as_read, raw_note=(payload.raw_note or "").strip(), reviewer=payload.reviewer,
        source=f"added in the app by {user.full_name}", created_at=_now(), created_by_id=user.id,
    )
    db.add(row)
    db.commit()
    return SmrReadingOut.from_row(row)


def edit_reading(db: Session, *, reading_id: uuid.UUID, payload: SmrReadingEditIn, user: User) -> SmrReadingOut:
    """Only the fields in the body change. A printing number already read on
    the order is refused; `printing_no` cannot be cleared. The edit is noted
    on `source` (readings carry no history table)."""
    reading = db.get(SmrPaperReading, reading_id)
    if reading is None:
        raise WorkOrderNotFoundError("Reading not found.")
    order = _require_smr(reading.work_order)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("printing_no", 1) is None:
        raise WorkOrderStateError("A reading keeps its printing number.")
    if "raw_note" in changes:
        changes["raw_note"] = (changes["raw_note"] or "").strip()
    changes = {field: value for field, value in changes.items() if getattr(reading, field) != value}
    if not changes:
        raise WorkOrderStateError("Nothing changed.")
    if "printing_no" in changes and any(r.printing_no == changes["printing_no"] for r in order.smr_readings):
        raise WorkOrderStateError(f"Printing {changes['printing_no']} is already read on this order.")
    for field, value in changes.items():
        setattr(reading, field, value)
    stamp = f"edited in the app by {user.full_name}"
    if stamp not in (reading.source or ""):
        reading.source = f"{reading.source}; {stamp}" if reading.source else stamp
    db.commit()
    # Dating the paper dates its undated lines (user, 2026-11-06): each takes
    # the day, lands in its week and charges itself (D10), with history.
    if changes.get("work_date") is not None:
        undated = [line for line in reading.lines
                   if line.work_date is None and line.exclusion_ground == rules.GROUND_UNDATED]
        for line in undated:
            edit_line(db, line_id=line.id, user=user, payload=SmrLineEditIn(
                work_date=changes["work_date"], reason=f"dated with printing {reading.printing_no}"))
    return SmrReadingOut.from_row(reading)


# --- lines ---------------------------------------------------------------

def _check_state(db: Session, order: WorkOrder, state: dict, *, week: Optional[int] = None) -> None:
    """The status rules, then the two foreign keys the DB cannot judge:
    the worker must be live and of the line's vendor, the reading this
    order's."""
    rules.validate_line_state(
        status=state["status"], work_date=state["work_date"], date_basis=state["date_basis"],
        exclusion_ground=state["exclusion_ground"], headcount=state["headcount"], hours_each=state["hours_each"],
        vendor=state["vendor"], kind=state["kind"], reason_code=state["reason_code"], week=week,
    )
    if state["worker_id"] is not None:
        worker = db.get(SmrWorker, state["worker_id"])
        if worker is None or worker.archived_at is not None:
            raise WorkOrderStateError("Unknown worker (merged away or never added).")
        if worker.vendor != state["vendor"]:
            raise WorkOrderStateError(f"{worker.display_name} works for {worker.vendor}; the line's vendor is {state['vendor']}.")
    if state["reading_id"] is not None:
        reading = db.get(SmrPaperReading, state["reading_id"])
        if reading is None or reading.work_order_id != order.id:
            raise WorkOrderStateError("That reading is not on this order.")


def match_worker(db: Session, *, name: Optional[str], vendor: str) -> Optional[uuid.UUID]:
    """The live worker of `vendor` whose display name or an alias equals the
    keyed `name` (case-insensitive); None when nothing matches. The editor
    has no roster picker: a keyed name links silently or stays unlinked."""
    needle = (name or "").strip().casefold()
    if not needle:
        return None
    for worker in db.query(SmrWorker).filter(SmrWorker.vendor == vendor, SmrWorker.archived_at.is_(None)).all():
        if needle in {n.casefold() for n in [worker.display_name, *(worker.aliases or [])]}:
            return worker.id
    return None


def add_line(db: Session, *, work_order_id: uuid.UUID, payload: SmrLineIn, user: User) -> SmrLineOut:
    order = smr_order(db, work_order_id)
    state = {field: getattr(payload, field) for field in LINE_FIELDS}
    state["kind"] = ", ".join(rules.kinds_of(state["kind"])) or "field"
    rules.require_one_kind(state["kind"])
    if state["worker_id"] is None:
        state["worker_id"] = match_worker(db, name=state["alias_on_paper"], vendor=state["vendor"])
    _check_state(db, order, state)
    now = _now()
    row = SmrLaborLine(
        id=uuid.uuid4(), work_order_id=order.id, week=rules.week_for(state["work_date"], state["date_basis"]),
        created_at=now, created_by_id=user.id, updated_at=now, updated_by_id=user.id, **state,
    )
    db.add(row)
    db.commit()
    return SmrLineOut.from_row(row)


def edit_line(db: Session, *, line_id: uuid.UUID, payload: SmrLineEditIn, user: User) -> SmrLineOut:
    """Only the fields in the body change (an explicit null clears one).
    A date landing on an `undated` line charges it unless the body sets
    `status` itself (D10). `reason` is accepted and ignored: nothing keeps it."""
    line = db.get(SmrLaborLine, line_id)
    if line is None:
        raise WorkOrderNotFoundError("Line not found.")
    order = _require_smr(line.work_order)
    changes = payload.model_dump(exclude_unset=True)
    changes.pop("reason", None)
    week = changes.pop("week", line.week)
    if not changes and week == line.week:
        raise WorkOrderStateError("Nothing to change.")
    if changes.get("work_date") is not None and "status" not in changes:
        status, ground = rules.apply_date(line.status, line.exclusion_ground, changes["work_date"])
        if status != line.status:
            changes["status"], changes["exclusion_ground"] = status, ground
    if "kind" in changes:
        changes["kind"] = ", ".join(rules.kinds_of(changes["kind"])) or "field"
        if changes["kind"] != line.kind:  # a stored mixed line may be re-saved as it is
            rules.require_one_kind(changes["kind"])
    state ={field: getattr(line, field) for field in LINE_FIELDS}
    state.update(changes)
    if "worker_id" not in changes and ("alias_on_paper" in changes or "vendor" in changes):
        changes["worker_id"] = state["worker_id"] = match_worker(db, name=state["alias_on_paper"], vendor=state["vendor"])
    _check_state(db, order, state, week=week)
    diffs = {field: value for field, value in changes.items() if getattr(line, field) != value}
    new_week = rules.week_for(state["work_date"], state["date_basis"], week)
    if not diffs and new_week == line.week:
        raise WorkOrderStateError("Nothing changed.")

    for field, value in diffs.items():
        setattr(line, field, value)
    line.week = new_week
    line.updated_at, line.updated_by_id = _now(), user.id
    db.commit()
    return SmrLineOut.from_row(line)


def delete_line(db: Session, *, line_id: uuid.UUID) -> None:
    """The row is deleted outright (user 2026-11-12): no soft remove, no
    history. The order's block reads as changed until it is generated again."""
    line = db.get(SmrLaborLine, line_id)
    if line is None:
        raise WorkOrderNotFoundError("Line not found.")
    _require_smr(line.work_order)
    db.delete(line)
    db.commit()


# --- workers -------------------------------------------------------------

def search_workers(db: Session, q: Optional[str]) -> list[SmrWorkerOut]:
    """Live workers whose name or any alias contains `q` (case-insensitive);
    every live worker for a blank `q`."""
    needle = (q or "").strip().casefold()
    live = db.query(SmrWorker).filter(SmrWorker.archived_at.is_(None)).order_by(SmrWorker.display_name).all()
    # ponytail: a few dozen workers; the alias match runs in Python over the
    # JSONB array rather than through jsonb_array_elements. A SQL predicate
    # is the upgrade if the table ever grows past a page.
    return [
        SmrWorkerOut.from_row(worker) for worker in live
        if not needle or needle in worker.display_name.casefold()
        or any(needle in alias.casefold() for alias in (worker.aliases or []))
    ]


def add_worker(db: Session, *, payload: SmrWorkerIn) -> SmrWorkerOut:
    """A new `display_name + vendor`, or `alias` appended to the one that
    already carries it. Nobody becomes an app user."""
    name, vendor = payload.display_name.strip(), payload.vendor.strip()
    if not name:
        raise WorkOrderStateError("A worker needs a name.")
    if vendor not in rules.VENDORS:
        raise WorkOrderStateError(f"Unknown vendor: {vendor}.")
    alias = (payload.alias or "").strip() or None
    worker = db.query(SmrWorker).filter(SmrWorker.display_name == name, SmrWorker.vendor == vendor).first()
    if worker is None:
        worker = SmrWorker(
            id=uuid.uuid4(), display_name=name, vendor=vendor, aliases=[alias] if alias else [],
            is_admin=payload.is_admin, user_id=payload.user_id, created_at=_now(),
        )
        db.add(worker)
    elif worker.archived_at is not None:
        raise WorkOrderStateError(f"{name} ({vendor}) was merged into another worker; search for that one.")
    elif alias and alias != name and alias not in (worker.aliases or []):
        worker.aliases = list(worker.aliases or []) + [alias]
    db.commit()
    return SmrWorkerOut.from_row(worker)


def merge_workers(db: Session, *, worker_id: uuid.UUID, into_id: uuid.UUID, reason: str, user: User) -> SmrWorkerOut:
    """Fold `worker_id` into `into_id` (Owner): its lines re-pointed, its name
    and aliases kept as aliases, the row archived. `reason` is not kept."""
    if worker_id == into_id:
        raise WorkOrderStateError("Pick two different workers to merge.")
    duplicate, keep = db.get(SmrWorker, worker_id), db.get(SmrWorker, into_id)
    if duplicate is None or keep is None:
        raise WorkOrderNotFoundError("Worker not found.")
    if keep.archived_at is not None:
        raise WorkOrderStateError(f"{keep.display_name} is archived; merge the other way.")
    now = _now()
    for line in db.query(SmrLaborLine).filter(SmrLaborLine.worker_id == duplicate.id).all():
        line.worker_id, line.updated_at, line.updated_by_id = keep.id, now, user.id
    known = [keep.display_name] + list(keep.aliases or [])
    folded = [name for name in [duplicate.display_name] + list(duplicate.aliases or []) if name not in known]
    keep.aliases = list(keep.aliases or []) + folded
    duplicate.archived_at = now
    db.commit()
    return SmrWorkerOut.from_row(keep)


# --- blocks --------------------------------------------------------------

def latest_block(order: WorkOrder, *, include_price: bool = True) -> Optional[SmrBlockOut]:
    """The highest version, `stale` when the current lines no longer hash
    to the digest it was built from; None before the first generation."""
    found = latest_block_row(order)
    if found is None:
        return None
    latest, stale = found
    return SmrBlockOut.from_row(latest, stale=stale, include_price=include_price)


def latest_block_row(order: WorkOrder):
    """`(block, stale)` for the highest version, None before the first
    generation. Reads only `version` and `lines_digest`, so the tiles can
    load blocks without their text."""
    blocks = list(getattr(order, "smr_blocks", None) or ())
    if not blocks:
        return None
    latest = max(blocks, key=lambda block: block.version)
    return latest, latest.lines_digest != block_rules.lines_digest(smr.correction_lines(order))


def _next_block(order: WorkOrder, *, user: User, now: datetime) -> SmrCorrectionBlock:
    """The order's next block version from its current lines, not yet added."""
    lines = list(order.smr_lines)
    version = max((block.version for block in order.smr_blocks), default=0) + 1
    materials = [
        receipt.ReceiptLine(name=line.item.name, quantity=line.quantity, billable_quantity=line.billable_quantity,
                            unit_price=line.item.price)
        for line in order.items
    ]
    text = block_rules.render_correction_block(
        order.number, order.smr_target, lines, version, now.astimezone(wo.NOTE_TIMEZONE).date(),
        materials=materials, description=order.smr_description,
    )
    return SmrCorrectionBlock(
        id=uuid.uuid4(), work_order_id=order.id, version=version, text=text, generated_at=now,
        generated_by_id=user.id, lines_digest=block_rules.lines_digest(lines),
    )


def generate_block(db: Session, *, work_order_id: uuid.UUID, user: User,
                   description: Optional[str] = None) -> SmrBlockOut:
    """Render the next version from the current lines and keep it, text and
    digest; the date is the note-log timezone's today. A `description`
    replaces the order's work description first (None keeps it)."""
    order = smr_order(db, work_order_id)
    if description is not None:
        order.smr_description = description.strip() or None
    row = _next_block(order, user=user, now=_now())
    db.add(row)
    db.commit()
    return SmrBlockOut.from_row(row, stale=False)


def regenerate_all_blocks(db: Session, *, user: User) -> SmrRegenerateOut:
    """A new block version for every SMR order that carries paper lines,
    archived ones included (user 2026-11-11, after the two-rate change). The
    run's blocks share one `generated_at`, which is how the undo finds them;
    each starts unpasted, so the order returns to the re-paste list."""
    now = _now()
    orders = (
        db.query(WorkOrder).filter(WorkOrder.smr_imported_at.is_not(None))
        .options(selectinload(WorkOrder.smr_lines).selectinload(SmrLaborLine.worker),
                 selectinload(WorkOrder.smr_blocks), selectinload(WorkOrder.items).selectinload(WorkOrderItem.item))
        .all()
    )
    rows = [_next_block(order, user=user, now=now) for order in orders if order.smr_lines]
    db.add_all(rows)
    db.commit()
    return SmrRegenerateOut(count=len(rows), generated_at=now)


def last_regenerate_at(db: Session) -> Optional[datetime]:
    """The newest Regenerate all run that can still be undone, else None."""
    # ponytail: a run is "two or more unpasted blocks sharing a generated_at"; a run over a
    # single order cannot be undone. Add a run id column if that ever matters.
    return (
        db.query(SmrCorrectionBlock.generated_at).filter(SmrCorrectionBlock.pasted_at.is_(None))
        .group_by(SmrCorrectionBlock.generated_at).having(func.count() > 1)
        .order_by(SmrCorrectionBlock.generated_at.desc()).limit(1).scalar()
    )


def undo_regenerate(db: Session) -> SmrRegenerateOut:
    """Delete the newest run's blocks that are still unpasted, so each
    order's previous version is its latest again. A block pasted since the
    run stays: its paste is a fact."""
    stamp = last_regenerate_at(db)
    if stamp is None:
        raise WorkOrderStateError("No Regenerate all run to undo.")
    rows = (db.query(SmrCorrectionBlock)
            .filter(SmrCorrectionBlock.generated_at == stamp, SmrCorrectionBlock.pasted_at.is_(None)).all())
    for row in rows:
        db.delete(row)
    db.commit()
    return SmrRegenerateOut(count=len(rows), generated_at=stamp)


def mark_pasted(db: Session, *, block_id: uuid.UUID, user: User) -> SmrBlockOut:
    """Stamp who pasted the block into NetFacilities and when; a second
    stamp keeps the first."""
    block = db.get(SmrCorrectionBlock, block_id)
    if block is None:
        raise WorkOrderNotFoundError("Correction block not found.")
    order = _require_smr(block.work_order)
    if block.pasted_at is None:
        block.pasted_at, block.pasted_by_id = _now(), user.id
    db.commit()
    stale = block.lines_digest != block_rules.lines_digest(smr.correction_lines(order))
    return SmrBlockOut.from_row(block, stale=stale)


# --- hours ---------------------------------------------------------------

def hours_table(db: Session) -> SmrHoursOut:
    """Worker × week and vendor × week over every line (D3, the dated
    working hours view). Legacy labor entries never enter it."""
    cells: dict[tuple, list] = {}
    for line in db.query(SmrLaborLine).options(selectinload(SmrLaborLine.worker)).all():
        name = line.worker.display_name if line.worker is not None else (line.alias_on_paper or UNNAMED)
        hours = rules.line_hours(line)
        for key in (("worker", name, line.vendor, line.week), ("vendor", line.vendor, line.vendor, line.week)):
            cell = cells.setdefault(key, [Decimal(0), Decimal(0), 0])
            cell[0 if line.status == rules.STATUS_CHARGED else 1] += hours
            cell[2] += 1
    weeks = sorted({key[3] for key in cells if key[3] is not None})
    if any(key[3] is None for key in cells):
        weeks.append(None)
    rows = [
        SmrHoursRow(group=group, name=name, vendor=vendor, week=week, week_label=rules.week_label(week),
                    charged_hours=charged, excluded_hours=excluded, lines=count)
        for (group, name, vendor, week), (charged, excluded, count)
        in sorted(cells.items(), key=lambda item: (item[0][0], item[0][2], item[0][1], item[0][3] is None, item[0][3] or 0))
    ]
    worker_rows = [row for row in rows if row.group == "worker"]
    return SmrHoursOut(
        weeks=weeks, rows=rows,
        charged_hours=sum((row.charged_hours for row in worker_rows), Decimal(0)),
        excluded_hours=sum((row.excluded_hours for row in worker_rows), Decimal(0)),
    )


def hours_csv(db: Session) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(["group", "name", "vendor", "week", "week_label", "charged_hours", "excluded_hours", "lines"])
    for row in hours_table(db).rows:
        writer.writerow([row.group, row.name, row.vendor, "" if row.week is None else row.week, row.week_label,
                         row.charged_hours, row.excluded_hours, row.lines])
    return out.getvalue().encode("utf-8")
