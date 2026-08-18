"""Work-order notification triggers: resolve who, then hand off delivery.

Layer: services. The rules are pure and live in
`app.domain.notifications`; this module resolves them against the
database and queues the send. It owns no HTTP concerns and decides no
status codes -- `services.push` does the network, `domain.push` decides
what a response means.

**The split that matters: decide inside the request, deliver outside
it.** Every recipient is resolved while the request's session is alive,
because since FastAPI 0.106 a dependency with `yield` is torn down
*before* background tasks run -- and this repo pins 0.136.3. A task that
captured `db` would find it closed, and a lazy relationship touched in
`_deliver` would raise `DetachedInstanceError`. That failure appears only
in a real deployment: a test driving the handler synchronously never sees
it. So `_deliver` receives plain ids and strings, and opens its own
session for the one write delivery can imply.

Delivery is best-effort, on the same rule `services/realtime.py::emit`
follows: the durable write already happened, and a push problem must
never turn a successful request into an error. Nothing here raises and
no caller checks a result.

Adding a trigger is a documented three-step procedure --
`docs/adding-a-notification-trigger.md` -- and should not require reading
this module.
"""

import logging
import uuid
from typing import Optional, Sequence

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.domain import notifications as policy
from app.models import WorkOrder
from app.services import push as push_service
from app.services import work_orders as wo_service

logger = logging.getLogger(__name__)


def _deliver(user_ids: Sequence[uuid.UUID], title: str, body: str) -> None:
    """Send one already-decided notification. Runs after the response.

    Opens its own session: the request's is closed by the time this runs
    (see the module docstring). Swallows everything -- a push failure
    reaching the server here would be logged as an error for a request
    that actually succeeded.
    """
    session = SessionLocal()
    try:
        result = push_service.send_to_users(session, user_ids, title, body)
        logger.info(
            "notification delivered to %s user(s): sent=%s dropped=%s failed=%s",
            len(user_ids),
            result["sent"],
            result["dropped"],
            result["failed"],
        )
    except Exception:  # noqa: BLE001 - best-effort by contract
        logger.exception("notification delivery failed")
    finally:
        session.close()


def _schedule(
    background: BackgroundTasks,
    user_ids: Sequence[uuid.UUID],
    title: str,
    body: str,
) -> None:
    """Queue a send for after the response, when there is one to make.

    Two silent exits, both ordinary rather than exceptional:

    - **No recipients.** An event whose audience emptied out under actor
      suppression is the common case for a one-person crew.
    - **Push not configured.** A deployment with no VAPID key would queue
      a task that can only fail, once per device, after every response.
    """
    if not user_ids:
        return
    if not push_service.is_configured():
        return
    background.add_task(_deliver, list(user_ids), title, body)


def _dispatch(
    background: BackgroundTasks,
    event_type: str,
    work_order: WorkOrder,
    user_ids: Sequence[uuid.UUID],
) -> None:
    """Build the text for `event_type` and queue it to `user_ids`."""
    title, body = policy.build_message(event_type, number=work_order.number)
    _schedule(background, user_ids, title, body)


def notify_work_order_assigned(
    db: Session,
    background: BackgroundTasks,
    *,
    work_order: WorkOrder,
    actor_id: Optional[uuid.UUID],
) -> None:
    """Requirement 1 -- technicians newly added to a work order.

    Reads the addition set off the row the write returned rather than the
    current assignees: re-saving a form with an unchanged list must stay
    silent, and after the write there is no other way to tell.
    """
    _dispatch(
        background,
        policy.EVENT_WORK_ORDER_ASSIGNED,
        work_order,
        policy.recipients_for_assignment(
            newly_assigned_ids=wo_service.newly_assigned_ids(work_order),
            actor_id=actor_id,
        ),
    )


def notify_work_order_completed(
    db: Session,
    background: BackgroundTasks,
    *,
    work_order: WorkOrder,
    actor_id: Optional[uuid.UUID],
) -> None:
    """Requirement 2 -- Admin and above, minus whoever completed it.

    The audience is resolved to people before it is filtered, because a
    role-addressed send cannot express "everyone at this rank except this
    person" and an Admin completing work through the PATCH would
    otherwise notify themselves.
    """
    _dispatch(
        background,
        policy.EVENT_WORK_ORDER_COMPLETED,
        work_order,
        policy.recipients_for_completion(
            admin_ids=push_service.user_ids_for_min_role(
                db, policy.COMPLETED_AUDIENCE_MIN_ROLE
            ),
            actor_id=actor_id,
        ),
    )


def notify_work_order_reopened(
    db: Session,
    background: BackgroundTasks,
    *,
    work_order: WorkOrder,
    actor_id: Optional[uuid.UUID],
) -> None:
    """Requirement 3 -- a Completed work order came back.

    Assignees because the work is theirs again, and the routed supervisor
    because they own the outcome. Both are read here, while the session is
    alive, for the reason in the module docstring.
    """
    _dispatch(
        background,
        policy.EVENT_WORK_ORDER_REOPENED,
        work_order,
        policy.recipients_for_reopen(
            assignee_ids=wo_service.assigned_technician_ids(work_order),
            supervisor_id=work_order.supervisor_id,
            actor_id=actor_id,
        ),
    )
