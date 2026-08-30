"""Tests for `domain/notifications.py` -- pure, no database.

Recipient selection is where the rules that matter live, and none of them
need a session: actor suppression, de-duplication, and dropping the
`None` that an unrouted supervisor produces. Keeping them testable
without Postgres is the reason this module is separate from the service.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid

import pytest

from app.domain import notifications as notif
from app.domain import roles


# --- select_recipients ---------------------------------------------------

def test_the_actor_is_never_a_recipient():
    actor = uuid.uuid4()
    other = uuid.uuid4()

    assert notif.select_recipients([actor, other], actor_id=actor) == [other]


def test_none_candidates_are_dropped():
    """An unrouted supervisor is `None`, and that is ordinary rather than
    a caller error -- guarding here spares every rule its own check."""
    person = uuid.uuid4()

    assert notif.select_recipients([None, person, None], actor_id=None) == [person]


def test_a_repeated_candidate_is_notified_once():
    person = uuid.uuid4()

    assert notif.select_recipients([person, person], actor_id=None) == [person]


def test_order_is_preserved():
    """Not cosmetic: the dedup keeps the first occurrence, so a rule that
    lists assignees before the supervisor keeps the more specific role."""
    first, second, third = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    assert notif.select_recipients(
        [first, second, third], actor_id=None
    ) == [first, second, third]


def test_an_empty_candidate_list_is_not_an_error():
    assert notif.select_recipients([], actor_id=uuid.uuid4()) == []


def test_suppressing_the_only_candidate_leaves_nobody():
    actor = uuid.uuid4()

    assert notif.select_recipients([actor], actor_id=actor) == []


# --- the three rules -----------------------------------------------------

def test_assignment_addresses_only_the_additions():
    added, actor = uuid.uuid4(), uuid.uuid4()

    assert notif.recipients_for_assignment(
        newly_assigned_ids=[added], actor_id=actor
    ) == [added]


def test_assignment_suppresses_a_self_assignment():
    actor = uuid.uuid4()

    assert notif.recipients_for_assignment(
        newly_assigned_ids=[actor], actor_id=actor
    ) == []


def test_completion_addresses_the_resolved_admins_minus_the_actor():
    admin, acting_admin = uuid.uuid4(), uuid.uuid4()

    assert notif.recipients_for_completion(
        admin_ids=[admin, acting_admin], actor_id=acting_admin
    ) == [admin]


def test_completion_is_addressed_to_admin_and_above():
    """Pinned because the constant is the whole audience rule -- there is
    no query to read it back from."""
    assert notif.COMPLETED_AUDIENCE_MIN_ROLE == roles.ROLE_ADMIN


def test_reopen_addresses_assignees_and_the_supervisor():
    assignee, supervisor, actor = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    assert notif.recipients_for_reopen(
        assignee_ids=[assignee], supervisor_id=supervisor, actor_id=actor
    ) == [assignee, supervisor]


def test_reopen_tolerates_an_unrouted_work_order():
    assignee = uuid.uuid4()

    assert notif.recipients_for_reopen(
        assignee_ids=[assignee], supervisor_id=None, actor_id=None
    ) == [assignee]


def test_reopen_notifies_a_supervising_assignee_once():
    both = uuid.uuid4()

    assert notif.recipients_for_reopen(
        assignee_ids=[both], supervisor_id=both, actor_id=None
    ) == [both]


def test_a_supervisor_reopening_their_own_work_order_is_suppressed():
    supervisor, assignee = uuid.uuid4(), uuid.uuid4()

    assert notif.recipients_for_reopen(
        assignee_ids=[assignee], supervisor_id=supervisor, actor_id=supervisor
    ) == [assignee]


def test_a_return_from_review_addresses_assignees_and_the_supervisor():
    assignee, supervisor, reviewer = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    assert notif.recipients_for_return_from_review(
        assignee_ids=[assignee], supervisor_id=supervisor, actor_id=reviewer
    ) == [assignee, supervisor]


def test_the_reviewer_who_sent_it_back_is_not_told_about_it():
    supervisor, assignee = uuid.uuid4(), uuid.uuid4()

    assert notif.recipients_for_return_from_review(
        assignee_ids=[assignee], supervisor_id=supervisor, actor_id=supervisor
    ) == [assignee]


def test_a_hold_addresses_the_routed_supervisor():
    supervisor, actor = uuid.uuid4(), uuid.uuid4()

    assert notif.recipients_for_hold(
        supervisor_id=supervisor, admin_ids=[], actor_id=actor
    ) == [supervisor]


def test_an_unrouted_hold_falls_back_to_the_admins():
    """Nobody owns the work order, so a stopped job would otherwise be
    silent until someone happened to open the card."""
    first, second = uuid.uuid4(), uuid.uuid4()

    assert notif.recipients_for_hold(
        supervisor_id=None, admin_ids=[first, second], actor_id=None
    ) == [first, second]


def test_an_unrouted_hold_still_suppresses_the_acting_admin():
    admin, acting_admin = uuid.uuid4(), uuid.uuid4()

    assert notif.recipients_for_hold(
        supervisor_id=None, admin_ids=[admin, acting_admin], actor_id=acting_admin
    ) == [admin]


def test_a_supervisor_holding_their_own_work_order_does_not_wake_the_admins():
    """Routed-but-suppressed is not unrouted. The fallback answers "nobody
    owns this", not "the audience came out empty" -- otherwise a supervisor
    pausing their own job escalates it to every Admin by doing so."""
    supervisor, admin = uuid.uuid4(), uuid.uuid4()

    assert notif.recipients_for_hold(
        supervisor_id=supervisor, admin_ids=[admin], actor_id=supervisor
    ) == []


def test_the_unrouted_hold_fallback_is_addressed_to_admin_and_above():
    assert notif.UNROUTED_HOLD_AUDIENCE_MIN_ROLE == roles.ROLE_ADMIN


def test_a_review_hold_reads_differently_from_an_ordinary_hold():
    """Same audience, different job for the supervisor: one is a
    scheduling problem, the other is a review task waiting on them."""
    _, held = notif.build_message(notif.EVENT_WORK_ORDER_HELD, number="WO-1")
    _, for_review = notif.build_message(
        notif.EVENT_WORK_ORDER_HELD_FOR_REVIEW, number="WO-1"
    )

    assert held != for_review


def test_a_return_from_review_reads_differently_from_a_reopen():
    """Same audience, different event. If the two ever collapse into one
    rule, the crew stops being told the difference between "this is live
    again" and "somebody wants this changed"."""
    _, returned = notif.build_message(
        notif.EVENT_WORK_ORDER_RETURNED_FROM_REVIEW, number="WO-1"
    )
    _, reopened = notif.build_message(
        notif.EVENT_WORK_ORDER_REOPENED, number="WO-1"
    )

    assert returned != reopened


