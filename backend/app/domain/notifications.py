"""Pure notification policy: who is told about a work-order event, and in
what words.

Layer: domain. No database, no network, no FastAPI -- every function here
takes ids and returns ids or strings, which is what makes the interesting
rules (actor suppression, de-duplication, the wording that reaches a lock
screen) testable without a session. `services/notifications.py` resolves
these against the database; `services/push.py` delivers.

**Notification text renders on a locked phone.** Nothing built here may
contain a customer name, an address, a job description, note text, or a
price. A work-order *number* is deliberately allowed: it is an opaque
identifier rather than a detail, it is what makes the notification
actionable, and it is already visible to anyone holding the phone. The
line is identifiers yes, human-readable detail no -- which is why
`build_message` accepts a number and nothing else. Widening that
signature is the change to argue about, not the strings.
"""

from typing import Iterable, Optional, Sequence
import uuid

from app.domain import roles

EVENT_WORK_ORDER_ASSIGNED = "work_order.assigned"
EVENT_WORK_ORDER_COMPLETED = "work_order.completed"
EVENT_WORK_ORDER_REOPENED = "work_order.reopened"
EVENT_WORK_ORDER_RETURNED_FROM_REVIEW = "work_order.returned_from_review"
EVENT_WORK_ORDER_HELD = "work_order.held"
EVENT_WORK_ORDER_HELD_FOR_REVIEW = "work_order.held_for_review"

ALL_EVENTS = (
    EVENT_WORK_ORDER_ASSIGNED,
    EVENT_WORK_ORDER_COMPLETED,
    EVENT_WORK_ORDER_REOPENED,
    EVENT_WORK_ORDER_RETURNED_FROM_REVIEW,
    EVENT_WORK_ORDER_HELD,
    EVENT_WORK_ORDER_HELD_FOR_REVIEW,
)

# Completion is the one rule addressed to a rank rather than to named
# people: the Admin review queue is what an Admin watches, and nobody is
# "assigned" to being told. Everything else routes by assignment.
COMPLETED_AUDIENCE_MIN_ROLE = roles.ROLE_ADMIN

# Who hears about a hold on a work order nobody is routed to. Deliberately
# a second constant rather than a reuse of the one above: they answer
# different questions ("who watches the review queue" versus "who covers an
# unowned job") and must be able to diverge without one silently dragging
# the other.
UNROUTED_HOLD_AUDIENCE_MIN_ROLE = roles.ROLE_ADMIN

_MESSAGES = {
    EVENT_WORK_ORDER_ASSIGNED: (
        "Work order assigned",
        "You were assigned to {number}.",
    ),
    EVENT_WORK_ORDER_COMPLETED: (
        "Work order completed",
        "{number} was marked Completed.",
    ),
    EVENT_WORK_ORDER_REOPENED: (
        "Work order reopened",
        "{number} is no longer Completed.",
    ),
    EVENT_WORK_ORDER_RETURNED_FROM_REVIEW: (
        "Work order returned",
        "{number} came back from Review and needs another look.",
    ),
    EVENT_WORK_ORDER_HELD: (
        "Work order on hold",
        "{number} was placed On-Hold.",
    ),
    EVENT_WORK_ORDER_HELD_FOR_REVIEW: (
        "Work order ready for review",
        "{number} is finished and waiting on your review.",
    ),
}


def select_recipients(
    candidates: Iterable[Optional[uuid.UUID]],
    *,
    actor_id: Optional[uuid.UUID],
) -> list[uuid.UUID]:
    """Turn a candidate list into the people who should actually be told.

    Drops `None` -- an unrouted supervisor and an unassigned work order
    are both ordinary, and letting them fall out here spares every rule
    from guarding its own inputs. De-duplicates while preserving order,
    because a supervisor who is also an assignee is one person and must
    not receive two notifications.

    Removes `actor_id` last: the person who caused an event does not need
    to be told it happened, and suppressing it centrally means a rule
    that *wants* to notify the actor has to say so explicitly rather than
    acquiring the behavior by forgetting.

    Suppression is by id, never by role -- a supervisor completing work on
    someone else's behalf is as much the actor as a technician is.
    """
    chosen: list[uuid.UUID] = []
    for candidate in candidates:
        if candidate is None or candidate == actor_id or candidate in chosen:
            continue
        chosen.append(candidate)
    return chosen


