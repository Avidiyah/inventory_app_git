"""Database integration tests for the standalone work-order service.

Exercises find-or-create-by-number (the import path: case-insensitive,
fill-blanks, restore-on-archived), resolve-by-number (every other surface, which
may not create), dispense vs retroactive logging, edit auto-correction, delete
reversal, the stock-neutral void, archive/restore, and role scoping. Skip if no
DB.

The Review-handoff permission tests at the end of the file are the exception:
`_require_review_handoff_permission` reads only a handful of attributes through
`getattr`, so they run against stand-ins and need no database.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain import list_limits
from app.domain import roles
from app.domain import work_orders as wo
from app.domain.errors import (
    InvalidAssigneeError,
    InvalidSupervisorError,
    ItemNotFoundError,
    RoleManagementError,
    WorkOrderAssignmentConflictError,
    WorkOrderNotFoundError,
    WorkOrderStateError,
)
from app.models import (
    Item,
    Transaction,
    User,
    UserRequest,
    WorkOrderLabor,
    WorkOrderLaborSession,
)
from app.services import auth
from app.services import work_orders as wos
from app.services.history import list_history
from app.services.transactions import void_transaction


# --- seed helpers --------------------------------------------------------

def _seed_item(db, qty=100, price="2.50"):
    item = Item(
        barcode=f"BC-{uuid.uuid4().hex[:10]}",
        name="Spray Paint",
        quantity=Decimal(qty),
        location="Bay 1",
        price=Decimal(price),
    )
    db.add(item)
    db.flush()
    return item


def _seed_user(db, role, *, first_name=None, last_name=None):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        first_name=first_name,
        last_name=last_name,
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _wo(db, *, created_by, assigned_to=None, supervisor=None, number=None):
    return wos.get_or_create_work_order(
        db,
        number=number or f"WO-{uuid.uuid4().hex[:8]}",
        created_by_id=created_by.id,
        assigned_to_id=assigned_to.id if assigned_to else None,
        supervisor_id=supervisor.id if supervisor else None,
    )


def _close(db, work_order, *, user):
    """Archive a fixture internally before exercising Closed behavior."""
    wos.archive_work_order(db, work_order.id, user=None)


def _txn(db, txn_id):
    return db.query(Transaction).filter(Transaction.id == txn_id).one()


# --- find-or-create (the import path) ------------------------------------

def test_import_create_is_created_with_number_identity(db):
    sup = _seed_user(db, "supervisor")
    w = wos.get_or_create_work_order(
        db, number="WO-100", community="Scholars", created_by_id=sup.id
    )
    assert w.status == "created"
    assert w.entry_mode == "dispense"
    assert w.community == "Scholars"
    assert w.created_by_id == sup.id


def test_technician_assignment_derives_only_prework_status(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup)
    assert w.status == "created"

    assigned = wos.update_work_order(
        db, w.id, user=sup, fields={"assigned_to_id": tech.id}
    )
    assert assigned.status == "assigned"

    unassigned = wos.update_work_order(
        db, w.id, user=sup, fields={"assigned_to_id": None}
    )
    assert unassigned.status == "created"

    wos.update_work_order(
        db, w.id, user=sup, fields={"status": "in_progress"}
    )
    reassigned = wos.update_work_order(
        db, w.id, user=sup, fields={"assigned_to_id": tech.id}
    )
    assert reassigned.status == "in_progress"


def test_multiple_technician_assignments_drive_status_and_scope(db):
    sup = _seed_user(db, "supervisor")
    tech1 = _seed_user(db, "technician")
    tech2 = _seed_user(db, "technician")
    w = _wo(db, created_by=sup)

    assigned = wos.update_work_order(
        db,
        w.id,
        user=sup,
        fields={"assigned_to_ids": [tech1.id, tech2.id]},
    )

    assert assigned.status == "assigned"
    assert assigned.assigned_to_id == tech1.id
    detail = wos.get_work_order(db, w.id, user=tech2)
    assert {tech.id for tech in wos.assigned_technicians(detail)} == {
        tech1.id,
        tech2.id,
    }
    assert w.id in {row.id for row in wos.list_work_orders(db, user=tech2)}

    cleared = wos.update_work_order(
        db, w.id, user=sup, fields={"assigned_to_ids": []}
    )
    assert cleared.status == "created"
    assert cleared.assigned_to_id is None


def test_supervisor_can_assign_self_and_other_supervisor_as_technicians(db):
    admin = _seed_user(db, "admin")
    assigner = _seed_user(db, "supervisor")
    other_supervisor = _seed_user(db, "supervisor")
    work_order = _wo(db, created_by=admin)

    assigned = wos.update_work_order(
        db,
        work_order.id,
        user=assigner,
        fields={
            "assigned_to_ids": [assigner.id, other_supervisor.id],
            "supervisor_id": admin.id,
        },
    )

    assert assigned.status == "assigned"
    assert assigned.supervisor_id == admin.id
    assert {user.id for user in wos.assigned_technicians(assigned)} == {
        assigner.id,
        other_supervisor.id,
    }
    # Worker assignment keeps both Supervisors in scope even though an Admin is
    # the routed supervisor.
    assert wos.get_work_order(db, work_order.id, user=assigner).id == work_order.id
    assert wos.get_work_order(db, work_order.id, user=other_supervisor).id == work_order.id
    assert work_order.id in {
        row.id for row in wos.list_work_orders(db, user=other_supervisor)
    }

    labor = wos.add_work_order_labor(
        db,
        work_order.id,
        user=assigner,
        technician_id=other_supervisor.id,
        minutes=30,
    )
    assert labor.technician_id == other_supervisor.id


def test_assigned_technician_can_start_work_order(db):
    supervisor = _seed_user(db, "supervisor")
    technician = _seed_user(db, "technician")
    work_order = _wo(db, created_by=supervisor)
    wos.update_work_order(
        db,
        work_order.id,
        user=supervisor,
        fields={"assigned_to_ids": [technician.id]},
    )

    started = wos.start_work_order(db, work_order.id, user=technician)

    assert started.status == "in_progress"
    # The narrow start action is idempotent for a double tap/retry.
    assert wos.start_work_order(db, work_order.id, user=technician).status == "in_progress"


def test_technician_cannot_start_unassigned_or_out_of_scope_work_order(db):
    supervisor = _seed_user(db, "supervisor")
    technician = _seed_user(db, "technician")
    other_technician = _seed_user(db, "technician")
    created = _wo(db, created_by=supervisor)

    with pytest.raises(WorkOrderNotFoundError):
        wos.start_work_order(db, created.id, user=technician)

    wos.update_work_order(
        db,
        created.id,
        user=supervisor,
        fields={"assigned_to_ids": [other_technician.id]},
    )
    with pytest.raises(WorkOrderNotFoundError):
        wos.start_work_order(db, created.id, user=technician)


@pytest.mark.parametrize("worker_role", ["technician", "supervisor"])
def test_assigned_worker_can_complete_only_after_start(db, worker_role):
    manager = _seed_user(db, "admin")
    worker = _seed_user(db, worker_role)
    work_order = _wo(db, created_by=manager, assigned_to=worker)

    with pytest.raises(WorkOrderStateError):
        wos.complete_work_order(db, work_order.id, user=worker)


def test_an_assigned_supervisor_completes_directly(db):
    manager = _seed_user(db, "admin")
    worker = _seed_user(db, "supervisor")
    work_order = _wo(db, created_by=manager, assigned_to=worker)
    wos.start_work_order(db, work_order.id, user=worker)

    completed = wos.complete_work_order(db, work_order.id, user=worker)

    assert completed.status == "completed"
    assert completed.completed_at is not None
    completed_at = completed.completed_at
    # A retry or double tap must not advance again or replace the timestamp.
    repeated = wos.complete_work_order(db, work_order.id, user=worker)
    assert repeated.status == "completed"
    assert repeated.completed_at == completed_at


def test_a_technicians_completion_parks_the_work_order_for_review(db):
    """A Technician finishes the job but does not get to declare it
    billable. The status now carries that state, so the note describes the
    person's action rather than the row's condition."""
    manager = _seed_user(db, "admin")
    worker = _seed_user(db, "technician", first_name="Dale", last_name="Grubb")
    work_order = _wo(db, created_by=manager, assigned_to=worker)
    wos.start_work_order(db, work_order.id, user=worker)

    held = wos.complete_work_order(db, work_order.id, user=worker)

    assert held.status == "ready_to_complete"
    assert held.completed_at is None
    assert wo.NOTE_READY_TO_COMPLETE in held.notes
    assert "Dale Grubb" in held.notes


def test_notify_supervisor_is_blocked_while_a_co_worker_is_charging(db):
    """One tech's finish must not silently end a colleague's charged time --
    the crew has to be off the clock first, or the finisher has to get them
    off it."""
    manager = _seed_user(db, "admin")
    a = _seed_user(db, "technician", first_name="Ada", last_name="Nunez")
    b = _seed_user(db, "technician", first_name="Bo", last_name="Reyes")
    work_order = _wo(db, created_by=manager)
    wos.update_work_order(
        db, work_order.id, user=manager, fields={"assigned_to_ids": [a.id, b.id]}
    )
    wos.start_labor_session(db, work_order.id, user=a)
    wos.start_labor_session(db, work_order.id, user=b)

    with pytest.raises(WorkOrderStateError):
        wos.complete_work_order(db, work_order.id, user=a)

    # Nothing moved: both clocks are still running and the row is untouched.
    db.refresh(work_order)
    assert work_order.status == "in_progress"
    assert sum(1 for s in _sessions(db, work_order) if s.ended_at is None) == 2


def test_notify_supervisor_still_works_for_a_lone_charger(db):
    """The rule only blocks on *someone else's* clock -- a tech alone on the
    row can still finish, same as before."""
    manager = _seed_user(db, "admin")
    worker = _seed_user(db, "technician")
    work_order = _wo(db, created_by=manager, assigned_to=worker)
    wos.start_labor_session(db, work_order.id, user=worker)

    held = wos.complete_work_order(db, work_order.id, user=worker)

    assert held.status == "ready_to_complete"


def test_a_repeated_technician_completion_does_not_duplicate_the_note(db):
    """The endpoint is idempotent by contract, so a slow double tap must
    not write a second note -- nor, downstream, fire a second alert."""
    manager = _seed_user(db, "admin")
    worker = _seed_user(db, "technician")
    work_order = _wo(db, created_by=manager, assigned_to=worker)
    wos.start_work_order(db, work_order.id, user=worker)

    first = wos.complete_work_order(db, work_order.id, user=worker)
    notes_after_first = first.notes

    repeated = wos.complete_work_order(db, work_order.id, user=worker)

    assert repeated.status == "ready_to_complete"
    assert repeated.notes == notes_after_first
    assert repeated.notes.count(wo.NOTE_READY_TO_COMPLETE) == 1


@pytest.mark.parametrize("worker_role", ["technician", "supervisor"])
def test_assigned_worker_can_hold_and_resume_only_matching_states(db, worker_role):
    manager = _seed_user(db, "admin")
    worker = _seed_user(db, worker_role)
    work_order = _wo(db, created_by=manager, assigned_to=worker)

    with pytest.raises(WorkOrderStateError):
        wos.hold_work_order(db, work_order.id, user=worker)
    with pytest.raises(WorkOrderStateError):
        wos.resume_work_order(db, work_order.id, user=worker)

    wos.start_work_order(db, work_order.id, user=worker)
    held = wos.hold_work_order(db, work_order.id, user=worker)

    assert held.status == "on_hold"
    assert held.completed_at is None
    assert wos.hold_work_order(db, work_order.id, user=worker).status == "on_hold"
    resumed = wos.resume_work_order(db, work_order.id, user=worker)
    assert resumed.status == "in_progress"
    assert wos.resume_work_order(db, work_order.id, user=worker).status == "in_progress"


def test_unassigned_supervisor_cannot_use_assigned_worker_completion(db):
    manager = _seed_user(db, "admin")
    routed_supervisor = _seed_user(db, "supervisor")
    worker = _seed_user(db, "technician")
    work_order = _wo(
        db,
        created_by=manager,
        assigned_to=worker,
        supervisor=routed_supervisor,
    )
    wos.start_work_order(db, work_order.id, user=worker)

    with pytest.raises(RoleManagementError):
        wos.complete_work_order(db, work_order.id, user=routed_supervisor)
    with pytest.raises(RoleManagementError):
        wos.hold_work_order(db, work_order.id, user=routed_supervisor)
    wos.hold_work_order(db, work_order.id, user=worker)
    with pytest.raises(RoleManagementError):
        wos.resume_work_order(db, work_order.id, user=routed_supervisor)


def test_review_requires_second_unassigned_responsible_user(db):
    manager = _seed_user(db, "admin")
    assigned_supervisor = _seed_user(db, "supervisor")
    work_order = _wo(
        db,
        created_by=manager,
        assigned_to=assigned_supervisor,
        supervisor=assigned_supervisor,
    )
    with pytest.raises(WorkOrderStateError):
        wos.update_work_order(
            db, work_order.id, user=manager, fields={"status": "review"}
        )

    wos.start_work_order(db, work_order.id, user=assigned_supervisor)
    wos.complete_work_order(db, work_order.id, user=assigned_supervisor)

    with pytest.raises(RoleManagementError):
        wos.update_work_order(
            db,
            work_order.id,
            user=assigned_supervisor,
            fields={"status": "review"},
        )

    reviewed = wos.update_work_order(
        db, work_order.id, user=manager, fields={"status": "review"}
    )
    assert reviewed.status == "review"


def test_unassigned_routed_supervisor_can_send_completed_work_to_review(db):
    manager = _seed_user(db, "admin")
    routed_supervisor = _seed_user(db, "supervisor")
    worker = _seed_user(db, "technician")
    work_order = _wo(
        db,
        created_by=manager,
        assigned_to=worker,
        supervisor=routed_supervisor,
    )
    wos.start_work_order(db, work_order.id, user=worker)
    # The technician's finish parks the row for review; the routed supervisor
    # is the one who turns that into Completed.
    wos.complete_work_order(db, work_order.id, user=worker)
    wos.update_work_order(
        db, work_order.id, user=routed_supervisor, fields={"status": "completed"}
    )

    reviewed = wos.update_work_order(
        db, work_order.id, user=routed_supervisor, fields={"status": "review"}
    )
    assert reviewed.status == "review"


def test_labor_tracks_technician_and_advances_first_activity(db):
    sup = _seed_user(db, "supervisor")
    tech1 = _seed_user(db, "technician")
    tech2 = _seed_user(db, "technician")
    w = _wo(db, created_by=sup)
    wos.update_work_order(
        db,
        w.id,
        user=sup,
        fields={"assigned_to_ids": [tech1.id, tech2.id]},
    )

    with pytest.raises(RoleManagementError):
        wos.add_work_order_labor(
            db, w.id, user=tech1, technician_id=tech2.id, minutes=35
        )

    first = wos.add_work_order_labor(
        db, w.id, user=sup, technician_id=tech1.id, minutes=35
    )
    second = wos.add_work_order_labor(
        db, w.id, user=sup, technician_id=tech2.id, minutes=40
    )
    detail = wos.get_work_order(db, w.id, user=tech2)

    assert detail.status == "in_progress"
    assert {entry.id for entry in detail.labor_entries} == {first.id, second.id}
    assert sum(entry.minutes for entry in detail.labor_entries) == 75

    updated = wos.update_work_order_labor(
        db, w.id, first.id, user=sup, minutes=50
    )
    assert updated.minutes == 50

    with pytest.raises(RoleManagementError):
        wos.update_work_order_labor(
            db, w.id, first.id, user=tech1, minutes=60
        )

    with pytest.raises(RoleManagementError):
        wos.delete_work_order_labor(db, w.id, first.id, user=tech1)

    wos.delete_work_order_labor(db, w.id, first.id, user=sup)
    detail = wos.get_work_order(db, w.id, user=tech2)
    assert [entry.id for entry in detail.labor_entries] == [second.id]
    assert detail.status == "in_progress"


def test_a_technician_cannot_key_labor_by_hand(db):
    """Tracked time is authoritative, so a Technician does not type a
    duration at all -- their rows come from stopping a session. This is the
    direct cost of that: a forgotten Start Tracking is only recoverable by a
    Supervisor."""
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup)
    wos.update_work_order(
        db, w.id, user=sup, fields={"assigned_to_ids": [tech.id]}
    )

    with pytest.raises(RoleManagementError):
        wos.add_work_order_labor(
            db, w.id, user=tech, technician_id=tech.id, minutes=35
        )


def test_a_technician_cannot_revise_or_erase_labor(db):
    """Hours are never written, rewritten, or erased by the person they are
    attributed to -- which is what keeps the billed figure trustworthy."""
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup)
    wos.update_work_order(
        db, w.id, user=sup, fields={"assigned_to_ids": [tech.id]}
    )
    entry = wos.add_work_order_labor(
        db, w.id, user=sup, technician_id=tech.id, minutes=35
    )

    with pytest.raises(RoleManagementError):
        wos.update_work_order_labor(db, w.id, entry.id, user=tech, minutes=5)
    with pytest.raises(RoleManagementError):
        wos.delete_work_order_labor(db, w.id, entry.id, user=tech)


def test_a_supervisor_records_their_own_labor_without_being_assigned(db):
    """A supervisor who does the work should record it without adding
    themselves to the crew list. A genuine permission widening: bounded by
    visibility and attributed by name."""
    sup = _seed_user(db, "supervisor", first_name="Robin", last_name="Vance")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)

    entry = wos.add_work_order_labor(
        db, w.id, user=sup, technician_id=sup.id, minutes=40
    )

    assert entry.technician_id == sup.id
    assert entry.minutes == 40
    assert sup.id not in wos.assigned_technician_ids(w)


def test_a_technician_still_needs_the_assignment_to_log_their_own_labor(db):
    """The own-row rule narrows the Supervisor+ permission; it does not
    replace the assignment check that was already there."""
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    other = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=other)

    with pytest.raises(WorkOrderNotFoundError):
        wos.add_work_order_labor(
            db, w.id, user=tech, technician_id=tech.id, minutes=30
        )


def test_labor_requires_current_technician_assignment(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup)

    with pytest.raises(InvalidAssigneeError):
        wos.add_work_order_labor(
            db, w.id, user=sup, technician_id=tech.id, minutes=30
        )


def test_find_or_create_case_insensitive_and_fill_blanks(db):
    sup = _seed_user(db, "supervisor")
    a = wos.get_or_create_work_order(db, number=f"WO-{uuid.uuid4().hex[:6]}", created_by_id=sup.id)
    same = a.number.upper() + " "
    b = wos.get_or_create_work_order(db, number=f"  {same.lower()} ", community="Scholars", created_by_id=sup.id)
    assert b.id == a.id  # same normalized number
    assert b.community == "Scholars"  # blank filled
    # a later reference does NOT overwrite a set attribute
    c = wos.get_or_create_work_order(db, number=a.number, community="Centennial", created_by_id=sup.id)
    assert c.community == "Scholars"


def test_import_resolver_leaves_archived_number_untouched(db):
    admin = _seed_user(db, "admin")
    work_order = _wo(db, created_by=admin)
    wos.archive_work_order(db, work_order.id, user=admin)
    archived_at = work_order.archived_at

    found = wos.get_or_create_work_order(
        db,
        number=work_order.number.lower(),
        created_by_id=admin.id,
        location="Replacement location",
    )

    assert found.id == work_order.id
    assert found.archived_at == archived_at
    assert found.location is None


def test_assignee_must_be_active_technician_or_supervisor(db):
    sup = _seed_user(db, "supervisor")
    admin = _seed_user(db, "admin")
    archived_supervisor = _seed_user(db, "supervisor")
    archived_supervisor.archived_at = datetime.now(timezone.utc)
    db.flush()

    assigned = wos.get_or_create_work_order(
        db,
        number=f"WO-SUP-{uuid.uuid4().hex[:8]}",
        assigned_to_id=sup.id,
        created_by_id=admin.id,
    )
    assert assigned.assigned_to_id == sup.id

    with pytest.raises(InvalidAssigneeError):
        wos.get_or_create_work_order(
            db,
            number=f"WO-ADMIN-{uuid.uuid4().hex[:8]}",
            assigned_to_id=admin.id,
            created_by_id=admin.id,
        )
    with pytest.raises(InvalidAssigneeError):
        wos.get_or_create_work_order(
            db,
            number=f"WO-ARCHIVED-{uuid.uuid4().hex[:8]}",
            assigned_to_id=archived_supervisor.id,
            created_by_id=admin.id,
        )


# --- resolve (every non-import surface) ----------------------------------
#
# Work orders are import-only: scan-and-go and Mass Stage attach to a number the
# import already brought in, and cannot conjure one.

def test_resolve_unknown_number_raises(db):
    with pytest.raises(WorkOrderNotFoundError):
        wos.resolve_work_order(db, number=f"WO-{uuid.uuid4().hex[:8]}")


def test_resolve_creates_nothing_on_a_miss(db):
    number = f"WO-{uuid.uuid4().hex[:8]}"
    with pytest.raises(WorkOrderNotFoundError):
        wos.resolve_work_order(db, number=number)
    assert wos.find_by_number(db, number) is None


def test_resolve_matches_case_insensitively_and_fills_blanks(db):
    sup = _seed_user(db, "supervisor")
    a = _wo(db, created_by=sup)
    b = wos.resolve_work_order(db, number=f"  {a.number.lower()} ", community="Scholars")
    assert b.id == a.id
    assert b.community == "Scholars"  # blank filled, as a reference always has
    # ...but a resolve never overwrites a value that is already set.
    c = wos.resolve_work_order(db, number=a.number, community="Centennial")
    assert c.community == "Scholars"


def test_resolve_refuses_an_archived_number(db):
    # Archived is a dead end for a reference now: only an explicit restore (or a
    # re-import) brings the work order back, so scanning cannot silently revive
    # something someone deliberately archived.
    sup = _seed_user(db, "supervisor")
    a = _wo(db, created_by=sup)
    _close(db, a, user=sup)
    with pytest.raises(WorkOrderNotFoundError):
        wos.resolve_work_order(db, number=a.number.lower())
    db.refresh(a)
    assert a.archived_at is not None  # the refused resolve changed nothing


# --- lookup / restore ----------------------------------------------------

def test_lookup_reports_an_archived_work_order(db):
    # The one read that sees through the archive, so History can offer a restore
    # for a number whose work order has been archived.
    sup = _seed_user(db, "supervisor")
    a = _wo(db, created_by=sup)
    assert wos.lookup_work_order(db, number=a.number, user=sup).archived_at is None
    _close(db, a, user=sup)
    found = wos.lookup_work_order(db, number=a.number.lower(), user=sup)
    assert found is not None and found.archived_at is not None


def test_lookup_hides_a_work_order_out_of_scope(db):
    # Scoping still applies after a work order leaves the shared pickup queue.
    mine = _seed_user(db, "supervisor")
    theirs = _seed_user(db, "supervisor")
    a = _wo(db, created_by=mine, supervisor=theirs)
    assert wos.lookup_work_order(db, number=a.number, user=mine) is None


def test_lookup_unknown_number_is_none(db):
    sup = _seed_user(db, "supervisor")
    assert wos.lookup_work_order(db, number=f"WO-{uuid.uuid4().hex[:8]}", user=sup) is None


def test_restore_unarchives_and_resolve_works_again(db):
    sup = _seed_user(db, "supervisor")
    a = _wo(db, created_by=sup)
    _close(db, a, user=sup)
    restored = wos.restore_work_order(db, a.id, user=sup)
    assert restored.id == a.id
    assert restored.archived_at is None
    # Back in scope for the loaders and for a reference.
    assert wos.get_work_order(db, a.id, user=sup).id == a.id
    assert wos.resolve_work_order(db, number=a.number).id == a.id


def test_restore_keeps_material_lines(db):
    # Archiving hides a work order; it never dropped its materials, and restoring
    # brings them back intact.
    sup = _seed_user(db, "supervisor")
    item = _seed_item(db, 100)
    a = _wo(db, created_by=sup)
    wos.add_work_order_item(db, a.id, user=sup, item_id=item.id, quantity=Decimal(3))
    _close(db, a, user=sup)
    wos.restore_work_order(db, a.id, user=sup)
    detail = wos.get_work_order(db, a.id, user=sup)
    assert [line.quantity for line in detail.items] == [Decimal(3)]


def test_archiving_keeps_the_work_orders_history_searchable(db):
    # Archiving hides the work order, never its ledger: each transaction carries
    # its own `work_order_number`, so History still finds every dispense logged
    # against an archived (or later restored) work order.
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100)
    w = _wo(db, created_by=sup, assigned_to=tech)
    wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(6))
    number = w.number

    def history_rows():
        return list_history(
            db, item_id=None, user_id=None, work_order_number=number,
            page=1, page_size=10, include_price=True,
        ).items

    assert len(history_rows()) == 1
    _close(db, w, user=sup)
    assert len(history_rows()) == 1  # still there while archived
    wos.restore_work_order(db, w.id, user=sup)
    assert len(history_rows()) == 1  # and unchanged by the restore


def test_restore_is_scoped(db):
    mine = _seed_user(db, "supervisor")
    theirs = _seed_user(db, "supervisor")
    a = _wo(db, created_by=mine, supervisor=theirs)
    _close(db, a, user=theirs)
    with pytest.raises(WorkOrderNotFoundError):
        wos.restore_work_order(db, a.id, user=mine)


# --- dispense mode (moves stock) -----------------------------------------

def test_dispense_add_moves_stock_and_writes_history_row(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100, price="3.00")
    w = _wo(db, created_by=sup, assigned_to=tech)  # default dispense
    assert w.status == "assigned"

    line = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(4))
    db.refresh(w)
    assert w.status == "in_progress"

    db.refresh(item)
    assert item.quantity == Decimal(96)
    txn = _txn(db, line.transaction_id)
    assert txn.transaction_type == "dispense"
    assert txn.affects_stock is True
    assert txn.work_order_id == w.id
    assert txn.work_order_number == w.number
    assert txn.unit_price == Decimal("3.00")


def test_material_activity_does_not_resume_on_hold_work_order(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100)
    w = _wo(db, created_by=sup, assigned_to=tech)
    wos.update_work_order(db, w.id, user=sup, fields={"status": "on_hold"})

    wos.add_work_order_item(
        db, w.id, user=tech, item_id=item.id, quantity=Decimal(1)
    )
    db.refresh(w)
    assert w.status == "on_hold"


@pytest.mark.parametrize("actor_role", ["technician", "supervisor"])
def test_dispense_shortage_is_recorded_with_recount_request(db, actor_role):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    actor = tech if actor_role == "technician" else sup
    item = _seed_item(db, 0, price="3.00")
    w = _wo(
        db,
        created_by=sup,
        assigned_to=tech if actor_role == "technician" else None,
        supervisor=sup,
    )

    line = wos.add_work_order_item(
        db,
        w.id,
        user=actor,
        item_id=item.id,
        quantity=Decimal(5),
    )

    db.refresh(item)
    assert item.quantity == Decimal(-5)
    request = (
        db.query(UserRequest)
        .filter(UserRequest.transaction_id == line.transaction_id)
        .one()
    )
    assert request.request_type == "inventory_recount"
    assert request.status == "open"
    assert request.created_by_id == actor.id
    assert request.details == {
        "recorded_quantity_before": "0",
        "dispensed_quantity": "5",
        "shortage_quantity": "5",
        "work_order_number": w.number,
    }

    if actor_role == "supervisor":
        wos.delete_work_order_item(db, w.id, line.id, user=sup)
        db.refresh(item)
        db.refresh(request)
        assert item.quantity == Decimal(0)
        assert request.status == "resolved"
        assert request.resolved_by_id == sup.id


def test_dispense_edit_auto_corrects_stock(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100)
    w = _wo(db, created_by=sup, assigned_to=tech)
    line = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(4))

    with pytest.raises(RoleManagementError):
        wos.update_work_order_item(
            db, w.id, line.id, user=tech, quantity=Decimal(10)
        )

    edited = wos.update_work_order_item(db, w.id, line.id, user=sup, quantity=Decimal(10))
    db.refresh(item)
    assert item.quantity == Decimal(90)
    # The line reflects the new total; the original dispense row is NOT rewritten
    # (the ledger stays append-only). A reconciling `adjust` carries the delta.
    assert edited.quantity == Decimal(10)
    assert _txn(db, line.transaction_id).quantity == Decimal(4)
    adjusts = (
        db.query(Transaction)
        .filter(
            Transaction.work_order_id == w.id,
            Transaction.transaction_type == "adjust",
        )
        .all()
    )
    assert [a.quantity for a in adjusts] == [Decimal(-6)]  # old(4) - new(10)

    wos.update_work_order_item(db, w.id, line.id, user=sup, quantity=Decimal(1))
    db.refresh(item)
    assert item.quantity == Decimal(99)


def test_dispense_delete_returns_stock_and_voids_txn(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100)
    w = _wo(db, created_by=sup, assigned_to=tech)
    line = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(4))
    txn_id = line.transaction_id

    with pytest.raises(RoleManagementError):
        wos.delete_work_order_item(db, w.id, line.id, user=tech)

    wos.delete_work_order_item(db, w.id, line.id, user=sup)
    db.refresh(item)
    assert item.quantity == Decimal(100)
    assert _txn(db, txn_id).voided_at is not None


def test_readd_same_item_accumulates_quantity(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100)
    w = _wo(db, created_by=sup, assigned_to=tech)
    first = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(4))
    second = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(7))
    # Re-logging an item ADDS to its one line (each add is its own ledger row).
    assert second.id == first.id
    assert second.quantity == Decimal(11)
    db.refresh(item)
    assert item.quantity == Decimal(89)
    # Two distinct dispense rows back the single line.
    dispenses = (
        db.query(Transaction)
        .filter(
            Transaction.work_order_id == w.id,
            Transaction.transaction_type == "dispense",
            Transaction.voided_at.is_(None),
        )
        .all()
    )
    assert sorted(d.quantity for d in dispenses) == [Decimal(4), Decimal(7)]


# --- retroactive mode (stock-neutral, still in History) ------------------

def _make_retroactive(db, w, actor):
    wos.update_work_order(db, w.id, user=actor, fields={"entry_mode": "retroactive"})


def test_retroactive_add_does_not_move_stock_but_shows_in_history(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100, price="5.00")
    w = _wo(db, created_by=sup, assigned_to=tech)
    _make_retroactive(db, w, sup)

    line = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(4))
    db.refresh(item)
    assert item.quantity == Decimal(100)
    txn = _txn(db, line.transaction_id)
    assert txn.transaction_type == "dispense"
    assert txn.affects_stock is False

    page = list_history(
        db, item_id=item.id, user_id=None, work_order_number=w.number,
        page=1, page_size=10, include_price=True,
    )
    assert any(r.transaction_type == "dispense" and r.quantity == Decimal(4) for r in page.items)


def test_void_of_retroactive_txn_does_not_move_stock(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100)
    w = _wo(db, created_by=sup, assigned_to=tech)
    _make_retroactive(db, w, sup)
    line = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(4))

    void_transaction(db, transaction_id=line.transaction_id, user_id=sup.id)
    db.refresh(item)
    assert item.quantity == Decimal(100)


def test_mode_switch_only_affects_new_lines(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100)
    other = _seed_item(db, 100)
    w = _wo(db, created_by=sup, assigned_to=tech)  # dispense

    disp = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(4))
    _make_retroactive(db, w, sup)
    retro = wos.add_work_order_item(db, w.id, user=tech, item_id=other.id, quantity=Decimal(3))
    assert disp.mode == "dispense"
    assert retro.mode == "retroactive"

    wos.update_work_order_item(db, w.id, disp.id, user=sup, quantity=Decimal(6))
    db.refresh(item)
    assert item.quantity == Decimal(94)
    db.refresh(other)
    assert other.quantity == Decimal(100)


# --- lifecycle / completed-stays-editable -------------------------------

def test_completed_work_order_still_editable(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100)
    w = _wo(db, created_by=sup, assigned_to=tech)

    with pytest.raises(RoleManagementError):
        wos.update_work_order(
            db, w.id, user=tech, fields={"status": "completed"}
        )

    completed = wos.update_work_order(db, w.id, user=sup, fields={"status": "completed"})
    assert completed.status == "completed"
    assert completed.completed_at is not None

    line = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(2))
    assert line.quantity == Decimal(2)


def test_review_retains_completion_time_and_reopen_clears_it(db):
    sup = _seed_user(db, "supervisor")
    w = _wo(db, created_by=sup, supervisor=sup)

    completed = wos.update_work_order(
        db, w.id, user=sup, fields={"status": "completed"}
    )
    completed_at = completed.completed_at
    review = wos.update_work_order(
        db, w.id, user=sup, fields={"status": "review"}
    )
    assert review.completed_at == completed_at

    reopened = wos.update_work_order(
        db, w.id, user=sup, fields={"status": "in_progress"}
    )
    assert reopened.completed_at is None


def test_completed_can_roll_back_to_on_hold_and_clear_completion_time(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)

    completed = wos.update_work_order(
        db, w.id, user=sup, fields={"status": "completed"}
    )
    assert completed.completed_at is not None

    held = wos.update_work_order(
        db, w.id, user=sup, fields={"status": "on_hold"}
    )
    assert held.status == "on_hold"
    assert held.completed_at is None


def test_manual_prework_rollback_stays_aligned_with_technician(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)
    wos.update_work_order(db, w.id, user=sup, fields={"status": "completed"})

    assigned = wos.update_work_order(
        db, w.id, user=sup, fields={"status": "created"}
    )
    assert assigned.status == "assigned"

    created = wos.update_work_order(
        db,
        w.id,
        user=sup,
        fields={"assigned_to_id": None, "status": "assigned"},
    )
    assert created.status == "created"


def test_work_order_notes_append_timestamped_authenticated_user_log(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(
        db,
        "technician",
        first_name="Jamie",
        last_name="Rivera",
    )
    w = _wo(db, created_by=sup, assigned_to=tech)

    saved = wos.update_work_order(
        db, w.id, user=tech, fields={"notes": "Call resident before arrival."}
    )
    # A human-typed note goes through the same `append_note_log` a
    # server-authored one does, which is what "normalized" means here.
    assert re.fullmatch(
        r"\d{2}/\d{2}/\d{2} \d{2}:\d{2} [AP]M Jamie Rivera "
        r"Call resident before arrival\.",
        saved.notes,
    )

    first_entry = saved.notes
    appended = wos.update_work_order(
        db, w.id, user=tech, fields={"notes": "Parts ordered."}
    )
    assert appended.notes.startswith(first_entry + "\n\n")
    assert appended.notes.endswith("Jamie Rivera Parts ordered.")

    # The log is append-only; an old client's null clear cannot erase history.
    unchanged = wos.update_work_order(
        db, w.id, user=tech, fields={"notes": None}
    )
    assert unchanged.notes == appended.notes


def test_work_order_update_role_matrix_separates_metadata_and_operations(db):
    admin = _seed_user(db, "admin")
    supervisor = _seed_user(db, "supervisor")
    technician = _seed_user(db, "technician")
    work_order = wos.get_or_create_work_order(
        db,
        number=f"WO-ROLE-{uuid.uuid4().hex[:8]}",
        created_by_id=admin.id,
        supervisor_id=supervisor.id,
        assigned_to_id=technician.id,
    )

    with pytest.raises(RoleManagementError, match="Admin"):
        wos.update_work_order(
            db,
            work_order.id,
            user=supervisor,
            fields={"location": "Commons 101", "description": "Leaking sink"},
        )
    with pytest.raises(RoleManagementError, match="Supervisor"):
        wos.update_work_order(
            db,
            work_order.id,
            user=technician,
            fields={"status": "in_progress"},
        )

    metadata = wos.update_work_order(
        db,
        work_order.id,
        user=admin,
        fields={
            "location": "Commons 101",
            "service_type": "Plumbing",
            "schedule_date": "8/4/2026",
            "output_to": "Facilities",
            "vendor_assignee": "Vendor Contact",
            "description": "Leaking sink",
            "priority": "Emergency",
        },
    )
    assert metadata.location == "Commons 101"
    assert metadata.description == "Leaking sink"
    assert metadata.priority == "Emergency"

    operational = wos.update_work_order(
        db,
        work_order.id,
        user=supervisor,
        fields={"status": "in_progress", "entry_mode": "retroactive"},
    )
    assert operational.status == "in_progress"
    assert operational.entry_mode == "retroactive"


@pytest.mark.parametrize("role", ["admin", "owner"])
@pytest.mark.parametrize("status", wo.ALL_STATUSES)
def test_admin_plus_can_archive_from_any_live_status(db, role, status):
    actor = _seed_user(db, role)
    work_order = _wo(db, created_by=actor)
    work_order.status = status
    db.commit()

    wos.archive_work_order(db, work_order.id, user=actor)

    db.refresh(work_order)
    assert work_order.archived_at is not None


def test_supervisor_cannot_archive_work_order(db):
    supervisor = _seed_user(db, "supervisor")
    work_order = _wo(db, created_by=supervisor)
    with pytest.raises(RoleManagementError, match="TechFM OA, Admin, or Owner"):
        wos.archive_work_order(db, work_order.id, user=supervisor)
    db.refresh(work_order)
    assert work_order.archived_at is None


def test_owner_can_preview_and_rearchive_only_live_legacy_work_orders(db):
    owner = _seed_user(db, "owner")
    baseline = wos.count_live_legacy_work_orders(db, user=owner)
    live_legacy_a = _wo(db, created_by=owner)
    live_legacy_b = _wo(db, created_by=owner)
    already_archived_legacy = _wo(db, created_by=owner)
    live_current = _wo(db, created_by=owner)

    for work_order in (
        live_legacy_a,
        live_legacy_b,
        already_archived_legacy,
    ):
        work_order.legacy = True
    db.commit()
    wos.archive_work_order(db, already_archived_legacy.id, user=owner)
    db.refresh(already_archived_legacy)
    already_archived_at = already_archived_legacy.archived_at

    assert wos.count_live_legacy_work_orders(db, user=owner) == baseline + 2
    assert wos.archive_live_legacy_work_orders(db, user=owner) == baseline + 2
    assert wos.count_live_legacy_work_orders(db, user=owner) == 0

    for work_order in (live_legacy_a, live_legacy_b, already_archived_legacy):
        db.refresh(work_order)
        assert work_order.archived_at is not None
    assert already_archived_legacy.archived_at == already_archived_at
    db.refresh(live_current)
    assert live_current.archived_at is None


def test_admin_cannot_preview_or_rearchive_legacy_work_orders(db):
    admin = _seed_user(db, "admin")
    work_order = _wo(db, created_by=admin)
    work_order.legacy = True
    db.commit()

    with pytest.raises(RoleManagementError, match="Owner"):
        wos.count_live_legacy_work_orders(db, user=admin)
    with pytest.raises(RoleManagementError, match="Owner"):
        wos.archive_live_legacy_work_orders(db, user=admin)

    db.refresh(work_order)
    assert work_order.archived_at is None


def test_set_invalid_status_rejected(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)
    with pytest.raises(WorkOrderStateError):
        wos.update_work_order(db, w.id, user=sup, fields={"status": "planning"})


def test_stale_supervisor_pickup_reports_current_assignee_and_preserves_it(db):
    admin = _seed_user(db, "admin")
    first = _seed_user(
        db, "supervisor", first_name="Avery", last_name="Anderson"
    )
    second = _seed_user(
        db, "supervisor", first_name="Blake", last_name="Bennett"
    )
    work_order = _wo(db, created_by=admin)

    claimed = wos.update_work_order(
        db,
        work_order.id,
        user=first,
        fields={"supervisor_id": first.id},
        expected_supervisor_id=None,
    )
    assert claimed.supervisor_id == first.id

    with pytest.raises(
        WorkOrderAssignmentConflictError,
        match=r"^This Work Order was already assigned to Avery Anderson$",
    ):
        wos.update_work_order(
            db,
            work_order.id,
            user=second,
            fields={"supervisor_id": second.id},
            expected_supervisor_id=None,
        )
    db.rollback()
    db.refresh(work_order)
    assert work_order.supervisor_id == first.id


def test_work_order_routing_requires_an_active_supervisor(db):
    admin = _seed_user(db, "admin")
    technician = _seed_user(db, "technician")
    archived = _seed_user(db, "supervisor")
    owner = _seed_user(db, "owner")
    archived.archived_at = datetime.now(timezone.utc)
    work_order = _wo(db, created_by=admin)
    db.commit()

    with pytest.raises(InvalidSupervisorError, match="active TechFM OA, Admin, or Supervisor"):
        wos.update_work_order(
            db,
            work_order.id,
            user=admin,
            fields={"supervisor_id": technician.id},
            expected_supervisor_id=None,
        )
    db.rollback()

    with pytest.raises(InvalidSupervisorError, match="active TechFM OA, Admin, or Supervisor"):
        wos.update_work_order(
            db,
            work_order.id,
            user=admin,
            fields={"supervisor_id": archived.id},
            expected_supervisor_id=None,
        )
    db.rollback()

    with pytest.raises(InvalidSupervisorError, match="active TechFM OA, Admin, or Supervisor"):
        wos.update_work_order(
            db,
            work_order.id,
            user=admin,
            fields={"supervisor_id": owner.id},
            expected_supervisor_id=None,
        )
    db.rollback()


def test_admin_can_route_work_order_to_self_and_another_admin(db):
    first_admin = _seed_user(db, "admin")
    second_admin = _seed_user(db, "admin")
    work_order = _wo(db, created_by=first_admin)

    self_routed = wos.update_work_order(
        db,
        work_order.id,
        user=first_admin,
        fields={"supervisor_id": first_admin.id},
        expected_supervisor_id=None,
    )
    assert self_routed.supervisor_id == first_admin.id

    rerouted = wos.update_work_order(
        db,
        work_order.id,
        user=first_admin,
        fields={"supervisor_id": second_admin.id},
        expected_supervisor_id=first_admin.id,
    )
    assert rerouted.supervisor_id == second_admin.id


# --- scoping -------------------------------------------------------------

def test_scoping_list_and_access(db):
    sup_a = _seed_user(db, "supervisor")
    sup_b = _seed_user(db, "supervisor")
    tech1 = _seed_user(db, "technician")
    tech2 = _seed_user(db, "technician")
    admin = _seed_user(db, "admin")

    a = _wo(db, created_by=sup_b, assigned_to=tech1, supervisor=sup_a)
    b = _wo(db, created_by=sup_a, assigned_to=tech2, supervisor=sup_b)
    pickup = _wo(db, created_by=admin)

    def ids(user, **kw):
        return {w.id for w in wos.list_work_orders(db, user=user, **kw)}

    assert ids(tech1) == {a.id}
    assert ids(tech2) == {b.id}
    assert {a.id, pickup.id} <= ids(sup_a)
    assert b.id not in ids(sup_a)
    assert {b.id, pickup.id} <= ids(sup_b)
    assert a.id not in ids(sup_b)
    assert {a.id, b.id} <= ids(admin)

    with pytest.raises(WorkOrderNotFoundError):
        wos.get_work_order(db, b.id, user=tech1)
    item = _seed_item(db, 100)
    with pytest.raises(WorkOrderNotFoundError):
        wos.add_work_order_item(db, b.id, user=tech1, item_id=item.id, quantity=Decimal(1))


def test_status_filter_and_search(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    a = _wo(db, created_by=sup, assigned_to=tech)
    b = _wo(db, created_by=sup, assigned_to=tech)
    wos.update_work_order(db, a.id, user=sup, fields={"status": "in_progress"})
    wos.update_work_order(db, b.id, user=sup, fields={"status": "completed"})
    held = _wo(db, created_by=sup, assigned_to=tech)
    wos.update_work_order(db, held.id, user=sup, fields={"status": "on_hold"})

    in_prog = {w.id for w in wos.list_work_orders(db, user=sup, status="in_progress")}
    done = {w.id for w in wos.list_work_orders(db, user=sup, status="completed")}
    on_hold = {w.id for w in wos.list_work_orders(db, user=sup, status="on_hold")}
    assert a.id in in_prog and b.id not in in_prog
    assert b.id in done and a.id not in done
    assert held.id in on_hold and a.id not in on_hold

    db.refresh(a)
    frag = a.number[-4:]
    found = {w.id for w in wos.list_work_orders(db, user=sup, search=frag)}
    assert a.id in found


def test_advanced_filters_combine_with_and(db):
    admin = _seed_user(db, "admin")
    sup_a = _seed_user(db, "supervisor", first_name="Avery", last_name="Able")
    sup_b = _seed_user(db, "supervisor", first_name="Blake", last_name="Baker")

    def make(
        *, supervisor, service, location, status="in_progress",
        schedule_date="7/28/2026"
    ):
        work_order = wos.get_or_create_work_order(
            db,
            number=f"WO-FILTER-{uuid.uuid4().hex[:8]}",
            created_by_id=admin.id,
            supervisor_id=supervisor.id,
            service_type=service,
            location=location,
            schedule_date=schedule_date,
        )
        wos.update_work_order(
            db, work_order.id, user=admin, fields={"status": status}
        )
        return work_order

    target = make(
        supervisor=sup_a,
        service="SMR27 - Belfor",
        location="Commons Apartments: 8B",
    )
    make(
        supervisor=sup_b,
        service="SMR27 - Belfor",
        location="Commons Apartments: 9B",
    )
    make(
        supervisor=sup_a,
        service="SMR27 - Belfor Re-Work",
        location="Commons Apartments: 10B",
    )
    make(
        supervisor=sup_a,
        service="SMR27 - Belfor",
        location="Centennial Courts Apartments: 112",
    )
    make(
        supervisor=sup_a,
        service="SMR27 - Belfor",
        location="Commons Apartments: 11B",
        status="completed",
    )
    make(
        supervisor=sup_a,
        service="SMR27 - Belfor",
        location="Commons Apartments: 12B",
        schedule_date="7/27/2026",
    )

    matches = wos.list_work_orders(
        db,
        user=admin,
        status="in_progress",
        service_type="  smr27 - BELFOR ",
        supervisor_id=sup_a.id,
        community="commons",
        scheduled_date=date(2026, 7, 28),
        search="WO-FILTER-",
    )

    assert [work_order.id for work_order in matches] == [target.id]


def test_assigned_to_id_filter_narrows_to_explicit_assignment(db):
    # A Supervisor's own scope (`_scoped_to_user`) also includes the
    # unrouted pickup queue and everything they supervise -- `assigned_to_id`
    # narrows within that to exactly what is explicitly assigned to them.
    # This is the Work Orders page's opt-in filter. The User Hub's "My Work
    # Orders" tab deliberately does *not* use it (see `mine` below): worker
    # assignment is not routing, and the tab needs both.
    supervisor = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")

    assigned_to_supervisor = wos.get_or_create_work_order(
        db,
        number=f"WO-ASSIGN-{uuid.uuid4().hex[:8]}",
        created_by_id=supervisor.id,
        supervisor_id=supervisor.id,
        assigned_to_id=supervisor.id,
    )
    supervised_but_unassigned = wos.get_or_create_work_order(
        db,
        number=f"WO-ASSIGN-{uuid.uuid4().hex[:8]}",
        created_by_id=supervisor.id,
        supervisor_id=supervisor.id,
    )
    wos.get_or_create_work_order(
        db,
        number=f"WO-ASSIGN-{uuid.uuid4().hex[:8]}",
        created_by_id=supervisor.id,
        assigned_to_id=tech.id,
    )

    # Sanity check: without the filter, the supervisor's own broader scope
    # already includes the unassigned-but-supervised row.
    unfiltered = wos.list_work_orders(db, user=supervisor)
    assert supervised_but_unassigned.id in [w.id for w in unfiltered]

    matches = wos.list_work_orders(
        db, user=supervisor, assigned_to_id=supervisor.id
    )

    assert [w.id for w in matches] == [assigned_to_supervisor.id]


def test_mine_covers_routing_and_assignment_but_not_the_pickup_queue(db):
    # The User Hub's "My Work Orders" tab. `assigned_to_id` cannot express
    # this: routing is not part of its or_ pair, so a work order an Admin
    # routed to a Supervisor was invisible on their own dashboard while the
    # "Work orders I lead" tile counted it.
    #
    # The unrouted row is the other half of the contract: a Supervisor's own
    # scope admits the pickup queue, and about half of all live work orders
    # are unrouted, so letting it through turned this list into "everything".
    supervisor = _seed_user(db, "supervisor")
    admin = _seed_user(db, "admin")
    other_supervisor = _seed_user(db, "supervisor")
    prefix = f"WO-MINE-{uuid.uuid4().hex[:8]}"

    routed = wos.get_or_create_work_order(
        db, number=f"{prefix}-R", created_by_id=admin.id, supervisor_id=supervisor.id
    )
    assigned = wos.get_or_create_work_order(
        db, number=f"{prefix}-A", created_by_id=admin.id, assigned_to_id=supervisor.id
    )
    unrouted = wos.get_or_create_work_order(
        db, number=f"{prefix}-U", created_by_id=admin.id
    )
    someone_elses = wos.get_or_create_work_order(
        db,
        number=f"{prefix}-X",
        created_by_id=admin.id,
        supervisor_id=other_supervisor.id,
    )

    found = {w.id for w in wos.list_work_orders(db, user=supervisor, mine=True)}

    assert routed.id in found
    assert assigned.id in found
    assert unrouted.id not in found
    assert someone_elses.id not in found

    # The unrouted row is not missing because it is invisible -- the
    # Supervisor's own scope does reach it. `mine` is what holds it back.
    assert unrouted.id in {w.id for w in wos.list_work_orders(db, user=supervisor)}


def test_mine_never_widens_a_technicians_scope(db):
    # `mine` admits the unrouted pickup queue, but `_scoped_to_user` still
    # runs on top of it -- a Technician has no pickup queue and must not
    # acquire one by passing the flag.
    tech = _seed_user(db, "technician")
    admin = _seed_user(db, "admin")
    prefix = f"WO-MINETECH-{uuid.uuid4().hex[:8]}"

    assigned = wos.get_or_create_work_order(
        db, number=f"{prefix}-A", created_by_id=admin.id, assigned_to_id=tech.id
    )
    unrouted = wos.get_or_create_work_order(
        db, number=f"{prefix}-U", created_by_id=admin.id
    )

    found = {w.id for w in wos.list_work_orders(db, user=tech, mine=True)}

    assert assigned.id in found
    assert unrouted.id not in found


def test_mine_narrows_an_admins_company_wide_list(db):
    admin = _seed_user(db, "admin")
    other_supervisor = _seed_user(db, "supervisor")
    prefix = f"WO-MINEADMIN-{uuid.uuid4().hex[:8]}"

    routed_to_admin = wos.get_or_create_work_order(
        db, number=f"{prefix}-R", created_by_id=admin.id, supervisor_id=admin.id
    )
    someone_elses = wos.get_or_create_work_order(
        db,
        number=f"{prefix}-X",
        created_by_id=admin.id,
        supervisor_id=other_supervisor.id,
    )

    unfiltered = {w.id for w in wos.list_work_orders(db, user=admin)}
    found = {w.id for w in wos.list_work_orders(db, user=admin, mine=True)}

    assert someone_elses.id in unfiltered
    assert routed_to_admin.id in found
    assert someone_elses.id not in found


def test_list_sorts_by_scheduled_date_descending_and_filters_exact_date(db):
    admin = _seed_user(db, "admin")
    prefix = f"WO-SCHEDULE-{uuid.uuid4().hex[:8]}"

    def make(suffix, schedule_date):
        return wos.get_or_create_work_order(
            db,
            number=f"{prefix}-{suffix}",
            created_by_id=admin.id,
            schedule_date=schedule_date,
        )

    older = make("OLDER", "7/1/2026")
    newest = make("NEWEST", "8/2/2026 13:35")
    invalid = make("INVALID", "shifted description text")
    blank = make("BLANK", None)

    ordered = wos.list_work_orders(db, user=admin, search=prefix)
    assert [work_order.id for work_order in ordered[:2]] == [newest.id, older.id]
    assert {work_order.id for work_order in ordered[2:]} == {invalid.id, blank.id}

    filtered = wos.list_work_orders(
        db,
        user=admin,
        search=prefix,
        scheduled_date=date(2026, 8, 2),
    )
    assert [work_order.id for work_order in filtered] == [newest.id]


def test_community_filters_are_membership_based_with_academics_fallback(db):
    admin = _seed_user(db, "admin")

    def make(location=None, *, community=None):
        return wos.get_or_create_work_order(
            db,
            number=f"WO-COMMUNITY-{uuid.uuid4().hex[:8]}",
            created_by_id=admin.id,
            location=location,
            community=community,
        )

    scholars = make("Scholars Inn Apartments: 1813")
    centennial = make("Centennial Courts Apartments: 1123")
    commons = make("Commons Apartments: 8B")
    cimarron = make("Cimarron Village: 1A")
    cimmarron = make("Cimmarron Village: 2A")
    young_hall = make("Young Hall: 201")
    structured = make(None, community="Scholars")
    multiple = make(
        "Multiple Locations: Scholars, Commons, Centennial, and Young Hall"
    )
    academic = make("Moore Hall - School of Business: 202")
    blank = make(None)

    def ids(value):
        return {
            work_order.id
            for work_order in wos.list_work_orders(
                db, user=admin, community=value
            )
        }

    assert {scholars.id, structured.id, multiple.id} <= ids("scholars")
    assert {centennial.id, multiple.id} <= ids("centennial")
    assert {commons.id, cimarron.id, cimmarron.id, multiple.id} <= ids("commons")
    assert {young_hall.id, multiple.id} <= ids("young_hall")
    academics = ids("academics")
    assert {academic.id, blank.id} <= academics
    assert multiple.id not in academics


def test_filter_options_are_distinct_and_server_scoped(db):
    admin = _seed_user(db, "admin")
    tech = _seed_user(db, "technician")
    other_tech = _seed_user(db, "technician")
    visible_sup = _seed_user(
        db, "supervisor", first_name="Visible", last_name="Supervisor"
    )
    hidden_sup = _seed_user(
        db, "supervisor", first_name="Hidden", last_name="Supervisor"
    )

    wos.get_or_create_work_order(
        db,
        number=f"WO-OPTION-{uuid.uuid4().hex[:8]}",
        created_by_id=admin.id,
        assigned_to_id=tech.id,
        supervisor_id=visible_sup.id,
        service_type="SMR27 - Belfor",
    )
    wos.get_or_create_work_order(
        db,
        number=f"WO-OPTION-{uuid.uuid4().hex[:8]}",
        created_by_id=admin.id,
        assigned_to_id=tech.id,
        supervisor_id=visible_sup.id,
        service_type="smr27 - belfor",
    )
    wos.get_or_create_work_order(
        db,
        number=f"WO-OPTION-{uuid.uuid4().hex[:8]}",
        created_by_id=admin.id,
        assigned_to_id=other_tech.id,
        supervisor_id=hidden_sup.id,
        service_type="SMR27 - Belfor Re-Work",
    )

    options = wos.get_work_order_filter_options(db, user=tech)

    assert options["service_types"] == ["SMR27 - Belfor"]
    assert options["supervisors"] == [
        {"id": visible_sup.id, "name": "Visible Supervisor"}
    ]
    assert [option["value"] for option in options["communities"]] == list(
        wo.ALL_COMMUNITY_FILTERS
    )


def test_edited_priority_case_variant_does_not_duplicate_the_filter_option(db):
    # A manual priority edit must fold into the same casefold bucket the
    # dedup in get_work_order_filter_options already uses for imported/scraped
    # values -- typing "normal" must not add a second dropdown entry next to
    # an existing "Normal".
    admin = _seed_user(db, "admin")
    tech = _seed_user(db, "technician")
    existing = wos.get_or_create_work_order(
        db,
        number=f"WO-PRIO-{uuid.uuid4().hex[:8]}",
        created_by_id=admin.id,
        assigned_to_id=tech.id,
    )
    wos.update_work_order(db, existing.id, user=admin, fields={"priority": "Normal"})

    edited = wos.get_or_create_work_order(
        db,
        number=f"WO-PRIO-{uuid.uuid4().hex[:8]}",
        created_by_id=admin.id,
        assigned_to_id=tech.id,
    )
    wos.update_work_order(db, edited.id, user=admin, fields={"priority": "normal"})

    options = wos.get_work_order_filter_options(db, user=tech)
    assert options["priorities"] == ["Normal"]


# --- priority filter -----------------------------------------------------
#
# Priority is raw NetFacilities text written by enrichment, never by the import,
# so these fixtures set it the way the enricher does: straight onto the row.

def test_list_filters_by_priority_ignoring_case_and_padding(db):
    admin = _seed_user(db, "admin")
    tech = _seed_user(db, "technician")
    emergency = _wo(db, created_by=admin, assigned_to=tech)
    normal = _wo(db, created_by=admin, assigned_to=tech)
    emergency.priority = "  Emergency  "
    normal.priority = "Normal"
    db.flush()

    found = wos.list_work_orders(db, user=tech, priority="emergency")

    assert [w.number for w in found] == [emergency.number]


def test_list_priority_none_filter_matches_null_and_blank(db):
    """"Not imported" has to mean the same thing to the filter that it means to
    the enricher, which treats NULL and whitespace-only alike."""
    admin = _seed_user(db, "admin")
    tech = _seed_user(db, "technician")
    never_enriched = _wo(db, created_by=admin, assigned_to=tech)
    blank = _wo(db, created_by=admin, assigned_to=tech)
    rated = _wo(db, created_by=admin, assigned_to=tech)
    blank.priority = "   "
    rated.priority = "Normal"
    db.flush()

    found = wos.list_work_orders(db, user=tech, priority=wo.PRIORITY_FILTER_NONE)

    assert {w.number for w in found} == {never_enriched.number, blank.number}


def test_priority_bucket_filter_matches_the_graphs_tab_grouping(db):
    """The Work Orders "Priority level" filter must agree with the same
    high/medium grouping `priority_bucket()` gives the Graphs-tab pies --
    otherwise a donut click would land on a different set than it pictured."""
    admin = _seed_user(db, "admin")
    tech = _seed_user(db, "technician")
    emergency = _wo(db, created_by=admin, assigned_to=tech)
    high = _wo(db, created_by=admin, assigned_to=tech)
    normal = _wo(db, created_by=admin, assigned_to=tech)
    routine = _wo(db, created_by=admin, assigned_to=tech)
    low = _wo(db, created_by=admin, assigned_to=tech)
    unimported = _wo(db, created_by=admin, assigned_to=tech)
    emergency.priority = "Emergency Call-Out"
    high.priority = "High"
    normal.priority = "Normal"
    routine.priority = "Routine Maintenance"
    low.priority = "Low"
    db.flush()

    def numbers(bucket):
        return {w.number for w in wos.list_work_orders(db, user=tech, priority_bucket=bucket)}

    high_numbers = numbers("high")
    assert {emergency.number, high.number} <= high_numbers
    assert not {normal.number, routine.number, low.number, unimported.number} & high_numbers

    medium_numbers = numbers("medium")
    assert {normal.number, routine.number} <= medium_numbers
    assert not {emergency.number, high.number, low.number, unimported.number} & medium_numbers

    with pytest.raises(WorkOrderStateError):
        wos.list_work_orders(db, user=tech, priority_bucket="low")


def test_filter_options_report_distinct_priorities(db):
    admin = _seed_user(db, "admin")
    tech = _seed_user(db, "technician")
    first = _wo(db, created_by=admin, assigned_to=tech)
    second = _wo(db, created_by=admin, assigned_to=tech)
    third = _wo(db, created_by=admin, assigned_to=tech)
    unenriched = _wo(db, created_by=admin, assigned_to=tech)
    first.priority = "Normal"
    second.priority = "normal"  # same value, vendor spelling drift
    third.priority = "Emergency"
    unenriched.priority = None  # contributes no option of its own
    db.flush()

    options = wos.get_work_order_filter_options(db, user=tech)

    assert options["priorities"] == ["Emergency", "Normal"]


def test_list_limit_applies_after_scheduled_date_sort(db):
    sup = _seed_user(db, "supervisor")
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    number_prefix = f"WO-LIMIT-{uuid.uuid4().hex[:8]}"
    created = []
    for i in range(13):
        w = _wo(
            db,
            created_by=sup,
            supervisor=sup,
            number=f"{number_prefix}-{i:02d}",
        )
        # Creation order intentionally opposes schedule order, proving the cap is
        # applied only after scheduled-date sorting.
        w.created_at = base + timedelta(minutes=i)
        w.schedule_date = f"7/{13 - i}/2026"
        created.append(w)
    db.flush()

    uncapped = wos.list_work_orders(db, user=sup, search=number_prefix)
    assert len(uncapped) == 13
    assert [work_order.id for work_order in uncapped] == [
        work_order.id for work_order in created
    ]

    # Capped at 10: exactly the first 10 in scheduled-date order.
    capped = wos.list_work_orders(
        db, user=sup, search=number_prefix, limit=10
    )
    assert len(capped) == 10
    assert [work_order.id for work_order in capped] == [
        work_order.id for work_order in created[:10]
    ]


def test_archived_work_order_hidden(db):
    sup = _seed_user(db, "supervisor")
    w = _wo(db, created_by=sup)
    _close(db, w, user=sup)
    assert w.id not in {x.id for x in wos.list_work_orders(db, user=sup)}
    with pytest.raises(WorkOrderNotFoundError):
        wos.get_work_order(db, w.id, user=sup)


def test_archived_item_cannot_be_logged(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)
    item = _seed_item(db, 100)
    item.archived_at = datetime.now(timezone.utc)
    db.flush()
    with pytest.raises(ItemNotFoundError):
        wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(1))


# --------------------------------------------------------------------------
# X3: the ceiling, and the branch it changed
# --------------------------------------------------------------------------

def test_omitting_limit_still_returns_every_matching_row_in_the_same_order(db):
    """X3 removed `list_work_orders`' separate uncapped branch.

    An omitted `limit` now runs the same rank-then-hydrate path a set `limit`
    takes, with `MAX_LIST_ROWS` as the effective cap. This is the one place the
    change switches which code path executes, so it is pinned directly: the
    default call must agree with an explicit large limit, row for row and in
    order.
    """
    admin = _seed_user(db, "admin")
    for index in range(5):
        wos.get_or_create_work_order(
            db,
            number=f"WO-CAP-{uuid.uuid4().hex[:8]}",
            created_by_id=admin.id,
            schedule_date=f"7/{20 + index}/2026",
        )

    default_call = wos.list_work_orders(db, user=admin)
    explicit_call = wos.list_work_orders(db, user=admin, limit=list_limits.MAX_LIST_ROWS)

    assert [w.id for w in default_call] == [w.id for w in explicit_call]
    assert len(default_call) >= 5


def test_the_ceiling_caps_the_default_call_and_reports_it(db, monkeypatch, caplog):
    monkeypatch.setattr(list_limits, "MAX_LIST_ROWS", 2)
    caplog.set_level(logging.WARNING)

    admin = _seed_user(db, "admin")
    for index in range(4):
        wos.get_or_create_work_order(
            db,
            number=f"WO-CEIL-{uuid.uuid4().hex[:8]}",
            created_by_id=admin.id,
            schedule_date=f"7/{20 + index}/2026",
        )

    rows = wos.list_work_orders(db, user=admin)

    assert len(rows) == 2
    truncations = [
        r.fields["list"] for r in caplog.records if r.getMessage() == "list.truncated"
    ]
    assert "work_orders" in truncations


def test_a_callers_own_smaller_limit_is_not_reported_as_truncation(db, monkeypatch, caplog):
    """The Work Orders page browses 10 cards by default. That is the caller
    getting exactly what it asked for, not the ceiling biting -- reporting it
    would fill the logs with false alarms and train everyone to ignore the one
    signal this item exists to produce."""
    monkeypatch.setattr(list_limits, "MAX_LIST_ROWS", 100)
    caplog.set_level(logging.WARNING)

    admin = _seed_user(db, "admin")
    for index in range(4):
        wos.get_or_create_work_order(
            db,
            number=f"WO-SMALL-{uuid.uuid4().hex[:8]}",
            created_by_id=admin.id,
            schedule_date=f"7/{20 + index}/2026",
        )

    rows = wos.list_work_orders(db, user=admin, limit=2)

    assert len(rows) == 2
    assert [r for r in caplog.records if r.getMessage() == "list.truncated"] == []


# --- Review handoff permission (pure: no DB) -------------------------------
#
# `_require_review_handoff_permission` reads only `user.id`, `user.role`,
# `work_order.supervisor_id`, and the two assignment attributes, all through
# `getattr` with fallbacks -- so stand-ins are enough and these run on a
# machine with no database.

def _review_stub_work_order(supervisor_id=None, assigned_to_id=None):
    """Minimal stand-in for the four attributes the handoff gate reads."""
    return SimpleNamespace(
        supervisor_id=supervisor_id,
        assigned_to_id=assigned_to_id,
        technician_assignments=(),
    )


def test_techfm_oa_cannot_send_a_work_order_to_review():
    # The single capability an Admin has and a TechFM OA does not. No special
    # case implements this -- it falls out of ranking below Admin -- so the
    # rule needs a test of its own or a future re-rank would silently grant it.
    actor = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_TECHFM_OA)
    with pytest.raises(RoleManagementError):
        wos._require_review_handoff_permission(_review_stub_work_order(), actor)


def test_techfm_oa_cannot_review_even_as_the_routed_supervisor():
    # TechFM OA IS a valid routing target (WORK_ORDER_SUPERVISOR_ROLES), so
    # this is reachable in production: they own the work order operationally
    # and still hand the final step to an Admin, Owner, or routed Supervisor.
    actor = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_TECHFM_OA)
    with pytest.raises(RoleManagementError):
        wos._require_review_handoff_permission(
            _review_stub_work_order(supervisor_id=actor.id), actor
        )


def test_admin_and_owner_still_send_work_orders_to_review():
    for role in (roles.ROLE_ADMIN, roles.ROLE_OWNER):
        actor = SimpleNamespace(id=uuid.uuid4(), role=role)
        wos._require_review_handoff_permission(_review_stub_work_order(), actor)


def test_unassigned_routed_supervisor_still_sends_to_review():
    actor = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_SUPERVISOR)
    wos._require_review_handoff_permission(
        _review_stub_work_order(supervisor_id=actor.id), actor
    )


# --- tracked labor sessions ----------------------------------------------

def _sessions(db, work_order):
    return (
        db.query(WorkOrderLaborSession)
        .filter(WorkOrderLaborSession.work_order_id == work_order.id)
        .order_by(WorkOrderLaborSession.started_at)
        .all()
    )


def _labor(db, work_order):
    return (
        db.query(WorkOrderLabor)
        .filter(WorkOrderLabor.work_order_id == work_order.id)
        .all()
    )


def _age_session(db, session, minutes):
    """Backdate a running session so the 12-hour cap can be exercised without
    a clock that actually runs for half a day."""
    session.started_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    db.flush()


def test_start_tracking_opens_a_session_and_advances_to_in_progress(db):
    """Starting the clock *is* the activity that moves a pre-work row, which
    is why "Set In-Progress" stops being a button a technician has to find."""
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician", first_name="Dale", last_name="Grubb")
    w = _wo(db, created_by=sup, assigned_to=tech)
    assert w.status == "assigned"

    started = wos.start_labor_session(db, w.id, user=tech)

    assert started.status == "in_progress"
    sessions = _sessions(db, w)
    assert len(sessions) == 1
    assert sessions[0].technician_id == tech.id
    assert sessions[0].ended_at is None
    assert started.notes.endswith(f"Dale Grubb {wo.NOTE_BEGAN_WORK}")


def test_start_tracking_resumes_an_on_hold_row(db):
    """Once "nobody is tracking" *causes* On-Hold, the inverse has to hold
    too -- otherwise clocking back in after lunch costs two taps every time."""
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)
    wos.start_work_order(db, w.id, user=tech)
    wos.hold_work_order(db, w.id, user=tech)
    assert w.status == "on_hold"

    started = wos.start_labor_session(db, w.id, user=tech)

    assert started.status == "in_progress"
    assert len([s for s in _sessions(db, w) if s.ended_at is None]) == 1


def test_start_tracking_is_idempotent(db):
    """The primary field button, tapped with gloves on."""
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)

    wos.start_labor_session(db, w.id, user=tech)
    notes_after_first = w.notes
    repeated = wos.start_labor_session(db, w.id, user=tech)

    assert repeated.status == "in_progress"
    assert repeated.notes == notes_after_first
    assert len(_sessions(db, w)) == 1


@pytest.mark.parametrize("blocked", ["ready_to_complete", "completed"])
def test_start_tracking_is_refused_once_the_work_is_declared_finished(db, blocked):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)
    wos.update_work_order(db, w.id, user=sup, fields={"status": blocked})

    with pytest.raises(WorkOrderStateError):
        wos.start_labor_session(db, w.id, user=tech)


def test_stop_writes_a_labor_row_linked_to_its_session(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician", first_name="Dale", last_name="Grubb")
    w = _wo(db, created_by=sup, assigned_to=tech)
    wos.start_labor_session(db, w.id, user=tech)

    stopped = wos.stop_labor_session(db, w.id, user=tech)

    entries = _labor(db, w)
    assert len(entries) == 1
    # A session measured in milliseconds still records a minute rather than
    # zero, which `validate_labor_minutes` would refuse.
    assert entries[0].minutes == 1
    assert entries[0].technician_id == tech.id
    assert entries[0].recorded_by_id == tech.id
    session = _sessions(db, w)[0]
    assert session.ended_at is not None
    assert session.labor_id == entries[0].id
    assert session.auto_closed_at is None
    assert f"Dale Grubb {wo.NOTE_STOPPED_WORK}" in stopped.notes


def test_the_last_clock_out_puts_the_work_order_on_hold(db):
    """Nobody is working on it, and that is precisely what On-Hold now means.
    A short job therefore ends On-Hold, not finished -- finishing is Notify
    Supervisor, which is a different button."""
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)
    wos.start_labor_session(db, w.id, user=tech)

    stopped = wos.stop_labor_session(db, w.id, user=tech)

    assert stopped.status == "on_hold"
    assert wos.previous_status(stopped) == "in_progress"


def test_a_co_worker_still_tracking_keeps_the_row_in_progress(db):
    sup = _seed_user(db, "supervisor")
    a = _seed_user(db, "technician")
    b = _seed_user(db, "technician")
    w = _wo(db, created_by=sup)
    wos.update_work_order(db, w.id, user=sup, fields={"assigned_to_ids": [a.id, b.id]})
    wos.start_labor_session(db, w.id, user=a)
    wos.start_labor_session(db, w.id, user=b)

    stopped = wos.stop_labor_session(db, w.id, user=a)

    assert stopped.status == "in_progress"
    # No transition, so the router sends nothing.
    assert wos.previous_status(stopped) == "in_progress"


def test_an_idempotent_repeat_stop_neither_transitions_nor_writes_a_note(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)
    wos.start_labor_session(db, w.id, user=tech)
    wos.stop_labor_session(db, w.id, user=tech)
    notes_after_first = w.notes

    repeated = wos.stop_labor_session(db, w.id, user=tech)

    assert repeated.status == "on_hold"
    assert repeated.notes == notes_after_first
    assert wos.previous_status(repeated) == "on_hold"
    assert len(_labor(db, w)) == 1


def test_hold_stops_every_clock_on_the_work_order(db):
    """The job is paused for everyone, which is what the status means."""
    sup = _seed_user(db, "supervisor")
    a = _seed_user(db, "technician", first_name="Ada", last_name="Nunez")
    b = _seed_user(db, "technician", first_name="Bo", last_name="Reyes")
    w = _wo(db, created_by=sup)
    wos.update_work_order(db, w.id, user=sup, fields={"assigned_to_ids": [a.id, b.id]})
    wos.start_labor_session(db, w.id, user=a)
    wos.start_labor_session(db, w.id, user=b)

    held = wos.hold_work_order(db, w.id, user=a)

    assert held.status == "on_hold"
    assert all(s.ended_at is not None for s in _sessions(db, w))
    assert len(_labor(db, w)) == 2
    # Each line names the person whose clock it was, not the person who tapped.
    assert f"Ada Nunez {wo.NOTE_STOPPED_WORK}" in held.notes
    assert f"Bo Reyes {wo.NOTE_STOPPED_WORK}" in held.notes


def test_resume_starts_no_clock(db):
    """Stopping a clock can only under-bill; starting one bills somebody for
    time they may not be working."""
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)
    wos.start_labor_session(db, w.id, user=tech)
    wos.hold_work_order(db, w.id, user=tech)

    resumed = wos.resume_work_order(db, w.id, user=tech)

    assert resumed.status == "in_progress"
    assert not [s for s in _sessions(db, w) if s.ended_at is None]


def test_notify_supervisor_refuses_while_a_co_worker_is_still_charging(db):
    """Superseded: a co-worker's clock is no longer auto-stopped by another
    technician's finish -- see
    test_notify_supervisor_is_blocked_while_a_co_worker_is_charging."""
    sup = _seed_user(db, "supervisor")
    a = _seed_user(db, "technician", first_name="Ada", last_name="Nunez")
    b = _seed_user(db, "technician", first_name="Bo", last_name="Reyes")
    w = _wo(db, created_by=sup)
    wos.update_work_order(db, w.id, user=sup, fields={"assigned_to_ids": [a.id, b.id]})
    wos.start_labor_session(db, w.id, user=a)
    wos.start_labor_session(db, w.id, user=b)

    with pytest.raises(WorkOrderStateError):
        wos.complete_work_order(db, w.id, user=a)

    assert sum(1 for s in _sessions(db, w) if s.ended_at is None) == 2


def test_notify_supervisor_does_not_auto_hold_despite_stopping_every_clock(db):
    """Auto-hold belongs to `/tracking/stop`. This action has its own
    destination and must not be intercepted by it."""
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)
    wos.start_labor_session(db, w.id, user=tech)

    finished = wos.complete_work_order(db, w.id, user=tech)

    assert finished.status == "ready_to_complete"


def test_a_co_worker_cannot_start_again_on_a_ready_to_complete_row(db):
    sup = _seed_user(db, "supervisor")
    a = _seed_user(db, "technician")
    b = _seed_user(db, "technician")
    w = _wo(db, created_by=sup)
    wos.update_work_order(db, w.id, user=sup, fields={"assigned_to_ids": [a.id, b.id]})
    wos.start_labor_session(db, w.id, user=a)
    wos.complete_work_order(db, w.id, user=a)

    with pytest.raises(WorkOrderStateError):
        wos.start_labor_session(db, w.id, user=b)

    # Send Back puts the crew live again.
    wos.update_work_order(db, w.id, user=sup, fields={"status": "in_progress"})
    assert wos.start_labor_session(db, w.id, user=b).status == "in_progress"


def test_a_supervisor_tracks_a_work_order_they_are_not_assigned_to(db):
    """A supervisor who does the work records it without joining the crew."""
    sup = _seed_user(db, "supervisor", first_name="Robin", last_name="Vance")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)

    wos.start_labor_session(db, w.id, user=sup)
    wos.stop_labor_session(db, w.id, user=sup)

    entries = _labor(db, w)
    assert [e.technician_id for e in entries] == [sup.id]
    assert sup.id not in wos.assigned_technician_ids(w)


def test_an_unassigned_technician_cannot_track(db):
    """The Supervisor widening does not reach down a rank."""
    sup = _seed_user(db, "supervisor")
    assigned = _seed_user(db, "technician")
    outsider = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=assigned)

    # Not visible to them at all, so it is a 404 rather than a 403 -- the
    # existence of the row is not leaked.
    with pytest.raises(WorkOrderNotFoundError):
        wos.start_labor_session(db, w.id, user=outsider)


def test_starting_elsewhere_closes_the_clock_on_the_previous_work_order(db):
    """A technician who drove to the next job should not have to remember to
    clock out of the last one -- and the unique index makes two open sessions
    impossible anyway. The abandoned row auto-holds and is handed back through
    `side_transitions` so its notification is not lost."""
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician", first_name="Dale", last_name="Grubb")
    first = _wo(db, created_by=sup, assigned_to=tech)
    second = _wo(db, created_by=sup, assigned_to=tech)
    wos.start_labor_session(db, first.id, user=tech)

    started = wos.start_labor_session(db, second.id, user=tech)

    assert started.status == "in_progress"
    assert len([s for s in _sessions(db, second) if s.ended_at is None]) == 1
    # The abandoned job closed, billed, and put itself On-Hold.
    assert not [s for s in _sessions(db, first) if s.ended_at is None]
    assert len(_labor(db, first)) == 1
    db.refresh(first)
    assert first.status == "on_hold"
    carried = wos.side_transitions(started)
    assert [row.id for row in carried] == [first.id]
    assert wos.previous_status(carried[0]) == "in_progress"


def test_only_one_running_session_per_person_is_possible(db):
    """Enforced by the partial unique index rather than by a service check
    that races."""
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)
    wos.start_labor_session(db, w.id, user=tech)

    db.add(
        WorkOrderLaborSession(
            id=uuid.uuid4(),
            work_order_id=w.id,
            technician_id=tech.id,
            started_at=datetime.now(timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_archive_stops_running_sessions(db):
    """An explicit action with an actor, so the stop is at the real clock
    time and there is nothing to guess."""
    admin = _seed_user(db, "admin")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=admin, assigned_to=tech)
    wos.start_labor_session(db, w.id, user=tech)

    wos.archive_work_order(db, w.id, user=admin)

    assert not [s for s in _sessions(db, w) if s.ended_at is None]
    assert len(_labor(db, w)) == 1
    # Restoring does not resume it.
    wos.restore_work_order(db, w.id, user=admin)
    assert not [s for s in _sessions(db, w) if s.ended_at is None]


@pytest.mark.parametrize("target", ["on_hold", "ready_to_complete", "completed"])
def test_a_supervisor_patch_into_a_stopping_status_stops_every_clock(db, target):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)
    wos.start_labor_session(db, w.id, user=tech)

    wos.update_work_order(db, w.id, user=sup, fields={"status": target})

    assert not [s for s in _sessions(db, w) if s.ended_at is None]
    assert len(_labor(db, w)) == 1


def test_an_over_cap_session_closes_at_the_capped_time_and_is_flagged(db):
    """The log must agree with the labor row it produced, so the line is
    stamped at the capped instant rather than at the moment it was noticed."""
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)
    wos.start_labor_session(db, w.id, user=tech)
    session = _sessions(db, w)[0]
    _age_session(db, session, 14 * 60)
    started_at = session.started_at

    # Any read repairs it -- the cap is lazy because this app has no scheduler.
    wos.get_work_order(db, w.id, user=sup)

    session = _sessions(db, w)[0]
    assert session.ended_at is not None
    assert session.auto_closed_at is not None
    assert session.ended_at == started_at + timedelta(
        minutes=wo.LABOR_SESSION_MAX_MINUTES
    )
    entries = _labor(db, w)
    assert [e.minutes for e in entries] == [wo.LABOR_SESSION_MAX_MINUTES]
    # Nobody stopped it, so no actor is credited with recording it.
    assert entries[0].recorded_by_id is None
    db.refresh(w)
    assert wo.format_note_timestamp(session.ended_at) in w.notes


def test_the_lazy_cap_does_not_auto_hold(db):
    """A status change and a supervisor's phone buzzing as a side effect of
    somebody opening a card would be indefensible."""
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)
    wos.start_labor_session(db, w.id, user=tech)
    _age_session(db, _sessions(db, w)[0], 14 * 60)

    refreshed = wos.get_work_order(db, w.id, user=sup)

    assert refreshed.status == "in_progress"


def test_an_open_session_contributes_nothing_to_billing(db):
    """The property that makes tracked time additive rather than a rewrite of
    the billing path."""
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)
    wos.start_labor_session(db, w.id, user=tech)

    assert _labor(db, w) == []
    assert wo.billed_labor_minutes(sum(e.minutes for e in _labor(db, w))) == 0


def test_start_and_stop_each_append_exactly_one_note_line(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)

    started = wos.start_labor_session(db, w.id, user=tech)
    assert started.notes.count(wo.NOTE_BEGAN_WORK) == 1
    stopped = wos.stop_labor_session(db, w.id, user=tech)
    assert stopped.notes.count(wo.NOTE_BEGAN_WORK) == 1
    assert stopped.notes.count(wo.NOTE_STOPPED_WORK) == 1


# --- transition facts, for notification triggers -------------------------
#
# A notification must fire on a real transition and stay silent on a repeat.
# The narrow endpoints are all idempotent -- a slow tap fires them twice --
# so the router needs to know what the row held *before* the call, not just
# what it holds now. `previous_status` and `newly_assigned_ids` carry that
# on the returned row; nothing else in the app reads them.

def test_each_narrow_transition_reports_the_status_it_left(db):
    manager = _seed_user(db, "admin")
    worker = _seed_user(db, "technician")
    work_order = _wo(db, created_by=manager, assigned_to=worker)

    started = wos.start_work_order(db, work_order.id, user=worker)
    assert wos.previous_status(started) == "assigned"

    held = wos.hold_work_order(db, work_order.id, user=worker)
    assert wos.previous_status(held) == "in_progress"

    resumed = wos.resume_work_order(db, work_order.id, user=worker)
    assert wos.previous_status(resumed) == "on_hold"

    completed = wos.complete_work_order(db, work_order.id, user=worker)
    assert wos.previous_status(completed) == "in_progress"


@pytest.mark.parametrize(
    "transition, reach",
    [
        ("start_work_order", []),
        ("hold_work_order", ["start_work_order"]),
        ("resume_work_order", ["start_work_order", "hold_work_order"]),
        ("complete_work_order", ["start_work_order"]),
    ],
)
def test_an_idempotent_repeat_reports_no_change(db, transition, reach):
    """The double-tap guard. Repeating a transition returns the row
    unchanged, and the caller must be able to tell that apart from a real
    move -- otherwise a slow tap sends two notifications for one event."""
    manager = _seed_user(db, "admin")
    worker = _seed_user(db, "technician")
    work_order = _wo(db, created_by=manager, assigned_to=worker)
    for step in reach:
        getattr(wos, step)(db, work_order.id, user=worker)

    moved = getattr(wos, transition)(db, work_order.id, user=worker)
    assert wos.previous_status(moved) != moved.status

    repeated = getattr(wos, transition)(db, work_order.id, user=worker)
    assert wos.previous_status(repeated) == repeated.status


def test_a_patch_reports_the_status_it_left(db):
    """The PATCH is the only route out of Completed, which makes it the
    only trigger site for the reopen rule."""
    manager = _seed_user(db, "admin")
    worker = _seed_user(db, "technician")
    work_order = _wo(db, created_by=manager, assigned_to=worker)
    wos.start_work_order(db, work_order.id, user=worker)
    wos.complete_work_order(db, work_order.id, user=worker)
    # A technician's finish stops at On-Hold, so Completed is reached the only
    # way it can be now -- a supervisory PATCH.
    wos.update_work_order(
        db, work_order.id, user=manager, fields={"status": "completed"}
    )

    reopened = wos.update_work_order(
        db, work_order.id, user=manager, fields={"status": "in_progress"}
    )

    assert wos.previous_status(reopened) == "completed"
    assert reopened.status == "in_progress"


def test_a_patch_reports_only_the_newly_added_assignees(db):
    manager = _seed_user(db, "admin")
    first = _seed_user(db, "technician")
    second = _seed_user(db, "technician")
    work_order = _wo(db, created_by=manager, assigned_to=first)

    both = wos.update_work_order(
        db,
        work_order.id,
        user=manager,
        fields={"assigned_to_ids": [first.id, second.id]},
    )

    assert wos.newly_assigned_ids(both) == [second.id]


def test_re_sending_an_unchanged_assignee_list_adds_nobody(db):
    """Re-saving a form must not re-notify the whole crew."""
    manager = _seed_user(db, "admin")
    worker = _seed_user(db, "technician")
    work_order = _wo(db, created_by=manager, assigned_to=worker)

    unchanged = wos.update_work_order(
        db, work_order.id, user=manager, fields={"assigned_to_ids": [worker.id]}
    )

    assert wos.newly_assigned_ids(unchanged) == []


def test_removing_an_assignee_adds_nobody(db):
    manager = _seed_user(db, "admin")
    worker = _seed_user(db, "technician")
    work_order = _wo(db, created_by=manager, assigned_to=worker)

    emptied = wos.update_work_order(
        db, work_order.id, user=manager, fields={"assigned_to_ids": []}
    )

    assert wos.newly_assigned_ids(emptied) == []


def test_reassigning_the_only_charging_technician_auto_holds(db):
    """Closing the last running clock via reassignment must put the row
    On-Hold, same as `stop_labor_session` already does -- nobody should have
    to notice nobody is charging and push a button."""
    manager = _seed_user(db, "admin")
    old = _seed_user(db, "technician", first_name="Old", last_name="Hand")
    new = _seed_user(db, "technician", first_name="New", last_name="Hire")
    work_order = _wo(db, created_by=manager, assigned_to=old)
    wos.start_labor_session(db, work_order.id, user=old)

    updated = wos.update_work_order(
        db, work_order.id, user=manager, fields={"assigned_to_ids": [new.id]}
    )

    assert updated.status == "on_hold"


def test_reassigning_a_technician_stops_their_running_clock(db):
    """Swapping the assignee must not leave the old tech's clock running
    forever -- the row no longer belongs to them."""
    manager = _seed_user(db, "admin")
    old = _seed_user(db, "technician", first_name="Old", last_name="Hand")
    new = _seed_user(db, "technician", first_name="New", last_name="Hire")
    work_order = _wo(db, created_by=manager, assigned_to=old)
    wos.start_labor_session(db, work_order.id, user=old)

    wos.update_work_order(
        db, work_order.id, user=manager, fields={"assigned_to_ids": [new.id]}
    )

    sessions = _sessions(db, work_order)
    assert len(sessions) == 1
    assert sessions[0].technician_id == old.id
    assert sessions[0].ended_at is not None


def test_removing_a_technician_stops_their_running_clock(db):
    """Unassigning a tech entirely -- not swapping them for someone else --
    must also close their clock."""
    manager = _seed_user(db, "admin")
    worker = _seed_user(db, "technician")
    work_order = _wo(db, created_by=manager, assigned_to=worker)
    wos.start_labor_session(db, work_order.id, user=worker)

    wos.update_work_order(
        db, work_order.id, user=manager, fields={"assigned_to_ids": []}
    )

    sessions = _sessions(db, work_order)
    assert len(sessions) == 1
    assert sessions[0].ended_at is not None


def test_reassignment_only_stops_the_removed_technicians_clock(db):
    """A co-worker who stays on the row keeps running; only the one who was
    taken off it gets closed out."""
    manager = _seed_user(db, "admin")
    a = _seed_user(db, "technician", first_name="Ada", last_name="Nunez")
    b = _seed_user(db, "technician", first_name="Bo", last_name="Reyes")
    work_order = _wo(db, created_by=manager)
    wos.update_work_order(
        db, work_order.id, user=manager, fields={"assigned_to_ids": [a.id, b.id]}
    )
    wos.start_labor_session(db, work_order.id, user=a)
    wos.start_labor_session(db, work_order.id, user=b)

    wos.update_work_order(
        db, work_order.id, user=manager, fields={"assigned_to_ids": [b.id]}
    )

    sessions = {s.technician_id: s for s in _sessions(db, work_order)}
    assert sessions[a.id].ended_at is not None
    assert sessions[b.id].ended_at is None


def test_a_patch_that_touches_no_assignments_adds_nobody(db):
    """A note-only edit is not an assignment event."""
    manager = _seed_user(db, "admin")
    worker = _seed_user(db, "technician")
    work_order = _wo(db, created_by=manager, assigned_to=worker)

    noted = wos.update_work_order(
        db, work_order.id, user=manager, fields={"notes": "on my way"}
    )

    assert wos.newly_assigned_ids(noted) == []
