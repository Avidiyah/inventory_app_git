"""Pure tests for work-order domain rules (no DB).

Covers number normalization, the two-state status/mode validators, the
fill-blanks merge, and the visibility scope.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid

import pytest

from app.domain import roles
from app.domain import work_orders as wo
from app.domain.errors import WorkOrderStateError


# --- identity / normalization --------------------------------------------

def test_normalize_number_trims_and_lowercases():
    assert wo.normalize_number("  WO-1 ") == "wo-1"
    assert wo.normalize_number("wo-1") == wo.normalize_number("WO-1")
    # internal whitespace is preserved (btrim only strips the ends)
    assert wo.normalize_number("A B") == "a b"


# --- status / mode validators --------------------------------------------

def test_validate_status_accepts_two_states():
    wo.validate_status(wo.STATUS_IN_PROGRESS)
    wo.validate_status(wo.STATUS_COMPLETED)
    # alias used by the router is the same function
    assert wo.validate_active_status is wo.validate_status


def test_validate_status_rejects_planning_and_junk():
    # planning is a Mass Stage stage concept, not a work-order state anymore.
    with pytest.raises(WorkOrderStateError):
        wo.validate_status("planning")
    with pytest.raises(WorkOrderStateError):
        wo.validate_status("archived")


def test_validate_mode_and_affects_stock():
    wo.validate_mode(wo.MODE_DISPENSE)
    wo.validate_mode(wo.MODE_RETROACTIVE)
    with pytest.raises(WorkOrderStateError):
        wo.validate_mode("loan")
    assert wo.affects_stock(wo.MODE_DISPENSE) is True
    assert wo.affects_stock(wo.MODE_RETROACTIVE) is False


# --- fill-blanks ---------------------------------------------------------

def test_is_blank_and_fill_blank():
    assert wo.is_blank(None)
    assert wo.is_blank("   ")
    assert not wo.is_blank("x")
    # keep a non-blank current; take incoming only when current is blank
    assert wo.fill_blank("Scholars", "Centennial") == "Scholars"
    assert wo.fill_blank(None, "Centennial") == "Centennial"
    assert wo.fill_blank("  ", "Centennial") == "Centennial"
    assert wo.fill_blank(None, None) is None


# --- visibility scope ----------------------------------------------------

def test_admin_and_owner_see_everything():
    creator, assignee, viewer = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for role in (roles.ROLE_ADMIN, roles.ROLE_OWNER):
        assert wo.can_view_work_order(
            role, created_by_id=creator, assigned_to_id=assignee, user_id=viewer
        )
    assert wo.can_view_work_order(
        None, created_by_id=creator, assigned_to_id=assignee, user_id=None
    )


def test_supervisor_sees_only_what_they_created():
    me, other, tech = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert wo.can_view_work_order(
        roles.ROLE_SUPERVISOR, created_by_id=me, assigned_to_id=tech, user_id=me
    )
    assert not wo.can_view_work_order(
        roles.ROLE_SUPERVISOR, created_by_id=other, assigned_to_id=me, user_id=me
    )


def test_technician_sees_only_what_is_assigned_to_them():
    me, creator, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert wo.can_view_work_order(
        roles.ROLE_TECHNICIAN, created_by_id=creator, assigned_to_id=me, user_id=me
    )
    assert not wo.can_view_work_order(
        roles.ROLE_TECHNICIAN, created_by_id=me, assigned_to_id=other, user_id=me
    )
    assert not wo.can_view_work_order(
        roles.ROLE_TECHNICIAN, created_by_id=creator, assigned_to_id=None, user_id=me
    )
