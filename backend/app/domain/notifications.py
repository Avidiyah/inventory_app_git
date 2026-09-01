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
actionable, and it is already visible to anyone holding the phone.

The line is **catalogue identifiers, counts, and quantities yes; customer,
job, and price detail no.** `build_message` accepts a `number`, a `count`,
an item `name`, and a `quantity`, and widening it past those is the change
to argue about, not the strings.

`count` was added for the bulk import event: "40 work orders have been
assigned to you" names no work order, no customer, and no job -- a tally
of your own queue discloses nothing to somebody holding the phone that the
badge on the app icon would not.

`name` was added for the low-stock event, and it is the one entry that
looks like a widening rather than an addition. It is not: the rule
protects *customer and job* detail, and an item name is a
catalogue/manufacturer string ("3M Blue Tape") that identifies no person,
site, or job. Without it the notification is unactionable -- nobody reads
a barcode off a lock screen -- so the choice was a useful notification or
none at all. A *price* remains forbidden on the same item.
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
EVENT_WORK_ORDER_SENT_BACK = "work_order.sent_back"
EVENT_WORK_ORDER_SUPERVISOR_ASSIGNED = "work_order.supervisor_assigned"
EVENT_WORK_ORDER_SUPERVISOR_ASSIGNED_BULK = (
    "work_order.supervisor_assigned_bulk"
)
EVENT_NETFACILITIES_IMPORT_FINISHED = "netfacilities.import_finished"
EVENT_NETFACILITIES_IMPORT_FAILED = "netfacilities.import_failed"
EVENT_ITEM_LOW_STOCK = "item.low_stock"