# --- message text --------------------------------------------------------

# Every event names one work order except the bulk import send, which
# tallies several and has none to name. The partition is spelled out so a
# new event has to be sorted into one half deliberately;
# `test_every_event_is_either_a_number_event_or_a_count_event` fails if
# somebody adds one and skips that step.
_COUNT_EVENTS = (notif.EVENT_WORK_ORDER_SUPERVISOR_ASSIGNED_BULK,)
# The capture chain's two events build their bodies from several counts and
# a stage word, so they have their own builder
# (`build_netfacilities_chain_message`) rather than a `build_message`
# template -- sorted here deliberately, as this partition demands.
_CHAIN_EVENTS = (
    notif.EVENT_NETFACILITIES_IMPORT_FINISHED,
    notif.EVENT_NETFACILITIES_IMPORT_FAILED,
)
_NUMBER_EVENTS = tuple(
    event
    for event in notif.ALL_EVENTS
    if event not in _COUNT_EVENTS + _CHAIN_EVENTS
)


def test_every_event_is_either_a_number_a_count_or_a_chain_event():
    assert set(_NUMBER_EVENTS) | set(_COUNT_EVENTS) | set(_CHAIN_EVENTS) == set(
        notif.ALL_EVENTS
    )
    assert not set(_NUMBER_EVENTS) & set(_COUNT_EVENTS)
    assert not set(_NUMBER_EVENTS) & set(_CHAIN_EVENTS)
    assert not set(_COUNT_EVENTS) & set(_CHAIN_EVENTS)


@pytest.mark.parametrize("event", _NUMBER_EVENTS)
def test_every_event_has_words_and_names_the_work_order(event):
    title, body = notif.build_message(event, number="WO-1234")

    assert title.strip()
    assert "WO-1234" in body


@pytest.mark.parametrize("event", _COUNT_EVENTS)
def test_a_count_event_has_words_and_states_the_tally(event):
    title, body = notif.build_message(event, count=40)

    assert title.strip()
    assert "40" in body


@pytest.mark.parametrize("event", _NUMBER_EVENTS)
def test_a_message_interpolates_nothing_but_the_number(event):
    """The lock-screen rule, enforced at the signature. `build_message`
    takes a number and a count and no other field, so no future edit can
    quote a customer or an address into a notification without changing
    that contract first -- which is the change worth arguing about."""
    _, body = notif.build_message(event, number="{description}{notes}")

    assert body.count("{description}{notes}") == 1


