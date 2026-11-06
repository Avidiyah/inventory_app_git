"""The Owner-only SMR27 paper import (spec
docs/superpowers/specs/2026-11-04-smr-paper-import-design.md, §Import).

Same shape as `import_smr_targets`: the two CSVs (`paper_readings.csv`,
`paper_lines.csv`) and an optional Breakdown CSV are decoded through
`_read_sheet`, every row is parsed, cross-checked and tie-checked before the
first write, then readings, lines, workers, one `created` history row per
line and the paper-check mark are written and committed once.

Idempotent: readings are keyed by `(work_order, printing_no)` and lines by
the CSV `line_id` (`import_key`); a rerun of the same files writes nothing,
and a row that arrives changed is refused and named rather than merged.
After the first successful run the route is for recovery; edits happen in
the app (D2).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.domain import work_orders as wo
from app.domain import work_orders_smr as smr
from app.domain import work_orders_smr_lines as rules
from app.domain.errors import WorkOrderStateError
from app.models import SmrLaborLine, SmrPaperReading, SmrWorker, User, WorkOrder
from app.schemas.work_orders_smr_lines import SmrPaperImportResult
from app.services import work_orders as wos
from app.services import work_orders_smr as smr_service
from app.services.work_orders_smr_lines import history, line_json

CREATED_BY_IMPORT = "created by paper import"
_LINE_FIELDS = (
    "work_date", "date_basis", "vendor", "alias_on_paper", "headcount", "hours_each",
    "kind", "reason_code", "status", "exclusion_ground", "note",
)


def run_identifier(*files: bytes) -> str:
    digest = hashlib.sha256()
    for data in files:
        digest.update(data)
    return f"import {digest.hexdigest()[:12]}"


def _parse(readings_bytes: bytes, lines_bytes: bytes, breakdown_bytes: Optional[bytes]):
    readings = [
        rules.parse_reading_row(row)
        for row in smr_service._read_sheet(readings_bytes, required=rules.READING_REQUIRED_HEADERS)
    ]
    lines = [
        rules.parse_line_row(row)
        for row in smr_service._read_sheet(lines_bytes, required=rules.LINE_REQUIRED_HEADERS)
    ]
    breakdown: dict[str, dict] = {}
    if breakdown_bytes:
        for row in smr_service._read_sheet(breakdown_bytes, required=smr.TARGET_REQUIRED_HEADERS):
            parsed = smr.parse_target_row(row)
            if parsed is not None:
                breakdown[parsed["number"]] = parsed  # last row wins, as the targets import does
    return readings, lines, breakdown


def _cross_check(readings: list[dict], lines: list[dict]) -> dict[str, list[dict]]:
    """Every id unique, every line under a reading of the same order, every
    reading's lines tying to its hours. Returns lines grouped by reading."""
    by_id: dict[str, dict] = {}
    printings: set[tuple[str, int]] = set()
    for reading in readings:
        if reading["reading_id"] in by_id:
            raise WorkOrderStateError(f"Reading id {reading['reading_id']} appears twice.")
        key = (reading["wo"], reading["printing_no"])
        if key in printings:
            raise WorkOrderStateError(f"WO {key[0]} printing {key[1]} appears twice in the readings.")
        by_id[reading["reading_id"]] = reading
        printings.add(key)

    grouped: dict[str, list[dict]] = {reading_id: [] for reading_id in by_id}
    seen: set[str] = set()
    for line in lines:
        if line["line_id"] in seen:
            raise WorkOrderStateError(f"Line id {line['line_id']} appears twice.")
        seen.add(line["line_id"])
        reading = by_id.get(line["reading_id"])
        if reading is None:
            raise WorkOrderStateError(
                f"Line {line['line_id']}: reading {line['reading_id']} is not in the readings file."
            )
        if reading["wo"] != line["wo"]:
            raise WorkOrderStateError(
                f"Line {line['line_id']}: WO {line['wo']} differs from its reading's WO {reading['wo']}."
            )
        grouped[line["reading_id"]].append(line)

    failures = [
        failure for reading in readings
        if (failure := rules.check_tie(reading, grouped[reading["reading_id"]])) is not None
    ]
    if failures:
        raise WorkOrderStateError("Lines do not tie to the paper. " + " ".join(str(f) for f in failures))
    return grouped


