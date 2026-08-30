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
    """Build the text for `event_type` and queue it to `user_ids`.

    For the events that name one work order, which is all of them but the
    bulk import send -- that one has no single row to name and builds its
    own text from a count.
    """
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


def notify_work_order_returned_from_review(
    db: Session,
    background: BackgroundTasks,
    *,
    work_order: WorkOrder,
    actor_id: Optional[uuid.UUID],
) -> None:
    """A reviewer returned the work order for corrections.

    Distinct from the reopen rule despite sharing an audience: this is the
    one transition where somebody has actively asked the crew to do more,
    so it is worth its own words on a lock screen.
    """
    _dispatch(
        background,
        policy.EVENT_WORK_ORDER_RETURNED_FROM_REVIEW,
        work_order,
        policy.recipients_for_return_from_review(
            assignee_ids=wo_service.assigned_technician_ids(work_order),
            supervisor_id=work_order.supervisor_id,
            actor_id=actor_id,
        ),
    )


def notify_work_order_sent_back(
    db: Session,
    background: BackgroundTasks,
    *,
    work_order: WorkOrder,
    actor_id: Optional[uuid.UUID],
) -> None:
    """A supervisor rejected the crew's handoff from Ready to Complete.

    Third of the three rules addressed to assignees plus the routed
    supervisor, and separate from both for the reason given in the policy
    module: the technician needs to know *why* the work is theirs again,
    and only the words carry that.
    """
    _dispatch(
        background,
        policy.EVENT_WORK_ORDER_SENT_BACK,
        work_order,
        policy.recipients_for_send_back(
            assignee_ids=wo_service.assigned_technician_ids(work_order),
            supervisor_id=work_order.supervisor_id,
            actor_id=actor_id,
        ),
    )


def notify_supervisor_assigned(
    db: Session,
    background: BackgroundTasks,
    *,
    work_order: WorkOrder,
    actor_id: Optional[uuid.UUID],
) -> None:
    """One work order was routed to a supervisor.

    The caller decides whether routing actually *changed* -- this fires on
    the fact, not on the field being present in a PATCH. `newly_routed_
    supervisor_id` is what carries that fact off the write, for the same
    reason `previous_status` does for transitions: the post-write row
    cannot tell a real re-route from a form re-save.
    """
    _dispatch(
        background,
        policy.EVENT_WORK_ORDER_SUPERVISOR_ASSIGNED,
        work_order,
        policy.recipients_for_supervisor_assignment(
            supervisor_id=wo_service.newly_routed_supervisor_id(work_order),
            actor_id=actor_id,
        ),
    )


def notify_netfacilities_chain_finished(
    *,
    user_id: uuid.UUID,
    ok: bool,
    stage: Optional[str],
    import_result: Optional[dict],
    job_id: Optional[uuid.UUID] = None,  # noqa: ARG001 - on the snapshot, not in the text
) -> None:
    """The unattended capture chain's only channel to a user who closed the
    tab (E10).

    Synchronous and immediate, unlike every other notifier here: the chain
    has no request and no `BackgroundTasks`, so there is nothing to queue
    behind -- it calls this off the event loop and `_deliver` opens its own
    session as always. Addressed to the acting user on purpose; the
    registry's actor-suppression rule is deliberately inverted for this one
    event pair (see `docs/notification-events.md`).
    """
    if not push_service.is_configured():
        return
    title, body = policy.build_netfacilities_chain_message(
        ok=ok, stage=stage, import_result=import_result
    )
    _deliver([user_id], title, body)


def notify_supervisors_assigned_bulk(
    db: Session,
    background: BackgroundTasks,
    *,
    routing: dict[uuid.UUID, Sequence[str]],
    actor_id: Optional[uuid.UUID],
) -> None:
    """An import routed a batch of new work orders to their supervisors.

    **The only batched notification in this system**, and the exception is
    argued rather than assumed: an import that creates forty work orders
    for one supervisor would otherwise buzz them forty times in a few
    seconds, which is not a notification but a denial of service aimed at
    the person who most needs to read it. One send per supervisor per
    import.

    A supervisor who matched exactly one work order gets the ordinary
    single-work-order text instead of "1 work orders" -- correct grammar
    is the smaller half of that; naming the number they can act on is the
    larger one.

    Each supervisor is resolved and scheduled independently, so one
    supervisor whose text fails to build cannot silence the rest.
    """
    for supervisor_id, numbers in routing.items():
        user_ids = policy.recipients_for_supervisor_assignment(
            supervisor_id=supervisor_id, actor_id=actor_id
        )
        if not user_ids:
            continue
        if len(numbers) == 1:
            title, body = policy.build_message(
                policy.EVENT_WORK_ORDER_SUPERVISOR_ASSIGNED,
                number=numbers[0],
            )
        else:
            title, body = policy.build_message(
                policy.EVENT_WORK_ORDER_SUPERVISOR_ASSIGNED_BULK,
                count=len(numbers),
            )
        _schedule(background, user_ids, title, body)


def _hold_recipients(
    db: Session,
    work_order: WorkOrder,
    actor_id: Optional[uuid.UUID],
) -> list[uuid.UUID]:
    """Who hears that a work order stopped, for either hold event.

    The Admin query runs only when the work order is unrouted -- a routed
    one never consults the fallback, and every hold would otherwise pay for
    a query whose result is discarded.
    """
    supervisor_id = work_order.supervisor_id
    admin_ids = (
        []
        if supervisor_id is not None
        else push_service.user_ids_for_min_role(
            db, policy.UNROUTED_HOLD_AUDIENCE_MIN_ROLE
        )
    )
    return policy.recipients_for_hold(
        supervisor_id=supervisor_id,
        admin_ids=admin_ids,
        actor_id=actor_id,
    )


def notify_work_order_held(
    db: Session,
    background: BackgroundTasks,
    *,
    work_order: WorkOrder,
    actor_id: Optional[uuid.UUID],
) -> None:
    """A work order was paused, from any of the three routes into On-Hold.

    Says only that the work stopped. The finished-and-waiting case is
    `notify_work_order_held_for_review`, and the difference is the whole
    reason they are two functions.
    """
    _dispatch(
        background,
        policy.EVENT_WORK_ORDER_HELD,
        work_order,
        _hold_recipients(db, work_order, actor_id),
    )


def notify_work_order_held_for_review(
    db: Session,
    background: BackgroundTasks,
    *,
    work_order: WorkOrder,
    actor_id: Optional[uuid.UUID],
) -> None:
    """A technician finished the work; it is parked awaiting review.

    Same audience as an ordinary hold and deliberately a separate event:
    the supervisor's next move is a review task rather than a scheduling
    problem, and that difference has to survive to a lock screen.
    """
    _dispatch(
        background,
        policy.EVENT_WORK_ORDER_HELD_FOR_REVIEW,
        work_order,
        _hold_recipients(db, work_order, actor_id),
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