ALL_EVENTS = (
    EVENT_WORK_ORDER_ASSIGNED,
    EVENT_WORK_ORDER_COMPLETED,
    EVENT_WORK_ORDER_REOPENED,
    EVENT_WORK_ORDER_RETURNED_FROM_REVIEW,
    EVENT_WORK_ORDER_HELD,
    EVENT_WORK_ORDER_HELD_FOR_REVIEW,
    EVENT_WORK_ORDER_SENT_BACK,
    EVENT_WORK_ORDER_SUPERVISOR_ASSIGNED,
    EVENT_WORK_ORDER_SUPERVISOR_ASSIGNED_BULK,
    EVENT_NETFACILITIES_IMPORT_FINISHED,
    EVENT_NETFACILITIES_IMPORT_FAILED,
    EVENT_ITEM_LOW_STOCK,
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

# Who hears that the stockroom is running out. TechFM OA and above -- the
# same rank that works the Low Stock page and can retune a threshold, so
# every recipient of the alert can also act on it. A third constant rather
# than a reuse of either above: "who watches the review queue" and "who
# covers an unowned job" are different questions from "who reorders", and
# must be able to diverge without one silently dragging another.
LOW_STOCK_AUDIENCE_MIN_ROLE = roles.ROLE_TECHFM_OA

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
    EVENT_WORK_ORDER_SENT_BACK: (
        "Work order sent back",
        "{number} was sent back and needs more work.",
    ),
    EVENT_WORK_ORDER_SUPERVISOR_ASSIGNED: (
        "Work order assigned to you",
        "{number} has been assigned to you.",
    ),
    EVENT_WORK_ORDER_SUPERVISOR_ASSIGNED_BULK: (
        "Work orders assigned to you",
        "{count} work orders have been assigned to you.",
    ),
    EVENT_ITEM_LOW_STOCK: (
        "Low stock",
        "{name} is down to {quantity}.",
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


def recipients_for_send_back(
    *,
    assignee_ids: Sequence[uuid.UUID],
    supervisor_id: Optional[uuid.UUID],
    actor_id: Optional[uuid.UUID],
) -> list[uuid.UUID]:
    """A supervisor rejected a finished job from Ready to Complete.

    The third rule sharing this audience -- assignees plus the routed
    supervisor -- and, like the reopen/returned pair above, kept separate
    for the only reason that matters on a lock screen. A reopen says the
    work is live again; a return from Review says an Admin wants changes;
    this says the crew's own supervisor did not accept the handoff. The
    technician's next move differs in each case and the words have to say
    which one happened.

    The routed supervisor is in the audience even though they are usually
    the one tapping Send Back -- actor suppression removes them for free
    in that case. The row earns its place when an Admin, or a second
    supervisor, rejects work over the owning supervisor's head: they own
    the outcome and have just had their crew put back on the job.
    """
    return select_recipients(
        [*assignee_ids, supervisor_id], actor_id=actor_id
    )


def recipients_for_supervisor_assignment(
    *,
    supervisor_id: Optional[uuid.UUID],
    actor_id: Optional[uuid.UUID],
) -> list[uuid.UUID]:
    """A work order was routed to a supervisor -- tell that supervisor.

    An audience of exactly one, and deliberately no fallback: unlike the
    hold rules there is no "nobody owns this" case to cover, because the
    event *is* somebody taking ownership. A `None` supervisor means the
    routing was cleared rather than set, and `select_recipients` drops it
    to an empty audience, which is correct -- nobody was assigned.

    A supervisor claiming an unrouted work order for themselves is the
    actor and is suppressed. That is the common case on the PATCH path and
    the reason this goes through `select_recipients` rather than returning
    a one-element list.

    Says nothing to whoever held the routing before. Losing a work order
    is real news and is not sent today; see the registry.
    """
    return select_recipients([supervisor_id], actor_id=actor_id)


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


def recipients_for_low_stock(
    *,
    recipient_ids: Sequence[uuid.UUID],
) -> list[uuid.UUID]:
    """An item fell to or below its threshold -- tell everyone who can act.

    **This rule deliberately does NOT suppress the actor**, and it is the
    only stock-side rule that does not. Every other event reports
    somebody's action to somebody else, where telling the actor what they
    just did is noise. This one is a state alarm about the stockroom: the
    person who just dispensed the last of an item is standing in front of
    the empty shelf and is the single most useful person to tell.

    Expressed by passing `actor_id=None` rather than by skipping
    `select_recipients`, so the dedup and the `None`-dropping still apply
    -- the audience is resolved from a role and can contain neither, but
    a future caller composing this list from several sources gets both
    for free.
    """
    return select_recipients(recipient_ids, actor_id=None)


def build_message(
    event_type: str,
    *,
    number: Optional[str] = None,
    count: Optional[int] = None,
    name: Optional[str] = None,
    quantity: Optional[str] = None,
) -> tuple[str, str]:
    """The `(title, body)` a device will display for one event.

    A work-order `number` and a `count` are the only things interpolated,
    on purpose -- see the module docstring. Both are optional because no
    template uses both: every event names one work order or tallies
    several, never both, and forcing callers to pass a `None` for the one
    they do not have would make the wrong call site look correct.

    Two ways this raises rather than sending something wrong, because a
    buzz with no words is worse than no buzz:

    - an event with no text at all, and
    - an event whose template needs a field this call did not supply,
      which is what a caller reaching for the bulk event with a single
      work order in hand would hit.
    """
    if event_type not in _MESSAGES:
        raise ValueError(f"no notification text for event {event_type!r}")
    title, body = _MESSAGES[event_type]
    supplied = {
        key: value
        for key, value in (
            ("number", number),
            ("count", count),
            ("name", name),
            ("quantity", quantity),
        )
        if value is not None
    }
    try:
        return title, body.format(**supplied)
    except KeyError as exc:
        raise ValueError(
            f"notification text for event {event_type!r} needs {exc.args[0]!r}"
        ) from exc


def build_netfacilities_chain_message(
    *,
    ok: bool,
    stage: Optional[str],
    import_result: Optional[dict],
) -> tuple[str, str]:
    """The `(title, body)` for the unattended capture chain's push (E10).

    Its own builder rather than a `build_message` template: the body is
    several *conditional* count clauses (auto-capture spec 2a) plus a stage
    word, which a single format string cannot express. The lock-screen line
    still holds -- counts and a stage, never customer detail. `auto_closed`
    and `reopened` are read tolerantly so the reconcile sweep's counts
    appear here the moment `WorkOrderImportResult` grows them, with no
    change in this module.

    Deliberately addressed to the acting user (the ceremony's owner): an
    unattended chain's owner is the one person who must hear how it ended,
    tab open or not. That inverts the actor-suppression rule every other
    event follows, and the registry names the inversion.
    """
    counts = import_result or {}
    created = counts.get("created") or 0
    auto_closed = counts.get("auto_closed") or 0
    reopened = counts.get("reopened") or 0
    created_clause = f"Imported {created} work order" + ("" if created == 1 else "s")

    if ok:
        clauses = [created_clause]
        if auto_closed:
            clauses.append(f"{auto_closed} closed (not in NetFacilities)")
        if reopened:
            clauses.append(f"{reopened} reopened (back in NetFacilities)")
        return (
            "NetFacilities import finished",
            " \u00b7 ".join(clauses) + "; enrichment started.",
        )
    if stage == "import":
        return (
            "NetFacilities import needs you",
            "The CSV did not import. You are still signed in, so export the "
            "work-order CSV again and it will import automatically.",
        )
    if stage == "enrichment":
        return (
            "NetFacilities import needs you",
            created_clause + ", but enrichment could not start. Open Work "
            "Orders and click Enrich when it frees up.",
        )
    return (
        "NetFacilities import needs you",
        "The NetFacilities import did not finish. Open Work Orders to see "
        "what to do next.",
    )
