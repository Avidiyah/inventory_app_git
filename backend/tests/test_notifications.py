"""Tests for work-order notification rules.

What is worth pinning here is **recipient selection** and **when nothing
is scheduled at all**. Delivery itself belongs to `services/push.py` and
has its own coverage in `test_push_subscriptions.py`; nothing in this
file sends a real push, and re-proving the transport per trigger would
only make triggers expensive to add.

The two failure modes these tests exist for:

- Notifying the wrong people, which on a locked phone is a privacy
  problem rather than a UX one.
- Notifying anybody twice for one event, which is what an idempotent
  double tap produces if the rule ignores the prior status.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid

import pytest
from fastapi import BackgroundTasks

from app.domain import notifications as notif
from app.domain import roles
from app.models import User
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
    """Push enabled. Without a private key the service declines to
    schedule anything, which is correct and would hide every assertion."""
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    return True


def _scheduled(background):
    """The `(user_ids, title, body)` of each task queued on a response."""
    return [task.args for task in background.tasks]


def _recipients(background):
    assert len(background.tasks) == 1, f"expected one task, got {len(background.tasks)}"
    return background.tasks[0].args[0]


# --- requirement 1: assignment ------------------------------------------

def test_assignment_notifies_only_the_newly_added_technician(db, configured):
    manager = _seed_user(db, roles.ROLE_ADMIN)
    already_on_it = _seed_user(db, roles.ROLE_TECHNICIAN)
    added = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=manager, assigned_to=already_on_it)

    updated = wos.update_work_order(
        db,
        work_order.id,
        user=manager,
        fields={"assigned_to_ids": [already_on_it.id, added.id]},
    )

    background = BackgroundTasks()
    notifications_service.notify_work_order_assigned(
        db, background, work_order=updated, actor_id=manager.id
    )

    assert _recipients(background) == [added.id]


def test_assigning_yourself_notifies_nobody(db, configured):
    """A supervisor who puts their own name on a work order already knows."""
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _wo(db, created_by=supervisor)

    updated = wos.update_work_order(
        db,
        work_order.id,
        user=supervisor,
        fields={"assigned_to_ids": [supervisor.id]},
    )

    background = BackgroundTasks()
    notifications_service.notify_work_order_assigned(
        db, background, work_order=updated, actor_id=supervisor.id
    )

    assert background.tasks == []


def test_re_saving_an_unchanged_assignee_list_notifies_nobody(db, configured):
    manager = _seed_user(db, roles.ROLE_ADMIN)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=manager, assigned_to=worker)

    updated = wos.update_work_order(
        db, work_order.id, user=manager, fields={"assigned_to_ids": [worker.id]}
    )

    background = BackgroundTasks()
    notifications_service.notify_work_order_assigned(
        db, background, work_order=updated, actor_id=manager.id
    )

    assert background.tasks == []


# --- requirement 2: completion ------------------------------------------

def test_completion_notifies_admins_and_above(db, configured):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    owner = _seed_user(db, roles.ROLE_OWNER)
    techfm = _seed_user(db, roles.ROLE_TECHFM_OA)
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=admin, assigned_to=worker)

    background = BackgroundTasks()
    notifications_service.notify_work_order_completed(
        db, background, work_order=work_order, actor_id=worker.id
    )

    recipients = set(_recipients(background))
    assert {admin.id, owner.id} <= recipients
    assert techfm.id not in recipients
    assert worker.id not in recipients


def test_an_admin_completing_work_does_not_notify_themselves(db, configured):
    """Suppression is by id. The actor here outranks everyone the rule
    addresses, which is exactly the case a role-only fan-out cannot express."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    other_admin = _seed_user(db, roles.ROLE_ADMIN)
    work_order = _wo(db, created_by=admin)

    background = BackgroundTasks()
    notifications_service.notify_work_order_completed(
        db, background, work_order=work_order, actor_id=admin.id
    )

    recipients = _recipients(background)
    assert admin.id not in recipients
    assert other_admin.id in recipients


