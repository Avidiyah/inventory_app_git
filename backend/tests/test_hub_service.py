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