def recipients_for_assignment(
    *,
    newly_assigned_ids: Sequence[uuid.UUID],
    actor_id: Optional[uuid.UUID],
) -> list[uuid.UUID]:
    """Requirement 1 -- the people this write *added* to a work order.

    Only the additions, never the full assignee set: re-saving a form
    with an unchanged list would otherwise re-notify everyone on it.
    """
    return select_recipients(newly_assigned_ids, actor_id=actor_id)


def recipients_for_completion(
    *,
    admin_ids: Sequence[uuid.UUID],
    actor_id: Optional[uuid.UUID],
) -> list[uuid.UUID]:
    """Requirement 2 -- Admin and above, minus whoever completed it.

    Takes resolved ids rather than a role so the actor can be removed. A
    role-addressed send has no way to express "everyone at this rank
    except this person", and an Admin who completes a work order through
    the PATCH would otherwise notify themselves.
    """
    return select_recipients(admin_ids, actor_id=actor_id)


def recipients_for_reopen(
    *,
    assignee_ids: Sequence[uuid.UUID],
    supervisor_id: Optional[uuid.UUID],
    actor_id: Optional[uuid.UUID],
) -> list[uuid.UUID]:
    """Requirement 3 -- a Completed work order came back.

    The assigned technicians because the work is theirs again, and the
    routed supervisor because they own the outcome and are usually the
    one who has to react. Ordered assignees-first so the dedup keeps a
    supervisor who is also an assignee in the more specific position.
    """
    return select_recipients(
        [*assignee_ids, supervisor_id], actor_id=actor_id
    )


def recipients_for_return_from_review(
    *,
    assignee_ids: Sequence[uuid.UUID],
    supervisor_id: Optional[uuid.UUID],
    actor_id: Optional[uuid.UUID],
) -> list[uuid.UUID]:
    """A reviewer sent the work back for corrections.

    The same audience as a reopen -- the assigned technicians and the
    routed supervisor -- but a separate rule rather than a shared one,
    because the two events differ in the only way that matters to the
    person holding the phone. A reopen says the work is live again; this
    says somebody looked at it and wants it changed. Keeping them apart
    also lets the audiences diverge later without untangling a caller.
    """
    return select_recipients(
        [*assignee_ids, supervisor_id], actor_id=actor_id
    )


def recipients_for_hold(
    *,
    supervisor_id: Optional[uuid.UUID],
    admin_ids: Sequence[uuid.UUID],
    actor_id: Optional[uuid.UUID],
) -> list[uuid.UUID]:
    """A work order stopped -- tell whoever owns it that it did.

    The routed supervisor owns a routed work order and is the whole
    audience for one. Assignees are deliberately excluded: on the hold
    paths that matter they are either the actor or people who already know
    the job stopped, and a hold is not an instruction to anyone.

    When the work order is **unrouted** nobody owns it, so the alert goes
    to `admin_ids` instead rather than nowhere.

    Routed-but-suppressed is not unrouted. A supervisor who holds their own
    job takes the `supervisor_id` branch and comes back empty -- they must
    not escalate their own pause to every Admin in the company by taking
    it. The branch is on who is routed, never on how many recipients
    survived.
    """
    if supervisor_id is not None:
        return select_recipients([supervisor_id], actor_id=actor_id)
    return select_recipients(admin_ids, actor_id=actor_id)


def build_message(event_type: str, *, number: str) -> tuple[str, str]:
    """The `(title, body)` a device will display for one event.

    `number` is the only thing interpolated, on purpose -- see the module
    docstring. An unknown event type raises rather than sending an empty
    notification, since a buzz with no words is worse than no buzz.
    """
    if event_type not in _MESSAGES:
        raise ValueError(f"no notification text for event {event_type!r}")
    title, body = _MESSAGES[event_type]
    return title, body.format(number=number)
