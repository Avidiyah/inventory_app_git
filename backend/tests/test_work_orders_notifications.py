"""Route-level tests for the three wired notification triggers.

These drive the real handlers against a real session and read what was
queued onto the response, so they cover the part unit tests cannot: that
the trigger sits at the right site, sees the transition facts the service
stamped, and fires once.

Delivery is still never attempted -- the assertions are about recipients
and about how many tasks were scheduled. `docs/adding-a-notification-trigger.md`
explains why that is the whole job at this layer.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid

import pytest
from fastapi import BackgroundTasks

from app.domain import roles
from app.models import User
from app.routers import work_orders as work_orders_router
from app.schemas.work_orders import WorkOrderUpdate
from app.services import auth
from app.services import notifications as notifications_service
from app.services import push as push_service
from app.services import work_orders as wos


# --- helpers ------------------------------------------------------------

def _seed_user(db, role):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _wo(db, *, created_by, assigned_to=None, supervisor=None):
    return wos.get_or_create_work_order(
        db,
        number=f"WO-{uuid.uuid4().hex[:8]}",
        created_by_id=created_by.id,
        assigned_to_id=assigned_to.id if assigned_to else None,
        supervisor_id=supervisor.id if supervisor else None,
    )


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    return True


def _patch(db, background, work_order_id, *, user, **fields):
    return work_orders_router.update_work_order(
        work_order_id,
        WorkOrderUpdate(**fields),
        background,
        user=user,
        db=db,
    )


def _recipients(background):
    assert len(background.tasks) == 1, f"expected one task, got {len(background.tasks)}"
    return background.tasks[0].args[0]


def _to_completed(db, work_order, *, worker, manager):
    """Walk a work order to Completed the way the app does now.

    A technician's finish stops at Ready to Complete, so reaching Completed
    takes a supervisory PATCH afterwards. Written as one helper because
    almost every rule below needs a Completed row as a *starting point*
    rather than as the thing under test.
    """
    wos.start_work_order(db, work_order.id, user=worker)
    wos.complete_work_order(db, work_order.id, user=worker)
    return wos.update_work_order(
        db, work_order.id, user=manager, fields={"status": "completed"}
    )


# --- requirement 1: assignment ------------------------------------------

def test_assigning_a_technician_notifies_that_technician(db, configured):
    manager = _seed_user(db, roles.ROLE_ADMIN)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=manager)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=manager, assigned_to_ids=[worker.id])

    assert _recipients(background) == [worker.id]


def test_adding_a_second_technician_leaves_the_first_alone(db, configured):
    manager = _seed_user(db, roles.ROLE_ADMIN)
    first = _seed_user(db, roles.ROLE_TECHNICIAN)
    second = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=manager, assigned_to=first)

    background = BackgroundTasks()
    _patch(
        db,
        background,
        work_order.id,
        user=manager,
        assigned_to_ids=[first.id, second.id],
    )

    assert _recipients(background) == [second.id]


def test_a_note_only_edit_notifies_nobody(db, configured):
    manager = _seed_user(db, roles.ROLE_ADMIN)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=manager, assigned_to=worker)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=manager, notes="on my way")

    assert background.tasks == []


# --- requirement 2: completion ------------------------------------------

def test_completing_from_the_walkthrough_notifies_admins(db, configured):
    """A Supervisor working the job reaches Completed directly, so this is
    still the completion event. A Technician's finish is a different event
    entirely -- see the hold rules below."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    worker = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _wo(db, created_by=admin, assigned_to=worker)
    wos.start_work_order(db, work_order.id, user=worker)

    background = BackgroundTasks()
    work_orders_router.complete_work_order(
        work_order.id, background, user=worker, db=db
    )

    assert admin.id in _recipients(background)