def _resolve_orders(db: Session, numbers: set[str], breakdown: dict[str, dict]):
    """SMR orders by number, and the Breakdown rows for numbers to create
    (D11). A number in neither aborts, named."""
    found: dict[str, WorkOrder] = {}
    to_create: dict[str, dict] = {}
    missing: list[str] = []
    not_smr: list[str] = []
    for number in sorted(numbers):
        existing = wos.find_by_number(db, number)
        if existing is not None and existing.smr_imported_at is not None:
            found[number] = existing
        elif existing is not None:
            not_smr.append(number)
        elif number in breakdown:
            to_create[number] = breakdown[number]
        else:
            missing.append(number)
    if not_smr:
        raise WorkOrderStateError("Not SMR orders: " + ", ".join(not_smr) + ".")
    if missing:
        where = "the app or the Breakdown upload" if breakdown else "the app (upload the Breakdown sheet to create them)"
        raise WorkOrderStateError(f"Not in {where}: " + ", ".join(missing) + ".")
    return found, to_create


def _already_imported(db: Session, found: dict[str, WorkOrder], lines: list[dict]):
    order_ids = [order.id for order in found.values()]
    readings = {
        (row.work_order_id, row.printing_no): row
        for row in db.query(SmrPaperReading).filter(SmrPaperReading.work_order_id.in_(order_ids)).all()
    } if order_ids else {}
    keys = [line["line_id"] for line in lines]
    existing_lines = {
        row.import_key: row
        for row in db.query(SmrLaborLine).filter(SmrLaborLine.import_key.in_(keys)).all()
    } if keys else {}
    return readings, existing_lines


def _reading_differs(row: SmrPaperReading, parsed: dict) -> bool:
    return (row.work_date, row.hours_as_read, row.raw_note) != (
        parsed["work_date"], parsed["hours_as_read"], parsed["raw_note"],
    )


def _line_differs(row: SmrLaborLine, parsed: dict) -> bool:
    if any(getattr(row, field) != parsed[field] for field in _LINE_FIELDS):
        return True
    return (row.worker.display_name if row.worker is not None else None) != parsed["worker"]


def _create_order(db: Session, *, number: str, target: dict, user: User, now: datetime) -> WorkOrder:
    """A reviewed order the app never had, from its Breakdown row (D11)."""
    source = target["source_row"]
    order = wos.get_or_create_work_order(
        db,
        number=number,
        created_by_id=user.id,
        service_type=smr.SMR_SERVICE_TYPE,
        unit_number=source.get("Unit#") or None,
        description=wo.work_order_task_fallback(number),
    )
    # ponytail: get_or_create_work_order commits on its own, so a shell
    # created here outlives a failure later in this run; a rerun finds it as
    # an SMR order and carries on. Hand-rolling the insert is the fix if
    # that ever matters.
    order.smr_imported_at = now
    db.flush()
    db.refresh(order)
    order.smr_baseline = smr.snapshot(
        order, taken_at=now,
        source_row={"WORK ORDER": number, "CREATOR": CREATED_BY_IMPORT, "SERVICE TYPE": smr.SMR_SERVICE_TYPE},
    )
    order.smr_target = smr.target_record(target, imported_at=now)
    return order


