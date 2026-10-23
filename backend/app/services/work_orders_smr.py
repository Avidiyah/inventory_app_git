"""SMR27 audit services (spec docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md).

The Owner-only sheet import that turns every Closed row into a
closed-but-unarchived SMR order with a baseline frozen once. Lives beside `services.work_orders` rather
than inside it because that module is already past three thousand lines."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.domain import work_orders as wo
from app.domain import work_orders_smr as smr
from app.domain.errors import WorkOrderStateError
from app.models import User
from app.schemas.work_orders_smr import SmrImportResult
from app.services import work_orders as wos


# --- import --------------------------------------------------------------

def _read_sheet(csv_bytes: bytes) -> list[dict]:
    """Decode, strip an Excel `sep=,` line, parse every record before any
    write, and insist on the headers the import reads by name."""
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise WorkOrderStateError("SMR sheet must be UTF-8 encoded.") from exc
    stream = io.StringIO(text)
    if stream.readline().strip().casefold() != "sep=,":
        stream.seek(0)
    try:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        missing = [h for h in smr.SMR_REQUIRED_HEADERS if headers.count(h) != 1]
        if missing:
            raise WorkOrderStateError(
                "SMR sheet must include exactly one of each column: " + ", ".join(missing)
            )
        return list(reader)
    except csv.Error as exc:
        raise WorkOrderStateError("SMR sheet could not be parsed.") from exc


def import_smr(db: Session, *, csv_bytes: bytes, user: User) -> SmrImportResult:
    """Import the SMR27 sheet (Owner).

    Per Closed row: an archived match is restored, a live match is
    fill-blanks merged, a new number is created -- all through the same
    `get_or_create_work_order` the mass import uses. Each touched row gets
    `smr_imported_at` once and `smr_baseline` once (the snapshot taken after
    restore and merge, so a re-run can never move the pre-audit record).
    Canceled rows and blank numbers are skipped untouched. The task text is
    the NetFacilities fallback link so the normal enrichment fills it."""
    rows = _read_sheet(csv_bytes)
    supervisors = wos._supervisor_lookup(db)
    now = datetime.now(timezone.utc)
    created = opened = restored = skipped = baselined = 0

    for row in rows:
        parsed = smr.parse_smr_row(row)
        number = parsed["number"]
        if number is None or not parsed["closed"]:
            skipped += 1
            continue

        existing = wos.find_by_number(db, number)
        was_archived = existing is not None and existing.archived_at is not None
        if was_archived:
            existing.archived_at = None
            db.flush()

        attrs = parsed["attrs"]
        key = wo.normalize_assignee_name(attrs.get("vendor_assignee"))
        work_order = wos.get_or_create_work_order(
            db,
            number=number,
            created_by_id=user.id,
            supervisor_id=supervisors.get(key) if key else None,
            description=wo.work_order_task_fallback(number),
            **attrs,
        )
        if was_archived:
            restored += 1
        elif existing is not None:
            opened += 1
        else:
            created += 1

        if work_order.smr_imported_at is None:
            work_order.smr_imported_at = now
        if work_order.smr_baseline is None:
            db.flush()
            db.refresh(work_order)
            work_order.smr_baseline = smr.snapshot(
                work_order, taken_at=now, source_row=parsed["source_row"]
            )
            baselined += 1
        db.commit()

    return SmrImportResult(
        total=created + opened + restored + skipped,
        created=created,
        opened=opened,
        restored=restored,
        skipped=skipped,
        baselined=baselined,
    )