def test_completing_twice_notifies_once(db, configured):
    """The double-tap guard, at the site it protects. The second call is a
    valid, successful, idempotent request that changed nothing."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    worker = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _wo(db, created_by=admin, assigned_to=worker)
    wos.start_work_order(db, work_order.id, user=worker)

    first = BackgroundTasks()
    work_orders_router.complete_work_order(work_order.id, first, user=worker, db=db)
    second = BackgroundTasks()
    work_orders_router.complete_work_order(work_order.id, second, user=worker, db=db)

    assert len(first.tasks) == 1
    assert second.tasks == []


# --- a technician's finish is a hold for review -------------------------

def test_a_technicians_finish_alerts_the_routed_supervisor(db, configured):
    """The technician cannot reach Completed, so the event their button
    produces is a review hold addressed to whoever owns the work order."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )
    wos.start_work_order(db, work_order.id, user=worker)

    background = BackgroundTasks()
    work_orders_router.complete_work_order(
        work_order.id, background, user=worker, db=db
    )

    assert _recipients(background) == [supervisor.id]


def test_a_technicians_finish_does_not_tell_the_admins_it_completed(db, configured):
    """The row is Ready to Complete, not Completed. Firing the completion
    rule here would put unreviewed work in front of the Admin review
    queue."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )
    wos.start_work_order(db, work_order.id, user=worker)

    background = BackgroundTasks()
    work_orders_router.complete_work_order(
        work_order.id, background, user=worker, db=db
    )

    assert admin.id not in _recipients(background)


def test_a_review_hold_says_it_is_waiting_on_the_supervisor(db, configured):
    """A supervisor must be able to tell a finished job from a paused one
    without opening the app."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )
    wos.start_work_order(db, work_order.id, user=worker)

    background = BackgroundTasks()
    work_orders_router.complete_work_order(
        work_order.id, background, user=worker, db=db
    )

    _, title, body = background.tasks[0].args
    assert title == "Work order ready for review"
    assert work_order.number in body
    assert "review" in body


def test_a_technician_finishing_twice_alerts_once(db, configured):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )
    wos.start_work_order(db, work_order.id, user=worker)

    first = BackgroundTasks()
    work_orders_router.complete_work_order(work_order.id, first, user=worker, db=db)
    second = BackgroundTasks()
    work_orders_router.complete_work_order(work_order.id, second, user=worker, db=db)

    assert len(first.tasks) == 1
    assert second.tasks == []


# --- tracking: start is silent, stop speaks only when it auto-holds -----

def _start_tracking(db, background, work_order_id, *, user):
    return work_orders_router.start_work_order_tracking(
        work_order_id, background, user=user, db=db
    )


def _stop_tracking(db, background, work_order_id, *, user):
    return work_orders_router.stop_work_order_tracking(
        work_order_id, background, user=user, db=db
    )


def test_starting_a_clock_notifies_nobody(db, configured):
    """Starting a timer is not news to a supervisor, and the Assigned ->
    In-Progress transition it performs matches no arm of any rule."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )

    background = BackgroundTasks()
    _start_tracking(db, background, work_order.id, user=worker)

    assert background.tasks == []


def test_the_last_clock_out_alerts_the_routed_supervisor(db, configured):
    """The auto-hold is a real entry into On-Hold, so it reuses the existing
    rule at a fourth trigger site rather than inventing an event."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )
    _start_tracking(db, BackgroundTasks(), work_order.id, user=worker)

    background = BackgroundTasks()
    _stop_tracking(db, background, work_order.id, user=worker)

    assert _recipients(background) == [supervisor.id]


