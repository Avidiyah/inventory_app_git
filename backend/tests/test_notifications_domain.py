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

@pytest.mark.parametrize("event", notif.ALL_EVENTS)
def test_every_event_has_words_and_names_the_work_order(event):
    title, body = notif.build_message(event, number="WO-1234")

    assert title.strip()
    assert "WO-1234" in body


@pytest.mark.parametrize("event", notif.ALL_EVENTS)
def test_a_message_interpolates_nothing_but_the_number(event):
    """The lock-screen rule, enforced at the signature. `build_message`
    takes a number and no other field, so no future edit can quote a
    customer or an address into a notification without changing this
    contract first -- which is the change worth arguing about."""
    _, body = notif.build_message(event, number="{description}{notes}")

    assert body.count("{description}{notes}") == 1


def test_an_unknown_event_raises_rather_than_buzzing_silently():
    """A notification with no words is worse than no notification."""
    with pytest.raises(ValueError):
        notif.build_message("work_order.invented", number="WO-1")
