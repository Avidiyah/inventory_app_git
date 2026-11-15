"""Save-time conflict check for work-order edits (W3).

A protected save carries the values the person last saw. Under the row lock,
each is compared with the row as it is now; any mismatch refuses the whole
save with `WorkOrderFieldConflictError`, naming the field, its current value,
who changed it and how long ago. The age is computed here, from the server's
clock, so a phone with a wrong clock cannot skew it.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.domain import work_orders as wo
from app.domain.errors import WorkOrderFieldConflictError
from app.models import User, WorkOrder, WorkOrderFieldStamp

BLANK = "(blank)"

DETAIL_LABELS = {
    "status": "Status",
    "location": "Location",
    "service_type": "Service type",
    "schedule_date": "Schedule date",
    "output_to": "Output to",
    "vendor_assignee": "Vendor contact",
    "description": "Symptom / task",
    "priority": "Priority",
    "supervisor_id": "Team Lead",
    "assigned_to_ids": "Assigned technicians",
}


def _text(value) -> Optional[str]:
    # ponytail: line breaks are ignored because <input type="text"> drops them
    # and a textarea turns CRLF into LF; a change only in line breaks is missed.
    return (value or "").replace("\r", "").replace("\n", "").strip() or None


def _name(db: Session, user_id) -> Optional[str]:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    return user.full_name if user is not None else None


def conflict(
    db: Session,
    *,
    field: str,
    label: str,
    current,
    current_label: Optional[str],
    changed_by_id,
    changed_at: Optional[datetime],
) -> dict:
    seconds_ago = None
    if changed_at is not None:
        seconds_ago = max(0, int((datetime.now(timezone.utc) - changed_at).total_seconds()))
    return {
        "field": field,
        "label": label,
        "current": current,
        "current_label": current_label if current_label is not None else BLANK,
        "changed_by": _name(db, changed_by_id),
        "seconds_ago": seconds_ago,
    }


def _current_details(db: Session, work_order: WorkOrder, field: str):
    """(comparable value, wire value, display text) for one protected field."""
    if field == "assigned_to_ids":
        ids = [a.technician_id for a in work_order.technician_assignments]
        names = ", ".join(filter(None, (_name(db, i) for i in ids))) or None
        return set(ids), [str(i) for i in ids], names
    if field == "supervisor_id":
        sid = work_order.supervisor_id
        return sid, (str(sid) if sid else None), _name(db, sid)
    if field == "status":
        return work_order.status, work_order.status, wo.STATUS_LABELS.get(work_order.status, work_order.status)
    value = getattr(work_order, field)
    return _text(value), value, value


def _expected_comparable(field: str, value):
    if field == "assigned_to_ids":
        return set(value or [])
    if field in ("supervisor_id", "status"):
        return value
    return _text(value)


def check_details(db: Session, work_order: WorkOrder, expected: dict) -> None:
    """Refuse the save if any field in `expected` has changed since it was seen."""
    found = []
    for field, seen in expected.items():
        now_value, wire, display = _current_details(db, work_order, field)
        if _expected_comparable(field, seen) == now_value:
            continue
        stamp = db.get(WorkOrderFieldStamp, (work_order.id, field))
        found.append(conflict(
            db,
            field=field,
            label=DETAIL_LABELS[field],
            current=wire,
            current_label=display,
            changed_by_id=stamp.changed_by_id if stamp else None,
            changed_at=stamp.changed_at if stamp else None,
        ))
    if found:
        raise WorkOrderFieldConflictError(found)