def test_the_clocking_out_technician_is_not_buzzed_by_their_own_stop(db, configured):
    """Actor suppression, at the site most likely to expose a gap in it: the
    person tapping Stop is the person the hold is about.

    The supervisor here is routed to *themselves*, so suppression is the only
    thing that can keep them off the list -- and a routed-but-suppressed hold
    deliberately does not escalate to Admins, so the correct outcome is that
    nothing is dispatched at all rather than a task addressed to somebody
    else."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    worker = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=worker
    )
    _start_tracking(db, BackgroundTasks(), work_order.id, user=worker)

    background = BackgroundTasks()
    _stop_tracking(db, background, work_order.id, user=worker)

    assert background.tasks == []


def test_a_stop_that_leaves_a_co_worker_on_the_clock_notifies_nobody(db, configured):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    a = _seed_user(db, roles.ROLE_TECHNICIAN)
    b = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=admin, supervisor=supervisor)
    wos.update_work_order(
        db, work_order.id, user=admin, fields={"assigned_to_ids": [a.id, b.id]}
    )
    _start_tracking(db, BackgroundTasks(), work_order.id, user=a)
    _start_tracking(db, BackgroundTasks(), work_order.id, user=b)

    background = BackgroundTasks()
    _stop_tracking(db, background, work_order.id, user=a)

    assert background.tasks == []


def test_an_idempotent_repeat_stop_notifies_nobody(db, configured):
    """A repeat closes no session, performs no transition, and therefore
    sends nothing -- the standard double-tap guard, at a new site."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )
    _start_tracking(db, BackgroundTasks(), work_order.id, user=worker)

    first = BackgroundTasks()
    _stop_tracking(db, first, work_order.id, user=worker)
    second = BackgroundTasks()
    _stop_tracking(db, second, work_order.id, user=worker)

    assert len(first.tasks) == 1
    assert second.tasks == []


def test_starting_elsewhere_alerts_the_abandoned_work_orders_supervisor(db, configured):
    """The auto-hold on the *other* work order is a real event with a real
    audience. The router only receives the row it asked about, so the write
    hands the extra back rather than letting its alert go missing."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    first = _wo(db, created_by=admin, assigned_to=worker, supervisor=supervisor)
    second = _wo(db, created_by=admin, assigned_to=worker, supervisor=supervisor)
    _start_tracking(db, BackgroundTasks(), first.id, user=worker)

    background = BackgroundTasks()
    _start_tracking(db, background, second.id, user=worker)

    assert _recipients(background) == [supervisor.id]


# --- the Ready to Complete review gate ----------------------------------

def test_approving_ready_to_complete_fires_the_completion_rule(db, configured):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )
    wos.start_work_order(db, work_order.id, user=worker)
    wos.complete_work_order(db, work_order.id, user=worker)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=supervisor, status="completed")

    assert admin.id in _recipients(background)


def test_sending_work_back_notifies_the_assigned_technician(db, configured):
    """The supervisor rejecting a handoff is the whole point of Send Back,
    and the technician is the one who has to act on it. The supervisor here
    is the actor and drops out."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )
    wos.start_work_order(db, work_order.id, user=worker)
    wos.complete_work_order(db, work_order.id, user=worker)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=supervisor, status="in_progress")

    assert _recipients(background) == [worker.id]


def test_an_admin_sending_work_back_also_tells_the_routed_supervisor(
    db, configured
):
    """The row that earns the supervisor a place in this audience. When an
    Admin rejects work over the owning supervisor's head, that supervisor's
    crew is back on the job and nothing else would tell them."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )
    wos.start_work_order(db, work_order.id, user=worker)
    wos.complete_work_order(db, work_order.id, user=worker)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, status="in_progress")

    assert _recipients(background) == [worker.id, supervisor.id]


def test_send_back_is_its_own_event_not_a_return_from_review(db, configured):
    """Send Back and the Admin Review return send the identical payload --
    `{"status": "in_progress"}` -- and are told apart only by `previous`.
    They share an audience, so nothing but the words would catch a mix-up,
    which is exactly why this asserts on the words."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )
    wos.start_work_order(db, work_order.id, user=worker)
    wos.complete_work_order(db, work_order.id, user=worker)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=supervisor, status="in_progress")

    _, title, _body = background.tasks[0].args
    assert title == "Work order sent back"


