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
from app.models import Item, Transaction, User, UserRequest
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

    wos.start_work_order(db, work_order.id, user=worker)
    completed = wos.complete_work_order(db, work_order.id, user=worker)

    assert completed.status == "completed"
    assert completed.completed_at is not None
    completed_at = completed.completed_at
    # A retry or double tap must not advance again or replace the timestamp.
    repeated = wos.complete_work_order(db, work_order.id, user=worker)
    assert repeated.status == "completed"
    assert repeated.completed_at == completed_at


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
    wos.complete_work_order(db, work_order.id, user=worker)

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
            db, w.id, user=tech1, technician_id=tech1.id, minutes=35
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
    assert re.fullmatch(
        r"\[\d{1,2}:\d{2} [AP]M\] \[\d{6}\] \[Jamie Rivera\] "
        r"Call resident before arrival\.",
        saved.notes,
    )

    first_entry = saved.notes
    appended = wos.update_work_order(
        db, w.id, user=tech, fields={"notes": "Parts ordered."}
    )
    assert appended.notes.startswith(first_entry + "\n\n")
    assert appended.notes.endswith("[Jamie Rivera] Parts ordered.")

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
        },
    )
    assert metadata.location == "Commons 101"
    assert metadata.description == "Leaking sink"

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
