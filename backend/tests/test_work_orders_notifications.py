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
    admin = _seed_user(db, roles.ROLE_ADMIN)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
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
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=admin, assigned_to=worker)
    wos.start_work_order(db, work_order.id, user=worker)

    first = BackgroundTasks()
    work_orders_router.complete_work_order(work_order.id, first, user=worker, db=db)
    second = BackgroundTasks()
    work_orders_router.complete_work_order(work_order.id, second, user=worker, db=db)

    assert len(first.tasks) == 1
    assert second.tasks == []


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
    wos.start_work_order(db, work_order.id, user=worker)
    wos.complete_work_order(db, work_order.id, user=worker)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, status="in_progress")

    assert set(_recipients(background)) == {worker.id, supervisor.id}


def test_reopening_does_not_also_fire_the_completed_rule(db, configured):
    """One transition is one event. An early version that evaluated both
    arms would tell the Admins a reopen was a completion."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=admin, assigned_to=worker)
    wos.start_work_order(db, work_order.id, user=worker)
    wos.complete_work_order(db, work_order.id, user=worker)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, status="on_hold")

    assert len(background.tasks) == 1
    assert admin.id not in background.tasks[0].args[0]


def test_sending_completed_work_to_review_notifies_nobody(db, configured):
    """Review is the one exception to "leaves Completed for any other
    status". It is the forward handoff, not work coming back: the assignees
    have nothing to do about it, and "no longer Completed" would read as a
    setback. Owner decision, 2026-08-18."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=admin, assigned_to=worker, supervisor=supervisor)
    wos.start_work_order(db, work_order.id, user=worker)
    wos.complete_work_order(db, work_order.id, user=worker)

    background = BackgroundTasks()
    _patch(db, background, work_order.id, user=admin, status="review")

    assert background.tasks == []


def test_every_other_way_out_of_completed_still_notifies(db, configured):
    """The Review carve-out must stay a carve-out. A rollback to any live
    status is work coming back and has to reach the people holding it."""
    for status in ("created", "assigned", "in_progress", "on_hold"):
        admin = _seed_user(db, roles.ROLE_ADMIN)
        worker = _seed_user(db, roles.ROLE_TECHNICIAN)
        work_order = _wo(db, created_by=admin, assigned_to=worker)
        wos.start_work_order(db, work_order.id, user=worker)
        wos.complete_work_order(db, work_order.id, user=worker)

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