def test_sending_back_a_row_already_in_progress_alerts_nobody(db, configured):
    """A second tap on Send Back, or a stale card sending the status it
    already has. `previous == status` is what stops the repeat."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )
    wos.start_work_order(db, work_order.id, user=worker)
    wos.complete_work_order(db, work_order.id, user=worker)
    _patch(
        db,
        BackgroundTasks(),
        work_order.id,
        user=supervisor,
        status="in_progress",
    )

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=supervisor, status="in_progress")

    assert background.tasks == []


def test_pausing_a_ready_to_complete_row_is_an_ordinary_hold(db, configured):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )
    wos.start_work_order(db, work_order.id, user=worker)
    wos.complete_work_order(db, work_order.id, user=worker)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, status="on_hold")

    _, title, _body = background.tasks[0].args
    assert title != "Work order ready for review"
    assert _recipients(background) == [supervisor.id]


# --- every entry into On-Hold reaches the supervisor --------------------

def test_pausing_from_the_walkthrough_alerts_the_routed_supervisor(db, configured):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )
    wos.start_work_order(db, work_order.id, user=worker)

    background = BackgroundTasks()
    work_orders_router.hold_work_order(
        work_order.id, background, user=worker, db=db
    )

    assert _recipients(background) == [supervisor.id]


def test_an_ordinary_pause_does_not_claim_the_work_is_finished(db, configured):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )
    wos.start_work_order(db, work_order.id, user=worker)

    background = BackgroundTasks()
    work_orders_router.hold_work_order(
        work_order.id, background, user=worker, db=db
    )

    _, title, _body = background.tasks[0].args
    assert title == "Work order on hold"


def test_pausing_twice_alerts_once(db, configured):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )
    wos.start_work_order(db, work_order.id, user=worker)

    first = BackgroundTasks()
    work_orders_router.hold_work_order(work_order.id, first, user=worker, db=db)
    second = BackgroundTasks()
    work_orders_router.hold_work_order(work_order.id, second, user=worker, db=db)

    assert len(first.tasks) == 1
    assert second.tasks == []


def test_a_hold_on_an_unrouted_work_order_reaches_the_admins(db, configured):
    """Nobody owns the work order, so the alert escalates rather than
    vanishing. Owner decision, 2026-08-18."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=admin, assigned_to=worker)
    wos.start_work_order(db, work_order.id, user=worker)

    background = BackgroundTasks()
    work_orders_router.hold_work_order(
        work_order.id, background, user=worker, db=db
    )

    assert admin.id in _recipients(background)


def test_a_supervisor_pausing_their_own_work_order_wakes_nobody(db, configured):
    """Routed-but-suppressed is not unrouted. A supervisor pausing their
    own job must not escalate it to every Admin by doing so."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _wo(
        db, created_by=admin, assigned_to=supervisor, supervisor=supervisor
    )
    wos.start_work_order(db, work_order.id, user=supervisor)

    background = BackgroundTasks()
    work_orders_router.hold_work_order(
        work_order.id, background, user=supervisor, db=db
    )

    assert background.tasks == []


def test_an_admin_holding_a_work_order_by_hand_alerts_the_supervisor(db, configured):
    """The third entry into On-Hold: a manual status edit."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, status="on_hold")

    assert _recipients(background) == [supervisor.id]


def test_completing_through_the_patch_also_notifies_admins(db, configured):
    """Requirement 2 is about the event, not about which endpoint caused
    it. A Supervisor+ can complete a work order without the walkthrough."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=admin, assigned_to=worker, supervisor=supervisor)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=supervisor, status="completed")

    assert admin.id in _recipients(background)


# --- requirement 3: reopened --------------------------------------------

def test_reopening_notifies_the_assignees_and_the_supervisor(db, configured):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=admin, assigned_to=worker, supervisor=supervisor)
    _to_completed(db, work_order, worker=worker, manager=admin)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, status="in_progress")

    assert set(_recipients(background)) == {worker.id, supervisor.id}


def test_reopening_does_not_also_fire_the_completed_rule(db, configured):
    """One transition is one event. An early version that evaluated both
    arms would tell the Admins a reopen was a completion."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=admin, assigned_to=worker)
    _to_completed(db, work_order, worker=worker, manager=admin)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, status="in_progress")

    assert len(background.tasks) == 1
    assert admin.id not in background.tasks[0].args[0]


