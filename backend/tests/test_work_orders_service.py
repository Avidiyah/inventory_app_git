"""Database integration tests for the standalone work-order service.

Exercises find-or-create-by-number (the import path: case-insensitive,
fill-blanks, restore-on-archived), resolve-by-number (every other surface, which
may not create), dispense vs retroactive logging, edit auto-correction, delete
reversal, the stock-neutral void, archive/restore, and role scoping. Skip if no
DB.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.domain.errors import (
    InvalidAssigneeError,
    ItemNotFoundError,
    NegativeQuantityError,
    RoleManagementError,
    WorkOrderNotFoundError,
    WorkOrderStateError,
)
from app.models import Item, Transaction, User
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


def _seed_user(db, role):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _wo(db, *, created_by, assigned_to=None, number=None):
    return wos.get_or_create_work_order(
        db,
        number=number or f"WO-{uuid.uuid4().hex[:8]}",
        created_by_id=created_by.id,
        assigned_to_id=assigned_to.id if assigned_to else None,
    )


def _close(db, work_order, *, user):
    """Move a fixture through Review before exercising Closed/archive behavior."""
    wos.update_work_order(
        db, work_order.id, user=user, fields={"status": "review"}
    )
    wos.archive_work_order(db, work_order.id, user=user)


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

    first = wos.add_work_order_labor(
        db, w.id, user=tech1, technician_id=tech1.id, minutes=35
    )
    second = wos.add_work_order_labor(
        db, w.id, user=sup, technician_id=tech2.id, minutes=40
    )
    detail = wos.get_work_order(db, w.id, user=tech2)

    assert detail.status == "in_progress"
    assert {entry.id for entry in detail.labor_entries} == {first.id, second.id}
    assert sum(entry.minutes for entry in detail.labor_entries) == 75

    updated = wos.update_work_order_labor(
        db, w.id, first.id, user=tech1, minutes=50
    )
    assert updated.minutes == 50

    with pytest.raises(RoleManagementError):
        wos.update_work_order_labor(
            db, w.id, second.id, user=tech1, minutes=60
        )

    wos.delete_work_order_labor(db, w.id, first.id, user=tech1)
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


def test_archived_number_is_restored_on_reimport(db):
    # A re-import of an archived number revives it -- the import is the one path
    # that may create, so it is also the one reference that un-archives.
    sup = _seed_user(db, "supervisor")
    a = _wo(db, created_by=sup)
    _close(db, a, user=sup)
    b = wos.get_or_create_work_order(db, number=a.number.lower(), created_by_id=sup.id)
    assert b.id == a.id
    assert b.archived_at is None


def test_assignee_must_be_technician(db):
    sup = _seed_user(db, "supervisor")
    other = _seed_user(db, "supervisor")
    with pytest.raises(InvalidAssigneeError):
        wos.get_or_create_work_order(
            db, number="WO-NT", assigned_to_id=other.id, created_by_id=sup.id
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
    # Scoping still applies: a supervisor may not discover another's work order.
    mine = _seed_user(db, "supervisor")
    theirs = _seed_user(db, "supervisor")
    a = _wo(db, created_by=theirs)
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
    a = _wo(db, created_by=theirs)
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


def test_dispense_overdraft_refused(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 2)
    w = _wo(db, created_by=sup, assigned_to=tech)
    with pytest.raises(NegativeQuantityError):
        wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(5))
    db.refresh(item)
    assert item.quantity == Decimal(2)


def test_dispense_edit_auto_corrects_stock(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100)
    w = _wo(db, created_by=sup, assigned_to=tech)
    line = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(4))

    edited = wos.update_work_order_item(db, w.id, line.id, user=tech, quantity=Decimal(10))
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

    wos.update_work_order_item(db, w.id, line.id, user=tech, quantity=Decimal(1))
    db.refresh(item)
    assert item.quantity == Decimal(99)


def test_dispense_delete_returns_stock_and_voids_txn(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    item = _seed_item(db, 100)
    w = _wo(db, created_by=sup, assigned_to=tech)
    line = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(4))
    txn_id = line.transaction_id

    wos.delete_work_order_item(db, w.id, line.id, user=tech)
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

    wos.update_work_order_item(db, w.id, disp.id, user=tech, quantity=Decimal(6))
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

    completed = wos.update_work_order(db, w.id, user=tech, fields={"status": "completed"})
    assert completed.status == "completed"
    assert completed.completed_at is not None

    line = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(2))
    assert line.quantity == Decimal(2)


def test_review_retains_completion_time_and_reopen_clears_it(db):
    sup = _seed_user(db, "supervisor")
    w = _wo(db, created_by=sup)

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


def test_work_order_notes_can_be_saved_and_cleared_by_in_scope_user(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)

    saved = wos.update_work_order(
        db, w.id, user=tech, fields={"notes": "Call resident before arrival."}
    )
    assert saved.notes == "Call resident before arrival."

    cleared = wos.update_work_order(
        db, w.id, user=tech, fields={"notes": None}
    )
    assert cleared.notes is None


def test_close_requires_review(db):
    sup = _seed_user(db, "supervisor")
    w = _wo(db, created_by=sup)
    with pytest.raises(WorkOrderStateError, match="Review"):
        wos.archive_work_order(db, w.id, user=sup)
    db.refresh(w)
    assert w.archived_at is None


def test_set_invalid_status_rejected(db):
    sup = _seed_user(db, "supervisor")
    tech = _seed_user(db, "technician")
    w = _wo(db, created_by=sup, assigned_to=tech)
    with pytest.raises(WorkOrderStateError):
        wos.update_work_order(db, w.id, user=tech, fields={"status": "planning"})


# --- scoping -------------------------------------------------------------

def test_scoping_list_and_access(db):
    sup_a = _seed_user(db, "supervisor")
    sup_b = _seed_user(db, "supervisor")
    tech1 = _seed_user(db, "technician")
    tech2 = _seed_user(db, "technician")
    admin = _seed_user(db, "admin")

    a = _wo(db, created_by=sup_a, assigned_to=tech1)
    b = _wo(db, created_by=sup_b, assigned_to=tech2)

    def ids(user, **kw):
        return {w.id for w in wos.list_work_orders(db, user=user, **kw)}

    assert ids(tech1) == {a.id}
    assert ids(tech2) == {b.id}
    assert ids(sup_a) == {a.id}
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


def test_list_limit_returns_newest(db):
    sup = _seed_user(db, "supervisor")
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    created = []
    for i in range(13):
        w = _wo(db, created_by=sup)
        # Explicit strictly-increasing created_at so the newest-first ordering (and
        # thus which rows the cap keeps) is deterministic regardless of insert speed
        # -- the model default is a Python-side now() and can collide in a tight loop.
        w.created_at = base + timedelta(minutes=i)
        created.append(w)
    db.flush()

    # Uncapped: every work order, newest-first.
    assert len(wos.list_work_orders(db, user=sup)) == 13

    # Capped at 10: exactly the 10 newest-created, in newest-first order.
    capped = wos.list_work_orders(db, user=sup, limit=10)
    assert len(capped) == 10
    newest_10 = [
        w.id for w in sorted(created, key=lambda x: x.created_at, reverse=True)[:10]
    ]
    assert [w.id for w in capped] == newest_10


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
