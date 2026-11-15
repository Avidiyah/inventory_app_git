"""Who changed what on a work order: the one writer of W3's stamps.

A save-time conflict names who changed a field and how long ago. Rather than
trust every route to remember, two session events record it for every flush:

- `before_flush` notes each protected `WorkOrder` column whose value really
  changed, each crew row added or removed (field `assigned_to_ids`), and sets
  `updated_by_id` on each changed material line or labor entry.
- `after_flush` upserts the noted stamps. After the flush, so the order row
  already exists and no unit-of-work ordering is involved.

The actor is `session.info["actor_id"]`, set by `get_current_user` on the
request's session. No actor (scripts, background jobs) stamps null.
"""

from datetime import datetime, timezone

from sqlalchemy import event, inspect
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    WorkOrder,
    WorkOrderFieldStamp,
    WorkOrderItem,
    WorkOrderLabor,
    WorkOrderTechnician,
)

STAMPED_COLUMNS = (
    "status",
    "location",
    "service_type",
    "schedule_date",
    "output_to",
    "vendor_assignee",
    "description",
    "priority",
    "supervisor_id",
)
CREW_FIELD = "assigned_to_ids"
_PENDING = "stamp_pending"


@event.listens_for(Session, "before_flush")
def _note_changes(session, flush_context, instances):
    actor = session.info.get("actor_id")
    pending = session.info.setdefault(_PENDING, set())
    new_orders = {obj.id for obj in session.new if isinstance(obj, WorkOrder)}
    for obj in session.dirty:
        if isinstance(obj, WorkOrder):
            attrs = inspect(obj).attrs
            for column in STAMPED_COLUMNS:
                if attrs[column].history.has_changes():
                    pending.add((obj.id, column, actor))
        elif isinstance(obj, (WorkOrderItem, WorkOrderLabor)) and session.is_modified(obj):
            obj.updated_by_id = actor
    for obj in (*session.new, *session.deleted):
        if isinstance(obj, WorkOrderTechnician) and obj.work_order_id not in new_orders:
            pending.add((obj.work_order_id, CREW_FIELD, actor))


@event.listens_for(Session, "after_flush")
def _write_stamps(session, flush_context):
    pending = session.info.pop(_PENDING, None)
    if not pending:
        return
    now = datetime.now(timezone.utc)
    rows = {(wo_id, field): actor for wo_id, field, actor in pending}
    statement = insert(WorkOrderFieldStamp).values(
        [
            {"work_order_id": wo_id, "field": field, "changed_at": now, "changed_by_id": actor}
            for (wo_id, field), actor in rows.items()
        ]
    )
    session.connection().execute(
        statement.on_conflict_do_update(
            index_elements=["work_order_id", "field"],
            set_={"changed_at": now, "changed_by_id": statement.excluded.changed_by_id},
        )
    )