# --- requirement 3: reopened --------------------------------------------

def test_reopening_notifies_the_assignees_and_the_supervisor(db, configured):
    manager = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    first = _seed_user(db, roles.ROLE_TECHNICIAN)
    second = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=manager, supervisor=supervisor)
    work_order = wos.update_work_order(
        db,
        work_order.id,
        user=manager,
        fields={"assigned_to_ids": [first.id, second.id]},
    )

    background = BackgroundTasks()
    notifications_service.notify_work_order_reopened(
        db, background, work_order=work_order, actor_id=manager.id
    )

    assert set(_recipients(background)) == {first.id, second.id, supervisor.id}


def test_a_supervisor_who_is_also_an_assignee_is_notified_once(db, configured):
    """One person, one buzz. The dedup lives in `select_recipients` so no
    rule has to remember that the two lists can overlap."""
    manager = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _wo(db, created_by=manager, supervisor=supervisor)
    work_order = wos.update_work_order(
        db,
        work_order.id,
        user=manager,
        fields={"assigned_to_ids": [supervisor.id]},
    )

    background = BackgroundTasks()
    notifications_service.notify_work_order_reopened(
        db, background, work_order=work_order, actor_id=manager.id
    )

    assert _recipients(background) == [supervisor.id]


def test_reopening_an_unassigned_unrouted_work_order_notifies_nobody(db, configured):
    """A `None` supervisor and an empty assignee list are both ordinary."""
    manager = _seed_user(db, roles.ROLE_ADMIN)
    work_order = _wo(db, created_by=manager)

    background = BackgroundTasks()
    notifications_service.notify_work_order_reopened(
        db, background, work_order=work_order, actor_id=manager.id
    )

    assert background.tasks == []


# --- the handoff --------------------------------------------------------

def test_nothing_is_scheduled_when_push_is_not_configured(db, monkeypatch):
    """A deployment that never set a VAPID key must not queue work that
    can only fail, once per recipient, after every response."""
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "")
    admin = _seed_user(db, roles.ROLE_ADMIN)
    work_order = _wo(db, created_by=admin)

    background = BackgroundTasks()
    notifications_service.notify_work_order_completed(
        db, background, work_order=work_order, actor_id=uuid.uuid4()
    )

    assert background.tasks == []


def test_the_message_carries_the_number_and_no_other_detail(db, configured):
    """The lock-screen rule, checked at the seam where text is chosen."""
    manager = _seed_user(db, roles.ROLE_ADMIN, )
    worker = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _wo(db, created_by=manager, assigned_to=worker)
    work_order.description = "Leaking tap at 14 Ash Lane, Mrs Patel"
    db.flush()

    background = BackgroundTasks()
    notifications_service.notify_work_order_completed(
        db, background, work_order=work_order, actor_id=worker.id
    )

    _, title, body = _scheduled(background)[0]
    assert work_order.number in body
    assert "Ash Lane" not in body and "Patel" not in body
    assert "Ash Lane" not in title and "Patel" not in title


def test_delivery_opens_its_own_session(db, monkeypatch, configured):
    """The request's session is closed before background tasks run, so
    `_deliver` must not capture it. Reusing it fails only in production,
    which is the worst place to discover it."""
    seen = {}

    class _Session:
        def __init__(self):
            seen["opened"] = seen.get("opened", 0) + 1

        def close(self):
            seen["closed"] = seen.get("closed", 0) + 1

    def _fake_send(session, user_ids, title, body):
        seen["session"] = session
        seen["user_ids"] = list(user_ids)
        return {"sent": 1, "dropped": 0, "failed": 0}

    monkeypatch.setattr(notifications_service, "SessionLocal", _Session)
    monkeypatch.setattr(push_service, "send_to_users", _fake_send)

    admin = _seed_user(db, roles.ROLE_ADMIN)
    work_order = _wo(db, created_by=admin)

    background = BackgroundTasks()
    notifications_service.notify_work_order_completed(
        db, background, work_order=work_order, actor_id=uuid.uuid4()
    )
    task = background.tasks[0]
    task.func(*task.args)

    assert seen["opened"] == 1
    assert seen["closed"] == 1
    assert isinstance(seen["session"], _Session)
    assert seen["session"] is not db
    assert admin.id in seen["user_ids"]