def test_the_bulk_message_says_nothing_about_any_work_order():
    """A count is allowed past the lock-screen rule precisely because it
    identifies nothing. If this message ever grows a number, a customer, or
    a location, that argument stops holding."""
    _, body = notif.build_message(
        notif.EVENT_WORK_ORDER_SUPERVISOR_ASSIGNED_BULK, count=40, number="WO-1"
    )

    assert "WO-1" not in body


def test_an_unknown_event_raises_rather_than_buzzing_silently():
    """A notification with no words is worse than no notification."""
    with pytest.raises(ValueError):
        notif.build_message("work_order.invented", number="WO-1")


def test_an_event_missing_the_field_its_text_needs_raises():
    """What a caller hits by reaching for the bulk event with one work
    order in hand. Better a logged exception the router swallows than a
    phone buzzing with a literal `{count}`."""
    with pytest.raises(ValueError):
        notif.build_message(
            notif.EVENT_WORK_ORDER_SUPERVISOR_ASSIGNED_BULK, number="WO-1"
        )

    with pytest.raises(ValueError):
        notif.build_message(
            notif.EVENT_WORK_ORDER_SUPERVISOR_ASSIGNED, count=3
        )


# --- the two new rules ---------------------------------------------------

def test_send_back_reaches_the_assignees_and_the_supervisor():
    first = uuid.uuid4()
    second = uuid.uuid4()
    supervisor = uuid.uuid4()

    assert notif.recipients_for_send_back(
        assignee_ids=[first, second],
        supervisor_id=supervisor,
        actor_id=None,
    ) == [first, second, supervisor]


def test_the_supervisor_sending_work_back_is_not_told_about_it():
    worker = uuid.uuid4()
    supervisor = uuid.uuid4()

    assert notif.recipients_for_send_back(
        assignee_ids=[worker],
        supervisor_id=supervisor,
        actor_id=supervisor,
    ) == [worker]


def test_send_back_reads_differently_from_a_reopen_and_a_review_return():
    """Three rules, one audience. The words are the only thing that tells
    a technician whether the work is live again, an Admin wants changes, or
    their own supervisor rejected the handoff -- so collapsing any two of
    these deletes the only thing the recipient needed."""
    bodies = {
        notif.build_message(event, number="WO-1")[1]
        for event in (
            notif.EVENT_WORK_ORDER_SENT_BACK,
            notif.EVENT_WORK_ORDER_REOPENED,
            notif.EVENT_WORK_ORDER_RETURNED_FROM_REVIEW,
        )
    }

    assert len(bodies) == 3


def test_a_routed_supervisor_is_the_whole_audience_for_their_assignment():
    supervisor = uuid.uuid4()

    assert notif.recipients_for_supervisor_assignment(
        supervisor_id=supervisor, actor_id=uuid.uuid4()
    ) == [supervisor]


def test_a_supervisor_claiming_a_work_order_does_not_notify_themselves():
    supervisor = uuid.uuid4()

    assert notif.recipients_for_supervisor_assignment(
        supervisor_id=supervisor, actor_id=supervisor
    ) == []


def test_clearing_the_routing_notifies_nobody():
    """`None` means the work order was un-routed. There is no fallback
    audience here, unlike the hold rules -- the event *is* somebody taking
    ownership, so nobody taking it is not an escalation."""
    assert notif.recipients_for_supervisor_assignment(
        supervisor_id=None, actor_id=uuid.uuid4()
    ) == []


# --- the capture chain's push text (E10, auto-capture spec 2a, 4.6) -------
#
# Locked-screen rule holds: counts and a stage word, never customer detail.


def test_the_chain_success_push_names_the_reconcile_counts():
    title, body = notif.build_netfacilities_chain_message(
        ok=True,
        stage=None,
        import_result={"created": 3, "auto_closed": 14, "reopened": 1},
    )

    assert title == "NetFacilities import finished"
    assert "3 work orders" in body
    assert "14 closed (not in NetFacilities)" in body
    assert "1 reopened" in body
    assert "enrichment started" in body


def test_the_chain_success_push_omits_zero_counts():
    _, body = notif.build_netfacilities_chain_message(
        ok=True, stage=None, import_result={"created": 2}
    )

    assert "closed" not in body
    assert "reopened" not in body


def test_the_chain_import_failure_push_says_to_re_export():
    title, body = notif.build_netfacilities_chain_message(
        ok=False, stage="import", import_result=None
    )

    assert title == "NetFacilities import needs you"
    assert "still signed in" in body
    assert "export" in body.lower()


def test_the_chain_enrichment_failure_push_says_the_import_stood():
    _, body = notif.build_netfacilities_chain_message(
        ok=False, stage="enrichment", import_result={"created": 5}
    )

    assert "5 work orders" in body
    assert "Enrich" in body
