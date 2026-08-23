"""Pure tests for work-order domain rules (no DB).

Covers number normalization, the seven-state live workflow/mode validators,
multi-technician assignment, labor billing and the tracked-session cap, the
note-log format, fill-blanks, and visibility scope.
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


# --- priority bucket -------------------------------------------------------

def test_priority_bucket_folds_urgent_and_emergency_into_high():
    assert wo.priority_bucket("High") == wo.PRIORITY_HIGH
    assert wo.priority_bucket("URGENT") == wo.PRIORITY_HIGH
    assert wo.priority_bucket("Emergency Call-Out") == wo.PRIORITY_HIGH


def test_priority_bucket_folds_routine_and_standard_into_medium():
    assert wo.priority_bucket("Normal") == wo.PRIORITY_MEDIUM
    assert wo.priority_bucket("Routine Maintenance") == wo.PRIORITY_MEDIUM
    assert wo.priority_bucket("Standard") == wo.PRIORITY_MEDIUM


def test_priority_bucket_low_and_unknown_and_none():
    assert wo.priority_bucket("Low") == wo.PRIORITY_LOW
    assert wo.priority_bucket("Priority 3") == wo.PRIORITY_UNKNOWN
    assert wo.priority_bucket(None) == wo.PRIORITY_NONE
    assert wo.priority_bucket("") == wo.PRIORITY_NONE
    assert wo.priority_bucket("   ") == wo.PRIORITY_NONE


def test_priority_bucket_is_case_and_whitespace_insensitive():
    assert wo.priority_bucket("  hIgH  ") == wo.PRIORITY_HIGH


def test_normalize_priority_bucket_filter_accepts_high_and_medium():
    assert wo.normalize_priority_bucket_filter("high") == wo.PRIORITY_HIGH
    assert wo.normalize_priority_bucket_filter("Medium") == wo.PRIORITY_MEDIUM
    assert wo.normalize_priority_bucket_filter("  HIGH  ") == wo.PRIORITY_HIGH


def test_normalize_priority_bucket_filter_blank_means_no_filter():
    assert wo.normalize_priority_bucket_filter(None) is None
    assert wo.normalize_priority_bucket_filter("") is None
    assert wo.normalize_priority_bucket_filter("   ") is None


def test_normalize_priority_bucket_filter_rejects_unknown_values():
    with pytest.raises(WorkOrderStateError):
        wo.normalize_priority_bucket_filter("low")
    with pytest.raises(WorkOrderStateError):
        wo.normalize_priority_bucket_filter("urgent")


# --- status / mode validators --------------------------------------------

def test_validate_status_accepts_seven_live_states():
    for status in (
        wo.STATUS_CREATED,
        wo.STATUS_ASSIGNED,
        wo.STATUS_IN_PROGRESS,
        wo.STATUS_ON_HOLD,
        wo.STATUS_READY_TO_COMPLETE,
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
    """Unchanged by tracked time. Its "On-Hold is intentionally stable" rule
    still governs material and labor activity -- a supervisor logging a part
    against a held job must not restart it. Start Tracking performs its own
    explicit On-Hold -> In-Progress transition rather than widening this."""
    assert wo.status_after_activity(wo.STATUS_CREATED) == wo.STATUS_IN_PROGRESS
    assert wo.status_after_activity(wo.STATUS_ASSIGNED) == wo.STATUS_IN_PROGRESS
    assert wo.status_after_activity(wo.STATUS_IN_PROGRESS) == wo.STATUS_IN_PROGRESS
    assert wo.status_after_activity(wo.STATUS_ON_HOLD) == wo.STATUS_ON_HOLD
    assert (
        wo.status_after_activity(wo.STATUS_READY_TO_COMPLETE)
        == wo.STATUS_READY_TO_COMPLETE
    )
    assert wo.status_after_activity(wo.STATUS_COMPLETED) == wo.STATUS_COMPLETED
    assert wo.status_after_activity(wo.STATUS_REVIEW) == wo.STATUS_REVIEW


def test_a_technicians_completion_lands_ready_to_complete():
    """A Technician may finish work but may not declare it Completed --
    Completed is the billing state the Admin review queue reads.

    It lands in its own status rather than On-Hold with a note, so a
    supervisor's filter separates "the job is done and waiting on you" from
    "the crew is at lunch" without anyone opening the card."""
    assert (
        wo.completion_target_status(roles.ROLE_TECHNICIAN)
        == wo.STATUS_READY_TO_COMPLETE
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
    assert (
        wo.completion_target_status("intern") == wo.STATUS_READY_TO_COMPLETE
    )


def test_note_log_appends_central_timestamp_date_and_author():
    occurred_at = datetime(2026, 8, 5, 19, 7, tzinfo=timezone.utc)

    first = wo.append_note_log(
        None,
        "  Resident requested a return visit.  ",
        author_name="Jamie Rivera",
        occurred_at=occurred_at,
    )
    assert first == (
        "08/05/26 02:07 PM Jamie Rivera Resident requested a return visit."
    )

    second = wo.append_note_log(
        "Legacy note without metadata.",
        "Parts ordered.",
        author_name="Alex Morgan",
        occurred_at=occurred_at,
    )
    assert second == (
        "Legacy note without metadata.\n\n"
        "08/05/26 02:07 PM Alex Morgan Parts ordered."
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


# --- ready_to_complete in the vocabulary ---------------------------------

def test_ready_to_complete_sits_between_on_hold_and_completed():
    """Lifecycle order is also the order every dropdown and filter renders
    in, so its position in the tuple is part of the contract."""
    assert wo.STATUS_READY_TO_COMPLETE in wo.ALL_STATUSES
    order = list(wo.ALL_STATUSES)
    assert (
        order.index(wo.STATUS_ON_HOLD)
        < order.index(wo.STATUS_READY_TO_COMPLETE)
        < order.index(wo.STATUS_COMPLETED)
    )
    # Ready to Complete is live work. Closed is still `archived_at`.
    assert wo.ACTIVE_STATUSES == wo.ALL_STATUSES


def test_validate_status_accepts_and_names_ready_to_complete():
    wo.validate_status(wo.STATUS_READY_TO_COMPLETE)
    with pytest.raises(WorkOrderStateError) as exc:
        wo.validate_status("nonsense")
    assert "ready_to_complete" in str(exc.value)


def test_export_scope_accepts_the_new_status():
    """`validate_export_scope` reads `ALL_STATUSES`, so a supervisor can
    export their review queue the moment the constant lands."""
    wo.validate_export_scope(wo.STATUS_READY_TO_COMPLETE)


# --- note log format -----------------------------------------------------

def test_note_log_zero_pads_the_hour():
    """The old format stripped the leading zero. A padded hour is what keeps
    a column of log lines aligned."""
    entry = wo.append_note_log(
        None,
        "began work",
        author_name="Jane Doe",
        occurred_at=datetime(2026, 8, 19, 14, 5, tzinfo=timezone.utc),
    )
    assert entry == "08/19/26 09:05 AM Jane Doe began work"


def test_note_log_renders_midnight_and_noon_unambiguously():
    """12-hour clocks are where off-by-twelve bugs live."""
    midnight = wo.append_note_log(
        None,
        "began work",
        author_name="J",
        occurred_at=datetime(2026, 8, 19, 5, 0, tzinfo=timezone.utc),
    )
    noon = wo.append_note_log(
        None,
        "began work",
        author_name="J",
        occurred_at=datetime(2026, 8, 19, 17, 0, tzinfo=timezone.utc),
    )
    assert midnight.startswith("08/19/26 12:00 AM ")
    assert noon.startswith("08/19/26 12:00 PM ")


def test_note_log_treats_a_naive_timestamp_as_utc():
    naive = wo.append_note_log(
        None,
        "began work",
        author_name="J",
        occurred_at=datetime(2026, 8, 19, 19, 30),
    )
    aware = wo.append_note_log(
        None,
        "began work",
        author_name="J",
        occurred_at=datetime(2026, 8, 19, 19, 30, tzinfo=timezone.utc),
    )
    assert naive == aware == "08/19/26 02:30 PM J began work"


def test_note_log_still_rejects_an_empty_body():
    with pytest.raises(WorkOrderStateError):
        wo.append_note_log(
            None,
            "   ",
            author_name="J",
            occurred_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
        )


def test_prior_lines_in_the_old_format_are_preserved_verbatim():
    """Mixed shapes coexist and age out. Rewriting stored prose would mean
    regex-parsing every work order with no verification and no undo."""
    legacy = "[2:07 PM] [080526] [Alex Morgan] Parts ordered."
    appended = wo.append_note_log(
        legacy,
        "began work",
        author_name="Jane Doe",
        occurred_at=datetime(2026, 8, 19, 19, 30, tzinfo=timezone.utc),
    )
    assert appended == legacy + "\n\n08/19/26 02:30 PM Jane Doe began work"


# --- the 12-hour session cap ---------------------------------------------

def _at(hour, minute=0, second=0):
    return datetime(2026, 8, 19, hour, minute, second, tzinfo=timezone.utc)


def test_capped_session_minutes_under_the_cap_is_the_real_duration():
    assert wo.capped_session_minutes(_at(8), _at(9, 45), now=_at(12)) == (105, False)


def test_capped_session_minutes_at_the_cap_is_not_flagged():
    """Exactly 12 hours is a real (if long) shift, not an invented figure."""
    assert wo.capped_session_minutes(_at(8), _at(20), now=_at(21)) == (720, False)


def test_capped_session_minutes_truncates_and_flags_beyond_the_cap():
    minutes, capped = wo.capped_session_minutes(_at(8), _at(23), now=_at(23))
    assert (minutes, capped) == (wo.LABOR_SESSION_MAX_MINUTES, True)


def test_a_sub_minute_session_floors_to_one_minute():
    """Zero would trip `validate_labor_minutes`' positive-integer rule and
    turn a legitimate short visit into an error."""
    minutes, capped = wo.capped_session_minutes(_at(8), _at(8, 0, 20), now=_at(9))
    assert (minutes, capped) == (1, False)
    wo.validate_labor_minutes(minutes)


def test_a_running_session_is_measured_against_now():
    """`ended_at=None` asks what the session would bill if closed right now,
    which is how the lazy cap decides a clock has outrun itself."""
    assert wo.capped_session_minutes(_at(8), None, now=_at(9, 30)) == (90, False)
    assert wo.capped_session_minutes(_at(8), None, now=_at(23))[1] is True


def test_billed_labor_minutes_is_unchanged_by_tracking():
    """Rounding stays once, over the work order's combined total -- not per
    session. A tracker makes short sessions easy, and rounding each one to
    half an hour would silently inflate every invoice."""
    assert wo.billed_labor_minutes(0) == 0
    assert wo.billed_labor_minutes(1) == 30
    assert wo.billed_labor_minutes(30) == 30
    assert wo.billed_labor_minutes(31) == 60
    # Three 5-minute return trips bill as one half hour, not three.
    assert wo.billed_labor_minutes(5 + 5 + 5) == 30