def import_paper(
    db: Session, *, readings_bytes: bytes, lines_bytes: bytes, breakdown_bytes: Optional[bytes] = None, user: User,
) -> SmrPaperImportResult:
    run_id = run_identifier(readings_bytes, lines_bytes)
    readings, lines, breakdown = _parse(readings_bytes, lines_bytes, breakdown_bytes)
    _cross_check(readings, lines)
    found, to_create = _resolve_orders(db, {reading["wo"] for reading in readings}, breakdown)
    existing_readings, existing_lines = _already_imported(db, found, lines)

    changed = [
        f"reading {reading['reading_id']}" for reading in readings
        if reading["wo"] in found
        and (row := existing_readings.get((found[reading["wo"]].id, reading["printing_no"]))) is not None
        and _reading_differs(row, reading)
    ] + [
        f"line {line['line_id']}" for line in lines
        if (row := existing_lines.get(line["line_id"])) is not None and _line_differs(row, line)
    ]
    if changed:
        raise WorkOrderStateError(
            "Already imported with different values; edit them in the app instead: "
            + ", ".join(changed[:20]) + (f" and {len(changed) - 20} more" if len(changed) > 20 else "") + "."
        )

    now = datetime.now(timezone.utc)
    created_numbers: list[str] = []
    for number, target in to_create.items():
        found[number] = _create_order(db, number=number, target=target, user=user, now=now)
        created_numbers.append(number)

    reading_rows: dict[str, SmrPaperReading] = {}
    new_readings = skipped_readings = 0
    for reading in readings:
        order = found[reading["wo"]]
        row = existing_readings.get((order.id, reading["printing_no"]))
        if row is not None:
            skipped_readings += 1
            reading_rows[reading["reading_id"]] = row
            continue
        source = f"paper_review.csv row {reading['csv_row']}, {run_id}" if reading["csv_row"] else run_id
        if reading["wo"] in to_create:
            source += f"; {CREATED_BY_IMPORT}"
        row = SmrPaperReading(
            id=uuid.uuid4(), work_order_id=order.id, printing_no=reading["printing_no"],
            work_date=reading["work_date"], hours_as_read=reading["hours_as_read"], raw_note=reading["raw_note"],
            reviewer=reading["reviewer"], source=source, created_at=now, created_by_id=user.id,
        )
        db.add(row)
        reading_rows[reading["reading_id"]] = row
        new_readings += 1

    workers = {(w.display_name, w.vendor): w for w in db.query(SmrWorker).all()}
    workers_created = 0
    new_lines: list[SmrLaborLine] = []
    skipped_lines = 0
    for line in lines:
        if line["line_id"] in existing_lines:
            skipped_lines += 1
            continue
        worker = None
        if line["worker"]:
            key = (line["worker"], line["vendor"])
            worker = workers.get(key)
            if worker is None:
                worker = SmrWorker(
                    id=uuid.uuid4(), display_name=line["worker"], vendor=line["vendor"], aliases=[],
                    is_admin=line["vendor"] == "Admin", created_at=now,
                )
                db.add(worker)
                workers[key] = worker
                workers_created += 1
            alias = line["alias_on_paper"]
            if alias and alias != worker.display_name and alias not in (worker.aliases or []):
                worker.aliases = list(worker.aliases or []) + [alias]
        row = SmrLaborLine(
            id=uuid.uuid4(), work_order_id=found[line["wo"]].id, reading_id=reading_rows[line["reading_id"]].id,
            import_key=line["line_id"], work_date=line["work_date"], date_basis=line["date_basis"],
            week=line["week"], vendor=line["vendor"], worker_id=worker.id if worker is not None else None,
            alias_on_paper=line["alias_on_paper"], headcount=line["headcount"], hours_each=line["hours_each"],
            kind=line["kind"], reason_code=line["reason_code"], status=line["status"],
            exclusion_ground=line["exclusion_ground"], note=line["note"],
            created_at=now, created_by_id=user.id, updated_at=now, updated_by_id=user.id,
        )
        db.add(row)
        new_lines.append(row)
    db.flush()
    for row in new_lines:
        history(db, line=row, actor=user, field="created", old=None, new=line_json(row), reason=run_id, now=now)
    for order in found.values():
        if order.smr_paper_checked_at is None:
            order.smr_paper_checked_at = now
            order.smr_paper_checked_by_id = user.id
    db.commit()

    charge = rules.lines_charge(new_lines)
    return SmrPaperImportResult(
        orders=len(found), readings=new_readings, lines=len(new_lines), workers_created=workers_created,
        charged_hours=charge.charged_hours, excluded_hours=charge.excluded_hours,
        created_orders=created_numbers, skipped_readings=skipped_readings, skipped_lines=skipped_lines,
        run_id=run_id,
    )