def test_completed_to_on_hold_is_a_hold_not_a_reopen(db, configured):
    """The one overlap the new arm creates: leaving Completed *and*
    entering On-Hold. It resolves as a hold, so the supervisor hears once
    instead of twice -- the reopen audience already includes them.

    The assignees are deliberately not told. The row is paused, not handed
    back, and "no longer Completed" would invite work that is not yet
    available."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(
        db, created_by=admin, assigned_to=worker, supervisor=supervisor
    )
    _to_completed(db, work_order, worker=worker, manager=admin)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, status="on_hold")

    assert _recipients(background) == [supervisor.id]
    assert worker.id not in background.tasks[0].args[0]


def test_sending_completed_work_to_review_notifies_nobody(db, configured):
    """Review is the one exception to "leaves Completed for any other
    status". It is the forward handoff, not work coming back: the assignees
    have nothing to do about it, and "no longer Completed" would read as a
    setback. Owner decision, 2026-08-18."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=admin, assigned_to=worker, supervisor=supervisor)
    _to_completed(db, work_order, worker=worker, manager=admin)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, status="review")

    assert background.tasks == []


def test_every_other_way_out_of_completed_still_notifies(db, configured):
    """The Review carve-out must stay a carve-out. A rollback to a live
    working status is work coming back and has to reach the people holding
    it.

    On-Hold is excluded because it is not work coming back -- it has its own
    rule and its own audience, pinned by
    `test_completed_to_on_hold_is_a_hold_not_a_reopen`."""
    for status in ("created", "assigned", "in_progress"):
        admin = _seed_user(db, roles.ROLE_ADMIN)
        worker = _seed_user(db, roles.ROLE_TECHNICIAN)
        work_order = _wo(db, created_by=admin, assigned_to=worker)
        _to_completed(db, work_order, worker=worker, manager=admin)

        background = BackgroundTasks()
        _patch(db, background, work_order.id, user=admin, status=status)

        assert worker.id in _recipients(background), f"{status} notified nobody"


def test_a_status_change_that_never_touched_completed_notifies_nobody(db, configured):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=admin, assigned_to=worker)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, status="in_progress")

    assert background.tasks == []


# --- returned from review -----------------------------------------------

def _to_review(db, work_order, *, worker, reviewer):
    """Walk a work order to Review the way the app does. The handoff needs
    a second, unassigned person, so the reviewer cannot be the worker."""
    _to_completed(db, work_order, worker=worker, manager=reviewer)
    return wos.update_work_order(
        db, work_order.id, user=reviewer, fields={"status": "review"}
    )


def test_returning_from_review_notifies_the_technician_and_supervisor(db, configured):
    """The Admin Review page's return button is the only way this happens
    and it sends exactly `status: in_progress`."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=admin, assigned_to=worker, supervisor=supervisor)
    _to_review(db, work_order, worker=worker, reviewer=admin)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, status="in_progress")

    assert set(_recipients(background)) == {worker.id, supervisor.id}


def test_the_returned_notification_says_it_needs_another_look(db, configured):
    """A return is not a reopen. The crew has to be able to tell the
    difference from the lock screen without opening the app."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=admin, assigned_to=worker)
    _to_review(db, work_order, worker=worker, reviewer=admin)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, status="in_progress")

    _, title, body = background.tasks[0].args
    assert title == "Work order returned"
    assert work_order.number in body
    assert "Review" in body


def test_a_supervisor_returning_their_own_work_order_is_not_told(db, configured):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=admin, assigned_to=worker, supervisor=supervisor)
    _to_review(db, work_order, worker=worker, reviewer=supervisor)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=supervisor, status="in_progress")

    assert _recipients(background) == [worker.id]


