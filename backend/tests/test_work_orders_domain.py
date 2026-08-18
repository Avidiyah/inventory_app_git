"""Pure tests for work-order domain rules (no DB).

Covers number normalization, the six-state live workflow/mode validators,
multi-technician assignment, labor billing, fill-blanks, and visibility scope.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

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

def test_validate_status_accepts_six_live_states():
    for status in (
        wo.STATUS_CREATED,
        wo.STATUS_ASSIGNED,
        wo.STATUS_IN_PROGRESS,
        wo.STATUS_ON_HOLD,
        wo.STATUS_COMPLETED,
        wo.STATUS_REVIEW,
    ):
        wo.validate_status(status)
    # alias used by the router is the same function
    assert wo.validate_active_status is wo.validate_status


def test_validate_status_rejects_planning_closed_and_junk():
    # planning is a Mass Stage stage concept, not a work-order state anymore.
    with pytest.raises(WorkOrderStateError):
        wo.validate_status("planning")
    with pytest.raises(WorkOrderStateError):
        wo.validate_status("closed")
    with pytest.raises(WorkOrderStateError):
        wo.validate_status("archived")


def test_community_filter_normalizes_labels_and_rejects_unknown_values():
    assert wo.normalize_community_filter(None) is None
    assert wo.normalize_community_filter("   ") is None
    assert wo.normalize_community_filter("Scholars") == wo.COMMUNITY_SCHOLARS
    assert wo.normalize_community_filter("Young Hall") == wo.COMMUNITY_YOUNG_HALL
    assert wo.normalize_community_filter("young_hall") == wo.COMMUNITY_YOUNG_HALL
    with pytest.raises(WorkOrderStateError, match="Community"):
        wo.normalize_community_filter("downtown")


def test_schedule_date_parser_accepts_vendor_and_iso_dates_safely():
    assert wo.parse_schedule_date("7/20/2026") == date(2026, 7, 20)
    assert wo.parse_schedule_date("7/20/2026 5:40") == date(2026, 7, 20)
    assert wo.parse_schedule_date("7/24/26 - 8:00am") == date(2026, 7, 24)
    assert wo.parse_schedule_date("2026-08-04") == date(2026, 8, 4)
    assert wo.parse_schedule_date(None) is None
    assert wo.parse_schedule_date("not a date") is None
    assert wo.parse_schedule_date("2/30/2026") is None


def test_initial_status_and_technician_assignment_reconciliation():
    technician_id = uuid.uuid4()
    assert wo.initial_status(None) == wo.STATUS_CREATED
    assert wo.initial_status(technician_id) == wo.STATUS_ASSIGNED
    assert (
        wo.reconcile_assignment_status(wo.STATUS_CREATED, technician_id)
        == wo.STATUS_ASSIGNED
    )
    assert (
        wo.reconcile_assignment_status(wo.STATUS_ASSIGNED, None)
        == wo.STATUS_CREATED
    )
    # Reassigning work already underway never rewinds the lifecycle.
    assert (
        wo.reconcile_assignment_status(wo.STATUS_IN_PROGRESS, None)
        == wo.STATUS_IN_PROGRESS
    )
    assert (
        wo.reconcile_assignment_status(wo.STATUS_ON_HOLD, None)
        == wo.STATUS_ON_HOLD
    )


def test_first_activity_advances_only_prework_states():
    assert wo.status_after_activity(wo.STATUS_CREATED) == wo.STATUS_IN_PROGRESS
    assert wo.status_after_activity(wo.STATUS_ASSIGNED) == wo.STATUS_IN_PROGRESS
    assert wo.status_after_activity(wo.STATUS_IN_PROGRESS) == wo.STATUS_IN_PROGRESS
    assert wo.status_after_activity(wo.STATUS_ON_HOLD) == wo.STATUS_ON_HOLD
    assert wo.status_after_activity(wo.STATUS_COMPLETED) == wo.STATUS_COMPLETED
    assert wo.status_after_activity(wo.STATUS_REVIEW) == wo.STATUS_REVIEW


def test_a_technicians_completion_lands_on_hold():
    """A Technician may finish work but may not declare it Completed --
    Completed is the billing state the Admin review queue reads."""
    assert (
        wo.completion_target_status(roles.ROLE_TECHNICIAN) == wo.STATUS_ON_HOLD
    )


def test_supervisor_and_above_still_complete():
    for role in (
        roles.ROLE_SUPERVISOR,
        roles.ROLE_TECHFM_OA,
        roles.ROLE_ADMIN,
        roles.ROLE_OWNER,
    ):
        assert wo.completion_target_status(role) == wo.STATUS_COMPLETED


def test_an_internal_caller_completes():
    """`None` is the no-role internal caller every other rule here honours."""
    assert wo.completion_target_status(None) == wo.STATUS_COMPLETED


def test_an_unknown_role_cannot_complete():
    """`roles.rank` puts a corrupt value below Technician, so the safe
    destination is the one that bills nobody."""
    assert wo.completion_target_status("intern") == wo.STATUS_ON_HOLD


def test_note_log_appends_central_timestamp_date_and_author():
    occurred_at = datetime(2026, 8, 5, 19, 7, tzinfo=timezone.utc)

    first = wo.append_note_log(
        None,
        "  Resident requested a return visit.  ",
        author_name="Jamie Rivera",
        occurred_at=occurred_at,
    )
    assert first == (
        "[2:07 PM] [080526] [Jamie Rivera] Resident requested a return visit."
    )

    second = wo.append_note_log(
        "Legacy note without metadata.",
        "Parts ordered.",
        author_name="Alex Morgan",
        occurred_at=occurred_at,
    )
    assert second == (
        "Legacy note without metadata.\n\n"
        "[2:07 PM] [080526] [Alex Morgan] Parts ordered."
    )

    with pytest.raises(WorkOrderStateError, match="Note text"):
        wo.append_note_log(
            first,
            "   ",
            author_name="Jamie Rivera",
            occurred_at=occurred_at,
        )


def test_labor_billing_rounds_combined_minutes_up_to_half_hour():
    assert wo.billed_labor_minutes(0) == 0
    assert wo.billed_labor_minutes(1) == 30
    assert wo.billed_labor_minutes(30) == 30
    assert wo.billed_labor_minutes(31) == 60
    assert wo.billed_labor_minutes(75) == 90
    assert wo.labor_charge(75) == Decimal("93.75")
    with pytest.raises(WorkOrderStateError):
        wo.billed_labor_minutes(-1)
    with pytest.raises(WorkOrderStateError):
        wo.validate_labor_minutes(0)


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


def test_supervisor_sees_unassigned_and_self_routed_work_orders():
    me, other, tech = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    # Creator identity no longer controls supervisor visibility: an unrouted
    # row is the shared pickup queue.
    assert wo.can_view_work_order(
        roles.ROLE_SUPERVISOR,
        created_by_id=other,
        assigned_to_id=tech,
        user_id=me,
        supervisor_id=None,
    )
    assert wo.can_view_work_order(
        roles.ROLE_SUPERVISOR,
        created_by_id=other,
        assigned_to_id=tech,
        user_id=me,
        supervisor_id=me,
    )


def test_supervisor_sees_other_routing_only_when_assigned_as_worker():
    me, importer, tech = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    other_supervisor = uuid.uuid4()
    assert not wo.can_view_work_order(
        roles.ROLE_SUPERVISOR,
        created_by_id=me,
        assigned_to_id=tech,
        user_id=me,
        supervisor_id=other_supervisor,
    )
    assert wo.can_view_work_order(
        roles.ROLE_SUPERVISOR,
        created_by_id=importer,
        assigned_to_id=tech,
        assigned_to_ids=[tech, me],
        user_id=me,
        supervisor_id=other_supervisor,
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


def test_technician_visibility_accepts_any_plural_assignment():
    me, primary, creator = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert wo.can_view_work_order(
        roles.ROLE_TECHNICIAN,
        created_by_id=creator,
        assigned_to_id=primary,
        assigned_to_ids=[primary, me],
        user_id=me,
    )