def test_a_delivery_failure_is_swallowed(db, monkeypatch, configured):
    """The durable write already happened. A push problem raising out of a
    background task would be logged as a server error for a request that
    actually succeeded."""
    def _explode(session, user_ids, title, body):
        raise RuntimeError("apple is down")

    monkeypatch.setattr(notifications_service, "SessionLocal", lambda: _NullSession())
    monkeypatch.setattr(push_service, "send_to_users", _explode)

    admin = _seed_user(db, roles.ROLE_ADMIN)
    work_order = _wo(db, created_by=admin)

    background = BackgroundTasks()
    notifications_service.notify_work_order_completed(
        db, background, work_order=work_order, actor_id=uuid.uuid4()
    )
    task = background.tasks[0]

    task.func(*task.args)  # must not raise


# --- the bulk import send -----------------------------------------------

def test_a_supervisor_gets_one_notification_for_a_whole_import(db, configured):
    """The exception to "one event, one notification", and the reason it
    exists: forty separate pushes in a few seconds is not a notification,
    it is a denial of service aimed at the person who most needs to read
    it."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)

    background = BackgroundTasks()
    notifications_service.notify_supervisors_assigned_bulk(
        db,
        background,
        routing={supervisor.id: [f"WO-{n}" for n in range(40)]},
        actor_id=admin.id,
    )

    (user_ids, _title, body), = _scheduled(background)
    assert user_ids == [supervisor.id]
    assert "40" in body


def test_each_matched_supervisor_is_scheduled_separately(db, configured):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    first = _seed_user(db, roles.ROLE_SUPERVISOR)
    second = _seed_user(db, roles.ROLE_SUPERVISOR)

    background = BackgroundTasks()
    notifications_service.notify_supervisors_assigned_bulk(
        db,
        background,
        routing={first.id: ["WO-1", "WO-2"], second.id: ["WO-3", "WO-4"]},
        actor_id=admin.id,
    )

    assert [args[0] for args in _scheduled(background)] == [
        [first.id],
        [second.id],
    ]


def test_a_single_matched_work_order_is_named_rather_than_counted(db, configured):
    """"1 work orders have been assigned to you" is the small half of the
    reason. The larger one is that a supervisor who received exactly one
    work order can be told which one, and that is strictly more useful."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)

    background = BackgroundTasks()
    notifications_service.notify_supervisors_assigned_bulk(
        db,
        background,
        routing={supervisor.id: ["WO-77"]},
        actor_id=admin.id,
    )

    (_user_ids, _title, body), = _scheduled(background)
    assert "WO-77" in body
    assert "1 work orders" not in body


def test_an_importer_who_matched_themselves_is_not_notified(db, configured):
    """A supervisor with the TechFM OA rank runs the import and their own
    name matches some rows. They are the actor and already know."""
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    other = _seed_user(db, roles.ROLE_SUPERVISOR)

    background = BackgroundTasks()
    notifications_service.notify_supervisors_assigned_bulk(
        db,
        background,
        routing={supervisor.id: ["WO-1", "WO-2"], other.id: ["WO-3"]},
        actor_id=supervisor.id,
    )

    assert [args[0] for args in _scheduled(background)] == [[other.id]]


def test_an_import_that_matched_nobody_schedules_nothing(db, configured):
    admin = _seed_user(db, roles.ROLE_ADMIN)

    background = BackgroundTasks()
    notifications_service.notify_supervisors_assigned_bulk(
        db, background, routing={}, actor_id=admin.id
    )

    assert background.tasks == []


class _NullSession:
    def close(self):
        pass
