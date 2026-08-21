"""Database tests for the personal hub payload.

Covers the count convention (a total and two subsets, not three disjoint
buckets), the `Start on...` picker's contents and order, and the sweep that
runs before the read. The time arithmetic itself is covered by
`test_labor_day.py` and `test_labor_summary.py`; this file only checks that
the composer wires them together.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.domain import hub as hub_domain
from app.domain import labor_day
from app.domain import roles
from app.domain import work_orders as wo
from app.domain.errors import TimesheetRangeInvalidError, TimesheetRangeTooLargeError
from app.models import User, WorkOrderLaborSession, WorkOrderTechnician
from app.services import auth
from app.services import hub as hub_service
from app.services import work_orders as wos


def _seed_user(db, role=roles.ROLE_TECHNICIAN, *, first_name="Jose", last_name="Rivera"):
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


def _seed_work_order(
    db, *, created_by, assigned_to=None, number=None, status=None, supervisor=None
):
    work_order = wos.get_or_create_work_order(
        db,
        number=number or f"WO-{uuid.uuid4().hex[:8]}",
        created_by_id=created_by.id,
        assigned_to_id=assigned_to.id if assigned_to else None,
        supervisor_id=supervisor.id if supervisor else None,
    )
    if status is not None:
        work_order.status = status
        db.flush()
    return work_order


def _seed_session(db, work_order, technician, *, started_at, ended_at=None):
    session = WorkOrderLaborSession(
        id=uuid.uuid4(),
        work_order_id=work_order.id,
        technician_id=technician.id,
        started_at=started_at,
        ended_at=ended_at,
    )
    db.add(session)
    db.flush()
    return session


def test_counts_are_a_total_and_two_subsets(db):
    # "8 assigned, 1 in progress, 2 ready" describes 8 work orders, not 11.
    tech = _seed_user(db)
    for _ in range(5):
        _seed_work_order(db, created_by=tech, assigned_to=tech, status=wo.STATUS_ASSIGNED)
    _seed_work_order(db, created_by=tech, assigned_to=tech, status=wo.STATUS_IN_PROGRESS)
    for _ in range(2):
        _seed_work_order(
            db, created_by=tech, assigned_to=tech, status=wo.STATUS_READY_TO_COMPLETE
        )

    payload = hub_service.personal_hub(db, tech)

    assert payload.counts.assigned == 8
    assert payload.counts.in_progress == 1
    assert payload.counts.ready_to_complete == 2


def test_counts_include_work_assigned_through_the_technician_table(db):
    # Assignment lives in two places -- the legacy `assigned_to_id` column and
    # `work_order_technicians` rows. Counting only one silently loses work.
    tech = _seed_user(db)
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    work_order = _seed_work_order(db, created_by=creator, status=wo.STATUS_ASSIGNED)
    db.add(
        WorkOrderTechnician(work_order_id=work_order.id, technician_id=tech.id)
    )
    db.flush()

    assert hub_service.personal_hub(db, tech).counts.assigned == 1


def test_an_archived_work_order_is_excluded_everywhere(db):
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=tech, assigned_to=tech, status=wo.STATUS_ASSIGNED
    )
    work_order.archived_at = datetime.now(timezone.utc)
    db.flush()

    payload = hub_service.personal_hub(db, tech)

    assert payload.counts.assigned == 0
    assert payload.startable == []


def test_someone_elses_work_order_is_not_mine(db):
    mine = _seed_user(db)
    theirs = _seed_user(db, first_name="Marisol", last_name="Chen")
    _seed_work_order(db, created_by=theirs, assigned_to=theirs, status=wo.STATUS_ASSIGNED)

    assert hub_service.personal_hub(db, mine).counts.assigned == 0


def test_the_picker_offers_only_startable_statuses(db):
    tech = _seed_user(db)
    _seed_work_order(db, created_by=tech, assigned_to=tech, status=wo.STATUS_ASSIGNED)
    _seed_work_order(
        db, created_by=tech, assigned_to=tech, status=wo.STATUS_READY_TO_COMPLETE
    )
    _seed_work_order(db, created_by=tech, assigned_to=tech, status=wo.STATUS_COMPLETED)

    startable = hub_service.personal_hub(db, tech).startable

    assert [s.status for s in startable] == [wo.STATUS_ASSIGNED]


def test_the_picker_puts_live_work_first(db):
    tech = _seed_user(db)
    _seed_work_order(
        db, created_by=tech, assigned_to=tech, number="88301", status=wo.STATUS_CREATED
    )
    _seed_work_order(
        db, created_by=tech, assigned_to=tech, number="88302", status=wo.STATUS_ASSIGNED
    )
    _seed_work_order(
        db, created_by=tech, assigned_to=tech, number="88303", status=wo.STATUS_ON_HOLD
    )
    _seed_work_order(
        db, created_by=tech, assigned_to=tech, number="88304", status=wo.STATUS_IN_PROGRESS
    )

    startable = hub_service.personal_hub(db, tech).startable

    assert [s.number for s in startable] == ["88304", "88303", "88302", "88301"]


def test_the_picker_carries_the_raw_place_fields(db):
    # There is no server-side location composer; `workOrders.js::placeMeta`
    # owns that and needs all four inputs.
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=tech, assigned_to=tech, status=wo.STATUS_ASSIGNED
    )
    work_order.community = "Commons"
    work_order.building_number = "B3"
    work_order.unit_number = "214"
    db.flush()

    entry = hub_service.personal_hub(db, tech).startable[0]

    assert entry.community == "Commons"
    assert entry.building_number == "B3"
    assert entry.unit_number == "214"


def test_the_hub_sweeps_the_callers_forgotten_clock_before_reading(db):
    # Without this a technician who forgot to clock out on Tuesday opens the
    # hub on Wednesday to a twenty-hour running clock.
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=tech, assigned_to=tech, status=wo.STATUS_IN_PROGRESS
    )
    started = datetime.now(timezone.utc) - timedelta(hours=20)
    session = WorkOrderLaborSession(
        id=uuid.uuid4(),
        work_order_id=work_order.id,
        technician_id=tech.id,
        started_at=started,
    )
    db.add(session)
    db.flush()

    payload = hub_service.personal_hub(db, tech)

    assert payload.clock.running is None
    db.refresh(session)
    assert session.ended_at == started + timedelta(
        minutes=wo.LABOR_SESSION_MAX_MINUTES
    )


def test_the_payload_reports_the_servers_instant_and_central_day(db):
    tech = _seed_user(db)

    payload = hub_service.personal_hub(db, tech)

    assert payload.server_now.tzinfo is not None
    assert payload.day == labor_day.central_date_of(payload.server_now)
    assert payload.user.id == tech.id


def test_an_empty_hub_is_all_zeros_and_empty_lists(db):
    tech = _seed_user(db)

    payload = hub_service.personal_hub(db, tech)

    assert payload.counts.assigned == 0
    assert payload.startable == []
    assert payload.tools_out == []
    assert payload.clock.total_minutes == 0


def test_the_payload_serialises_into_the_response_schema(db):
    # The handler is called directly -- its two parameters are `Depends`
    # defaults, so this needs no HTTP client. A field renamed on either side
    # of the service/schema boundary has to fail here rather than at runtime.
    from app.routers.hub import get_hub

    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=tech, assigned_to=tech, number="88214",
        status=wo.STATUS_ASSIGNED,
    )
    wos.start_labor_session(db, work_order.id, user=tech)

    body = get_hub(user=tech, db=db).model_dump()

    assert body["user"]["role"] == roles.ROLE_TECHNICIAN
    assert body["counts"]["assigned"] == 1
    assert body["clock"]["running_session"]["number"] == "88214"
    assert body["clock"]["running_session"]["day_counting_from"] is not None
    assert body["clock"]["total_minutes_today"] == (
        body["clock"]["closed_minutes_today"]
        + body["clock"]["running_minutes_today"]
        + body["clock"]["adjustment_minutes_today"]
    )
    assert [e["number"] for e in body["timeline"]] == ["88214"]
    assert body["startable"][0]["status"] == wo.STATUS_IN_PROGRESS


# --- crew_hub (P3a) ---------------------------------------------------------

NOW = datetime(2026, 8, 20, 19, 0, tzinfo=timezone.utc)  # 2:00 PM Central


def test_crew_membership_is_derived_from_supervisor_routing(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db, first_name="Jose", last_name="Rivera")
    stranger = _seed_user(db, first_name="Marisol", last_name="Chen")
    _seed_work_order(
        db, created_by=supervisor, assigned_to=tech, supervisor=supervisor,
        status=wo.STATUS_ASSIGNED,
    )
    _seed_work_order(db, created_by=stranger, assigned_to=stranger, status=wo.STATUS_ASSIGNED)

    payload = hub_service.crew_hub(db, supervisor, now=NOW)

    ids = {t.user.id for t in payload.technicians}
    assert ids == {tech.id}
    assert stranger.id not in ids


def test_crew_membership_includes_legacy_assigned_to_id(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=supervisor, status=wo.STATUS_ASSIGNED, supervisor=supervisor
    )
    db.add(WorkOrderTechnician(work_order_id=work_order.id, technician_id=tech.id))
    db.flush()

    payload = hub_service.crew_hub(db, supervisor, now=NOW)

    assert {t.user.id for t in payload.technicians} == {tech.id}


def test_an_archived_led_work_order_contributes_no_crew(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=supervisor, assigned_to=tech, supervisor=supervisor,
        status=wo.STATUS_ASSIGNED,
    )
    work_order.archived_at = datetime.now(timezone.utc)
    db.flush()

    payload = hub_service.crew_hub(db, supervisor, now=NOW)

    assert payload.technicians == []


def test_the_supervisors_own_row_is_excluded_from_cards_and_totals(db):
    # D13: a supervisor doing hands-on work is on the same work order as
    # their crew, but their own row never appears on the board, and their
    # own tracked time never counts toward the crew total.
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=supervisor, supervisor=supervisor, status=wo.STATUS_IN_PROGRESS
    )
    db.add(WorkOrderTechnician(work_order_id=work_order.id, technician_id=tech.id))
    db.add(WorkOrderTechnician(work_order_id=work_order.id, technician_id=supervisor.id))
    db.flush()
    _seed_session(db, work_order, supervisor, started_at=NOW - timedelta(hours=3), ended_at=NOW)

    payload = hub_service.crew_hub(db, supervisor, now=NOW)

    ids = {t.user.id for t in payload.technicians}
    assert supervisor.id not in ids
    assert payload.crew_total == 1
    assert payload.crew_minutes_today == 0


def test_led_counts_are_a_total_and_two_subsets(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)
    for _ in range(5):
        _seed_work_order(
            db, created_by=supervisor, assigned_to=tech, supervisor=supervisor,
            status=wo.STATUS_ASSIGNED,
        )
    _seed_work_order(
        db, created_by=supervisor, assigned_to=tech, supervisor=supervisor,
        status=wo.STATUS_IN_PROGRESS,
    )
    for _ in range(2):
        _seed_work_order(
            db, created_by=supervisor, assigned_to=tech, supervisor=supervisor,
            status=wo.STATUS_READY_TO_COMPLETE,
        )

    payload = hub_service.crew_hub(db, supervisor, now=NOW)

    assert payload.led.total == 8
    assert payload.led.in_progress == 1
    assert payload.led.ready_to_complete == 2


def test_roll_ups_reconcile_with_the_cards(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    a = _seed_user(db, first_name="Jose", last_name="Rivera")
    b = _seed_user(db, first_name="Marisol", last_name="Chen")
    wa = _seed_work_order(
        db, created_by=supervisor, assigned_to=a, supervisor=supervisor,
        status=wo.STATUS_IN_PROGRESS,
    )
    wb = _seed_work_order(
        db, created_by=supervisor, assigned_to=b, supervisor=supervisor,
        status=wo.STATUS_ASSIGNED,
    )
    _seed_session(db, wa, a, started_at=NOW - timedelta(hours=1))  # running
    _seed_session(db, wb, b, started_at=NOW - timedelta(hours=2), ended_at=NOW - timedelta(hours=1))

    payload = hub_service.crew_hub(db, supervisor, now=NOW)

    assert payload.crew_total == len(payload.technicians) == 2
    assert payload.crew_on_clock == sum(1 for t in payload.technicians if t.running_session)
    assert payload.crew_on_clock == 1
    assert payload.crew_minutes_today == sum(t.minutes_today for t in payload.technicians)
    assert payload.crew_minutes_today == 120


def test_a_supervisor_with_no_routed_work_gets_an_empty_crew(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)

    payload = hub_service.crew_hub(db, supervisor, now=NOW)

    assert payload.technicians == []
    assert payload.attention == []
    assert payload.crew_total == 0
    assert payload.led.total == 0


def test_a_long_running_clock_flags_the_technician_and_appears_in_attention(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db, first_name="Dana", last_name="Ortiz")
    work_order = _seed_work_order(
        db, created_by=supervisor, assigned_to=tech, supervisor=supervisor,
        status=wo.STATUS_IN_PROGRESS,
    )
    _seed_session(db, work_order, tech, started_at=NOW - timedelta(hours=9))

    payload = hub_service.crew_hub(db, supervisor, now=NOW)

    card = payload.technicians[0]
    assert hub_domain.FLAG_LONG_SESSION in card.flags
    assert any(
        item.kind == "technician" and "Ortiz" in item.subject for item in payload.attention
    )


def test_an_idle_assigned_technician_is_flagged_after_the_guard_hour(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db, first_name="Marisol", last_name="Chen")
    _seed_work_order(
        db, created_by=supervisor, assigned_to=tech, supervisor=supervisor,
        status=wo.STATUS_ASSIGNED,
    )

    payload = hub_service.crew_hub(db, supervisor, now=NOW)  # NOW is 2 PM Central

    card = payload.technicians[0]
    assert hub_domain.FLAG_ASSIGNED_IDLE in card.flags
    assert any(item.kind == "technician" for item in payload.attention)


def test_last_worked_appears_on_the_card(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=supervisor, assigned_to=tech, supervisor=supervisor,
        status=wo.STATUS_ASSIGNED,
    )
    ended = NOW - timedelta(days=1)
    _seed_session(db, work_order, tech, started_at=ended - timedelta(hours=1), ended_at=ended)

    payload = hub_service.crew_hub(db, supervisor, now=NOW)

    assert payload.technicians[0].last_worked == ended


def test_a_technician_who_has_never_tracked_time_shows_never(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)
    _seed_work_order(
        db, created_by=supervisor, assigned_to=tech, supervisor=supervisor,
        status=wo.STATUS_ASSIGNED,
    )

    payload = hub_service.crew_hub(db, supervisor, now=NOW)

    assert payload.technicians[0].last_worked is None


def test_a_stale_in_progress_work_order_appears_in_attention(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=supervisor, assigned_to=tech, supervisor=supervisor,
        number="88102", status=wo.STATUS_IN_PROGRESS,
    )
    _seed_session(
        db, work_order, tech,
        started_at=NOW - timedelta(days=5, hours=1),
        ended_at=NOW - timedelta(days=5),
    )

    payload = hub_service.crew_hub(db, supervisor, now=NOW)

    assert any(
        item.kind == "work_order" and "88102" in item.subject for item in payload.attention
    )


def test_a_fresh_in_progress_work_order_is_not_stale(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=supervisor, assigned_to=tech, supervisor=supervisor,
        number="88103", status=wo.STATUS_IN_PROGRESS,
    )
    _seed_session(db, work_order, tech, started_at=NOW - timedelta(hours=1), ended_at=NOW)

    payload = hub_service.crew_hub(db, supervisor, now=NOW)

    assert not any(
        item.kind == "work_order" and "88103" in item.subject for item in payload.attention
    )


def test_a_created_or_ready_work_order_is_never_stale(db):
    # Stale only applies to in_progress/on_hold -- work that hasn't started
    # or is already done waiting on review is not "stuck." (The technician
    # still earns their own assigned_idle flag here -- that is a separate
    # rule under test elsewhere -- so this only checks the work_order kind.)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)
    _seed_work_order(
        db, created_by=supervisor, assigned_to=tech, supervisor=supervisor,
        number="88104", status=wo.STATUS_CREATED,
    )

    payload = hub_service.crew_hub(db, supervisor, now=NOW)

    assert not any(item.kind == "work_order" for item in payload.attention)


def test_the_sweep_repairs_a_crew_members_forgotten_clock(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=supervisor, assigned_to=tech, supervisor=supervisor,
        status=wo.STATUS_IN_PROGRESS,
    )
    started = datetime.now(timezone.utc) - timedelta(hours=20)
    session = WorkOrderLaborSession(
        id=uuid.uuid4(), work_order_id=work_order.id, technician_id=tech.id,
        started_at=started,
    )
    db.add(session)
    db.flush()

    payload = hub_service.crew_hub(db, supervisor)

    assert payload.technicians[0].running_session is None
    db.refresh(session)
    assert session.ended_at == started + timedelta(minutes=wo.LABOR_SESSION_MAX_MINUTES)


def test_the_crew_payload_serialises_into_the_response_schema(db):
    from app.routers.hub import get_hub_crew

    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db, first_name="Jose", last_name="Rivera")
    work_order = _seed_work_order(
        db, created_by=supervisor, assigned_to=tech, supervisor=supervisor,
        number="88214", status=wo.STATUS_IN_PROGRESS,
    )
    wos.start_labor_session(db, work_order.id, user=tech)

    body = get_hub_crew(user=supervisor, db=db).model_dump()

    assert body["led"]["total"] == 1
    assert body["crew_total"] == 1
    assert body["crew_on_clock"] == 1
    assert body["technicians"][0]["user"]["id"] == tech.id
    assert body["technicians"][0]["running_session"]["number"] == "88214"


# --- admin_hub (P4 slice 1: the company-wide time summary) -----------------


def test_admin_hub_sums_supervisors_and_technicians_separately(db):
    # Bucketed by account role, not by what work was clocked on: a
    # supervisor doing hands-on work still lands in the supervisor bucket.
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    supervisor_a = _seed_user(db, roles.ROLE_SUPERVISOR, first_name="Jose", last_name="Rivera")
    supervisor_b = _seed_user(db, roles.ROLE_SUPERVISOR, first_name="Dana", last_name="Ortiz")
    tech = _seed_user(db, roles.ROLE_TECHNICIAN, first_name="Marisol", last_name="Chen")
    wo_a = _seed_work_order(db, created_by=creator, assigned_to=supervisor_a, status=wo.STATUS_IN_PROGRESS)
    wo_b = _seed_work_order(db, created_by=creator, assigned_to=supervisor_b, status=wo.STATUS_IN_PROGRESS)
    wo_c = _seed_work_order(db, created_by=creator, assigned_to=tech, status=wo.STATUS_IN_PROGRESS)
    _seed_session(db, wo_a, supervisor_a, started_at=NOW - timedelta(hours=1), ended_at=NOW)
    _seed_session(db, wo_b, supervisor_b, started_at=NOW - timedelta(hours=2), ended_at=NOW)
    _seed_session(db, wo_c, tech, started_at=NOW - timedelta(minutes=30), ended_at=NOW)

    payload = hub_service.admin_hub(db, creator, now=NOW)

    assert payload.supervisor_minutes_today == 180  # 60 + 120
    assert payload.technician_minutes_today == 30


def test_admin_hub_excludes_techfm_oa_admin_and_owner_from_both_buckets(db):
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    oa = _seed_user(db, roles.ROLE_TECHFM_OA, first_name="Pat", last_name="Nguyen")
    admin = _seed_user(db, roles.ROLE_ADMIN, first_name="Lee", last_name="Park")
    owner = _seed_user(db, roles.ROLE_OWNER, first_name="Sam", last_name="Boyd")
    # `assigned_to` can't be an OA/Admin/Owner (WORK_ORDER_TECHNICIAN_ROLES
    # forbids it) -- seed the session directly against an unassigned work
    # order instead; admin_hub buckets by the session's technician_id, not
    # by work-order assignment.
    work_order = _seed_work_order(db, created_by=creator, status=wo.STATUS_IN_PROGRESS)
    for person in (oa, admin, owner):
        _seed_session(db, work_order, person, started_at=NOW - timedelta(hours=1), ended_at=NOW)

    payload = hub_service.admin_hub(db, creator, now=NOW)

    assert payload.supervisor_minutes_today == 0
    assert payload.technician_minutes_today == 0


def test_admin_hub_excludes_archived_users(db):
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    departed = _seed_user(db, roles.ROLE_SUPERVISOR, first_name="Former", last_name="Employee")
    work_order = _seed_work_order(
        db, created_by=creator, assigned_to=departed, status=wo.STATUS_IN_PROGRESS
    )
    _seed_session(db, work_order, departed, started_at=NOW - timedelta(hours=1), ended_at=NOW)
    departed.archived_at = datetime.now(timezone.utc)
    db.flush()

    payload = hub_service.admin_hub(db, creator, now=NOW)

    assert payload.supervisor_minutes_today == 0


def test_admin_hub_sweeps_a_forgotten_clock_before_summing(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _seed_work_order(
        db, created_by=supervisor, assigned_to=tech, status=wo.STATUS_IN_PROGRESS
    )
    started = datetime.now(timezone.utc) - timedelta(hours=20)
    session = WorkOrderLaborSession(
        id=uuid.uuid4(), work_order_id=work_order.id, technician_id=tech.id,
        started_at=started,
    )
    db.add(session)
    db.flush()

    payload = hub_service.admin_hub(db, supervisor)

    db.refresh(session)
    assert session.ended_at == started + timedelta(minutes=wo.LABOR_SESSION_MAX_MINUTES)
    # The capped session straddles a Central day boundary (started 20h ago,
    # real wall clock), so only part of it falls in "today" -- same reason
    # the sibling crew_hub sweep test above doesn't assert an exact total.
    # What matters here is that the sweep ran before the sum: a still-open
    # session would read as 0 minutes, so any positive total proves it.
    assert payload.technician_minutes_today > 0


def test_the_admin_payload_serialises_into_the_response_schema(db):
    from app.routers.hub import get_hub_admin

    oa = _seed_user(db, roles.ROLE_TECHFM_OA)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR, first_name="Jose", last_name="Rivera")
    work_order = _seed_work_order(
        db, created_by=oa, assigned_to=supervisor, status=wo.STATUS_IN_PROGRESS
    )
    wos.start_labor_session(db, work_order.id, user=supervisor)

    body = get_hub_admin(user=oa, db=db).model_dump()

    assert body["supervisor_minutes_today"] >= 0
    assert "technician_minutes_today" in body
    assert "server_now" in body


# --- the supervisor timesheet payload (P3b) -------------------------------


def test_timesheets_hub_is_scoped_to_the_supervisors_routed_crew(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR, first_name="Sam", last_name="Boss")
    crew_tech = _seed_user(db, first_name="Ana", last_name="Crew")
    other_tech = _seed_user(db, first_name="Not", last_name="Mine")
    _seed_work_order(
        db, created_by=supervisor, assigned_to=crew_tech, supervisor=supervisor
    )
    _seed_work_order(db, created_by=supervisor, assigned_to=other_tech)

    payload = hub_service.timesheets_hub(
        db, supervisor, start=date(2026, 8, 17), end=date(2026, 8, 17), now=NOW
    )

    assert [row.user.id for row in payload.rows] == [crew_tech.id]
    assert supervisor.id not in [row.user.id for row in payload.rows]


def test_timesheets_hub_totals_include_adjustments_at_every_level(db):
    from app.models import WorkOrderLabor

    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=supervisor, assigned_to=tech, supervisor=supervisor
    )
    day = date(2026, 8, 17)
    window_start, _ = labor_day.day_bounds(day)
    _seed_session(
        db,
        work_order,
        tech,
        started_at=window_start + timedelta(hours=1),
        ended_at=window_start + timedelta(hours=2),
    )
    db.add(
        WorkOrderLabor(
            id=uuid.uuid4(),
            work_order_id=work_order.id,
            technician_id=tech.id,
            recorded_by_id=supervisor.id,
            minutes=30,
            created_at=window_start + timedelta(hours=3),
        )
    )
    db.flush()

    payload = hub_service.timesheets_hub(
        db, supervisor, start=day, end=day, now=NOW
    )

    cell = payload.rows[0].days[0]
    assert (cell.tracked_minutes, cell.adjustment_minutes, cell.total_minutes) == (
        60,
        30,
        90,
    )
    assert payload.rows[0].total_minutes == 90
    assert payload.crew_totals_by_day[0].minutes == 90


def test_timesheets_hub_user_filter_cannot_escape_the_crew_scope(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    crew_tech = _seed_user(db, first_name="Ana")
    stranger = _seed_user(db, first_name="Outside")
    _seed_work_order(
        db, created_by=supervisor, assigned_to=crew_tech, supervisor=supervisor
    )

    included = hub_service.timesheets_hub(
        db,
        supervisor,
        start=date(2026, 8, 17),
        end=date(2026, 8, 17),
        user_id=crew_tech.id,
        now=NOW,
    )
    excluded = hub_service.timesheets_hub(
        db,
        supervisor,
        start=date(2026, 8, 17),
        end=date(2026, 8, 17),
        user_id=stranger.id,
        now=NOW,
    )

    assert [row.user.id for row in included.rows] == [crew_tech.id]
    assert excluded.rows == []


def test_timesheets_hub_validates_the_inclusive_range(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)

    with pytest.raises(TimesheetRangeInvalidError):
        hub_service.timesheets_hub(
            db,
            supervisor,
            start=date(2026, 8, 20),
            end=date(2026, 8, 19),
            now=NOW,
        )
    with pytest.raises(TimesheetRangeTooLargeError) as exc_info:
        hub_service.timesheets_hub(
            db,
            supervisor,
            start=date(2026, 1, 1),
            end=date(2026, 4, 3),
            now=NOW,
        )

    assert exc_info.value.max_days == 92


def test_timesheets_hub_marks_running_and_assigned_idle_cells(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    running_tech = _seed_user(db, first_name="Running")
    idle_tech = _seed_user(db, first_name="Idle")
    running_work = _seed_work_order(
        db, created_by=supervisor, assigned_to=running_tech, supervisor=supervisor
    )
    _seed_work_order(
        db, created_by=supervisor, assigned_to=idle_tech, supervisor=supervisor
    )
    _seed_session(db, running_work, running_tech, started_at=NOW - timedelta(hours=1))
    today = labor_day.central_date_of(NOW)

    payload = hub_service.timesheets_hub(
        db, supervisor, start=today, end=today, now=NOW
    )
    cells = {row.user.first_name: row.days[0] for row in payload.rows}

    assert hub_domain.FLAG_RUNNING in cells["Running"].flags
    assert hub_domain.FLAG_ASSIGNED_IDLE in cells["Idle"].flags


def test_timesheets_hub_never_flags_a_future_zero_day_as_idle(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)
    _seed_work_order(db, created_by=supervisor, assigned_to=tech, supervisor=supervisor)
    tomorrow = labor_day.central_date_of(NOW) + timedelta(days=1)

    payload = hub_service.timesheets_hub(
        db, supervisor, start=tomorrow, end=tomorrow, now=NOW
    )

    assert hub_domain.FLAG_ASSIGNED_IDLE not in payload.rows[0].days[0].flags


def test_timesheets_hub_sweeps_a_forgotten_crew_clock_before_reading(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)
    work_order = _seed_work_order(
        db, created_by=supervisor, assigned_to=tech, supervisor=supervisor
    )
    started = datetime.now(timezone.utc) - timedelta(hours=20)
    session = _seed_session(db, work_order, tech, started_at=started)
    start_day = labor_day.central_date_of(started)
    end_day = labor_day.central_date_of(datetime.now(timezone.utc))

    payload = hub_service.timesheets_hub(
        db, supervisor, start=start_day, end=end_day
    )

    db.refresh(session)
    assert session.ended_at == started + timedelta(minutes=wo.LABOR_SESSION_MAX_MINUTES)
    assert all(
        hub_domain.FLAG_RUNNING not in day.flags
        for day in payload.rows[0].days
    )


def test_timesheet_csv_uses_h_mm_and_includes_the_crew_total(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db, first_name="Jordan", last_name="Rivera")
    work_order = _seed_work_order(
        db, created_by=supervisor, assigned_to=tech, supervisor=supervisor
    )
    day = date(2026, 8, 17)
    window_start, _ = labor_day.day_bounds(day)
    _seed_session(
        db,
        work_order,
        tech,
        started_at=window_start + timedelta(hours=1),
        ended_at=window_start + timedelta(hours=8, minutes=5),
    )

    payload = hub_service.timesheets_hub(
        db, supervisor, start=day, end=day, now=NOW
    )
    lines = hub_service.timesheet_csv(payload).splitlines()

    assert lines == [
        "Technician,2026-08-17,Total",
        "Jordan Rivera,7:05,7:05",
        "Crew total,7:05,7:05",
    ]