def test_review_to_completed_is_a_completion_not_a_return(db, configured):
    """The branches are ordered, and this is the one pair that can overlap.
    A reviewer marking the work Completed again is telling the Admins, not
    sending it back to the crew.

    The second Admin is seeded rather than assumed: the reviewer is the
    actor and therefore suppressed, so without someone else at that rank
    there is no audience and no task to assert on. A development database
    supplies one by accident; CI's does not."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    other_admin = _seed_user(db, roles.ROLE_ADMIN)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=admin, assigned_to=worker)
    _to_review(db, work_order, worker=worker, reviewer=admin)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, status="completed")

    recipients = _recipients(background)
    assert other_admin.id in recipients
    assert admin.id not in recipients  # the actor
    assert worker.id not in recipients  # not a return-to-crew event


# --- one write, several events ------------------------------------------

def test_one_patch_can_be_both_an_assignment_and_a_completion(db, configured):
    """A PATCH is not one event. Evaluating the rules as a chain would drop
    whichever arm came second."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=admin, supervisor=supervisor)

    background = BackgroundTasks()
    _patch(
        db,
        background,
        work_order.id,
        user=supervisor,
        assigned_to_ids=[worker.id],
        status="completed",
    )

    audiences = [set(task.args[0]) for task in background.tasks]
    assert len(audiences) == 2
    assert {worker.id} in audiences
    assert any(admin.id in audience for audience in audiences)


# --- the durable write wins ---------------------------------------------

def test_a_broken_notification_rule_never_fails_the_write(db, monkeypatch, configured):
    """The work order is already committed when the rule runs. A bug in
    recipient resolution must cost a notification, not the save."""
    def _explode(*args, **kwargs):
        raise RuntimeError("recipient resolution is broken")

    monkeypatch.setattr(
        notifications_service, "notify_work_order_assigned", _explode
    )

    manager = _seed_user(db, roles.ROLE_ADMIN)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=manager)

    background = BackgroundTasks()
    result = _patch(
        db, background, work_order.id, user=manager, assigned_to_ids=[worker.id]
    )

    assert result is not None
    assert wos.assigned_technician_ids(
        wos.get_work_order(db, work_order.id, user=None)
    ) == [worker.id]


# --- routing a supervisor -----------------------------------------------

def test_routing_a_work_order_notifies_that_supervisor(db, configured):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _wo(db, created_by=admin)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, supervisor_id=supervisor.id)

    assert _recipients(background) == [supervisor.id]
    _, title, body = background.tasks[0].args
    assert title == "Work order assigned to you"
    assert work_order.number in body


def test_re_routing_tells_the_new_supervisor_and_not_the_old_one(db, configured):
    """A named gap rather than an oversight: losing a work order is real
    news and nothing sends it today. See `docs/notification-events.md`."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    old = _seed_user(db, roles.ROLE_SUPERVISOR)
    new = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _wo(db, created_by=admin, supervisor=old)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, supervisor_id=new.id)

    assert _recipients(background) == [new.id]


def test_re_saving_an_unchanged_supervisor_notifies_nobody(db, configured):
    """The editor sends the whole form. A supervisor already routed to a
    work order must not be re-notified every time somebody saves a note."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _wo(db, created_by=admin, supervisor=supervisor)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, supervisor_id=supervisor.id)

    assert background.tasks == []


def test_clearing_the_routing_notifies_nobody(db, configured):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _wo(db, created_by=admin, supervisor=supervisor)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, supervisor_id=None)

    assert background.tasks == []


def test_a_supervisor_claiming_an_unrouted_work_order_wakes_nobody(db, configured):
    """The common case on this path, and the reason the rule goes through
    actor suppression rather than returning a one-element list."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _wo(db, created_by=admin)

    background = BackgroundTasks()
    _patch(
        db, background, work_order.id, user=supervisor, supervisor_id=supervisor.id
    )

    assert background.tasks == []


def test_routing_and_a_status_move_in_one_patch_fire_both_rules(db, configured):
    """Assignment is evaluated independently of the transition chain. One
    write is one write, not one event."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=admin, assigned_to=worker)

    background = BackgroundTasks()
    _patch(
        db,
        background,
        work_order.id,
        user=admin,
        supervisor_id=supervisor.id,
        status="on_hold",
    )

    titles = [title for _ids, title, _body in
              (task.args for task in background.tasks)]
    assert titles == ["Work order assigned to you", "Work order on hold"]
