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
from decimal import Decimal

import pytest

from app.domain import hub as hub_domain
from app.domain import labor_day
from app.domain import roles
from app.domain import work_orders as wo
from app.domain.errors import TimesheetRangeInvalidError, TimesheetRangeTooLargeError
from app.models import Item, User, WorkOrderItem, WorkOrderLaborSession, WorkOrderTechnician
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


def _seed_item(db, price="10.00"):
    item = Item(
        barcode=f"BC-{uuid.uuid4().hex[:10]}",
        name="Test Material",
        quantity=Decimal(100),
        location="Bay 1",
        price=Decimal(price),
    )
    db.add(item)
    db.flush()
    return item


def _seed_work_order_item(db, work_order, item, *, quantity):
    line = WorkOrderItem(
        id=uuid.uuid4(),
        work_order_id=work_order.id,
        item_id=item.id,
        quantity=Decimal(quantity),
        mode="dispense",
    )
    db.add(line)
    db.flush()
    return line


def _seed_labor_entry(db, work_order, technician, *, minutes):
    from app.models import WorkOrderLabor

    entry = WorkOrderLabor(
        id=uuid.uuid4(),
        work_order_id=work_order.id,
        technician_id=technician.id,
        recorded_by_id=technician.id,
        minutes=minutes,
    )
    db.add(entry)
    db.flush()
    return entry


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


def test_personal_hub_counts_high_priority_work_assigned_to_me(db):
    tech = _seed_user(db)
    other = _seed_user(db, first_name="Other", last_name="Tech")

    mine_high = _seed_work_order(db, created_by=tech, assigned_to=tech, status=wo.STATUS_ASSIGNED)
    mine_high.priority = "High"
    mine_low = _seed_work_order(db, created_by=tech, assigned_to=tech, status=wo.STATUS_ASSIGNED)
    mine_low.priority = "Low"
    someone_elses_high = _seed_work_order(db, created_by=tech, assigned_to=other, status=wo.STATUS_ASSIGNED)
    someone_elses_high.priority = "Emergency"
    db.flush()

    payload = hub_service.personal_hub(db, tech)

    assert payload.priority.assigned == 1
    assert payload.priority.unassigned is None


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


def test_crew_hub_counts_high_priority_led_and_unassigned(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db)

    led_assigned_high = _seed_work_order(
        db, created_by=supervisor, supervisor=supervisor, assigned_to=tech, status=wo.STATUS_ASSIGNED
    )
    led_assigned_high.priority = "High"
    led_unassigned_high = _seed_work_order(
        db, created_by=supervisor, supervisor=supervisor, status=wo.STATUS_CREATED
    )
    led_unassigned_high.priority = "Urgent"
    led_low = _seed_work_order(
        db, created_by=supervisor, supervisor=supervisor, status=wo.STATUS_CREATED
    )
    led_low.priority = "Low"
    db.flush()

    payload = hub_service.crew_hub(db, supervisor, now=NOW)

    assert payload.priority.assigned == 2
    assert payload.priority.unassigned == 1


def test_crew_hub_priority_counts_exclude_other_supervisors_led_work(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    other_supervisor = _seed_user(db, roles.ROLE_SUPERVISOR, first_name="Other")

    not_mine = _seed_work_order(
        db, created_by=supervisor, supervisor=other_supervisor, status=wo.STATUS_CREATED
    )
    not_mine.priority = "High"
    db.flush()

    payload = hub_service.crew_hub(db, supervisor, now=NOW)

    assert payload.priority.assigned == 0
    assert payload.priority.unassigned == 0


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


# --- graphs_hub (P4 slice 2: guided company-wide graphs) -------------------


def test_graphs_hub_counts_live_statuses_by_community_and_service_type(db):
    creator = _seed_user(db, roles.ROLE_TECHFM_OA)
    baseline = hub_service.graphs_hub(db, creator, weeks=12, now=NOW)
    scholar = _seed_work_order(db, created_by=creator, status=wo.STATUS_CREATED)
    scholar.community = "Scholars"
    scholar.service_type = "Electrical"
    scholar.created_at = NOW - timedelta(days=10)
    shared = _seed_work_order(db, created_by=creator, status=wo.STATUS_ON_HOLD)
    shared.location = "Cimarron / Young Hall"
    shared.service_type = " electrical "
    shared.created_at = NOW - timedelta(days=4)
    closed = _seed_work_order(db, created_by=creator, status=wo.STATUS_COMPLETED)
    closed.community = "Scholars"
    closed.service_type = "Plumbing"
    closed.created_at = NOW - timedelta(days=12)
    closed.archived_at = NOW - timedelta(days=2)
    db.flush()

    payload = hub_service.graphs_hub(db, creator, weeks=12, now=NOW)
    before_communities = {row.key: row for row in baseline.communities}
    communities = {row.key: row for row in payload.communities}
    before_services = {row.key: row for row in baseline.service_types}
    services = {row.key: row for row in payload.service_types}

    assert communities[wo.COMMUNITY_SCHOLARS].counts[wo.STATUS_CREATED] == before_communities[wo.COMMUNITY_SCHOLARS].counts[wo.STATUS_CREATED] + 1
    assert communities[wo.COMMUNITY_COMMONS].counts[wo.STATUS_ON_HOLD] == before_communities[wo.COMMUNITY_COMMONS].counts[wo.STATUS_ON_HOLD] + 1
    assert communities[wo.COMMUNITY_YOUNG_HALL].counts[wo.STATUS_ON_HOLD] == before_communities[wo.COMMUNITY_YOUNG_HALL].counts[wo.STATUS_ON_HOLD] + 1
    assert services["electrical"].total == before_services.get("electrical", hub_service.GraphDistribution("", "", 0, {})).total + 2
    assert all(row.total == sum(row.counts.values()) for row in payload.communities + payload.service_types)

    before_current = baseline.duration.buckets[-1]
    current = payload.duration.buckets[-1]
    assert current.closed_count == before_current.closed_count + 1
    assert current.closed_avg_days is not None


def test_graphs_hub_keeps_empty_duration_samples_as_null(db):
    viewer = _seed_user(db, roles.ROLE_TECHFM_OA)
    payload = hub_service.graphs_hub(db, viewer, weeks=12, now=NOW)

    assert all(
        bucket.circulating_avg_age_days is None or bucket.circulating_count > 0
        for bucket in payload.duration.buckets
    )
    assert all(
        bucket.closed_avg_days is None or bucket.closed_count > 0
        for bucket in payload.duration.buckets
    )


# --- admin_hub (P4 slice 1: the company-wide time summary) -----------------


def test_admin_hub_sums_supervisors_and_technicians_separately(db):
    # Bucketed by account role, not by what work was clocked on: a
    # supervisor doing hands-on work still lands in the supervisor bucket.
    # admin_hub is deliberately unscoped (company-wide), so pre-existing
    # rows in the shared dev database (e.g. real manual-QA sessions) can
    # already be non-zero for this day -- assert on the delta this test's
    # own fixtures caused, not on an absolute total.
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    baseline = hub_service.admin_hub(db, creator, now=NOW)
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

    assert payload.supervisor_minutes_today - baseline.supervisor_minutes_today == 180  # 60 + 120
    assert payload.technician_minutes_today - baseline.technician_minutes_today == 30


def test_admin_hub_excludes_techfm_oa_admin_and_owner_from_both_buckets(db):
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    baseline = hub_service.admin_hub(db, creator, now=NOW)
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

    assert payload.supervisor_minutes_today == baseline.supervisor_minutes_today
    assert payload.technician_minutes_today == baseline.technician_minutes_today


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


def test_admin_hub_pipeline_counts_are_company_wide_and_unscoped(db):
    # The shared dev database already has live rows in it (see this plan's
    # Global Constraints), so assert on the delta this test's own fixtures
    # caused, not on an absolute total.
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    stranger = _seed_user(db, roles.ROLE_SUPERVISOR, first_name="Dana", last_name="Ortiz")
    baseline = hub_service.admin_hub(db, creator).pipeline

    _seed_work_order(db, created_by=creator, status=wo.STATUS_CREATED)
    _seed_work_order(db, created_by=creator, status=wo.STATUS_ASSIGNED)
    _seed_work_order(db, created_by=creator, status=wo.STATUS_IN_PROGRESS)
    _seed_work_order(db, created_by=creator, status=wo.STATUS_READY_TO_COMPLETE)
    _seed_work_order(db, created_by=creator, status=wo.STATUS_COMPLETED)
    _seed_work_order(db, created_by=creator, status=wo.STATUS_REVIEW)
    # A stranger's work order still counts -- the pipeline is company-wide,
    # not scoped to the caller the way `GET /hub`'s own counts are.
    _seed_work_order(db, created_by=stranger, status=wo.STATUS_CREATED)

    pipeline = hub_service.admin_hub(db, creator).pipeline

    assert pipeline.created - baseline.created == 2
    assert pipeline.assigned - baseline.assigned == 1
    assert pipeline.in_progress - baseline.in_progress == 1
    assert pipeline.ready_to_complete - baseline.ready_to_complete == 1
    assert pipeline.completed - baseline.completed == 1
    assert pipeline.review - baseline.review == 1


def test_admin_hub_counts_high_priority_company_wide_assigned_and_unassigned(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN, first_name="Jose", last_name="Rivera")
    baseline = hub_service.admin_hub(db, admin, now=NOW).priority

    assigned_high = _seed_work_order(db, created_by=admin, assigned_to=tech, status=wo.STATUS_ASSIGNED)
    assigned_high.priority = "High"
    unassigned_high = _seed_work_order(db, created_by=admin, status=wo.STATUS_CREATED)
    unassigned_high.priority = "Emergency"
    low = _seed_work_order(db, created_by=admin, status=wo.STATUS_CREATED)
    low.priority = "Low"
    db.flush()

    payload = hub_service.admin_hub(db, admin, now=NOW)

    assert payload.priority.assigned - baseline.assigned == 2
    assert payload.priority.unassigned - baseline.unassigned == 1


def test_admin_hub_priority_counts_exclude_archived_work_orders(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    baseline = hub_service.admin_hub(db, admin, now=NOW).priority

    archived = _seed_work_order(db, created_by=admin, status=wo.STATUS_CREATED)
    archived.priority = "High"
    archived.archived_at = NOW
    db.flush()

    payload = hub_service.admin_hub(db, admin, now=NOW)

    assert payload.priority.assigned == baseline.assigned
    assert payload.priority.unassigned == baseline.unassigned


def test_admin_hub_pipeline_excludes_on_hold_and_archived(db):
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    baseline = hub_service.admin_hub(db, creator).pipeline

    _seed_work_order(db, created_by=creator, status=wo.STATUS_ON_HOLD)
    archived = _seed_work_order(db, created_by=creator, status=wo.STATUS_IN_PROGRESS)
    archived.archived_at = datetime.now(timezone.utc)
    db.flush()

    pipeline = hub_service.admin_hub(db, creator).pipeline

    # Six columns, not seven (Global Constraints) -- on_hold has nowhere to
    # land, and the archived row is excluded everywhere.
    assert pipeline.created == baseline.created
    assert pipeline.assigned == baseline.assigned
    assert pipeline.in_progress == baseline.in_progress
    assert pipeline.ready_to_complete == baseline.ready_to_complete
    assert pipeline.completed == baseline.completed
    assert pipeline.review == baseline.review


def _seed_user_request(db, *, request_type, status="open", created_by):
    from app.models import UserRequest

    request = UserRequest(
        id=uuid.uuid4(),
        request_type=request_type,
        status=status,
        message="test",
        created_by_id=created_by.id,
    )
    db.add(request)
    db.flush()
    return request


def test_admin_hub_exceptions_count_each_open_request_type(db):
    from app.services import user_requests as user_requests_service

    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    baseline = hub_service.admin_hub(db, creator, now=NOW).exceptions

    _seed_user_request(
        db, request_type=user_requests_service.REQUEST_INVENTORY_RECOUNT, created_by=creator
    )
    _seed_user_request(
        db, request_type=user_requests_service.REQUEST_MISSING_ITEM_PRICE, created_by=creator
    )
    _seed_user_request(
        db, request_type=user_requests_service.REQUEST_ITEM, created_by=creator
    )
    # A resolved request must not count -- exceptions are open work only.
    _seed_user_request(
        db,
        request_type=user_requests_service.REQUEST_ITEM,
        status=user_requests_service.STATUS_RESOLVED,
        created_by=creator,
    )

    exceptions = hub_service.admin_hub(db, creator, now=NOW).exceptions

    assert exceptions.inventory_recounts - baseline.inventory_recounts == 1
    assert exceptions.missing_item_price - baseline.missing_item_price == 1
    assert exceptions.item_requests - baseline.item_requests == 1


def test_admin_hub_exceptions_admin_review_queue_matches_pipeline_review(db):
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    _seed_work_order(db, created_by=creator, status=wo.STATUS_REVIEW)

    payload = hub_service.admin_hub(db, creator, now=NOW)

    assert payload.exceptions.admin_review_queue == payload.pipeline.review


def test_admin_hub_exceptions_counts_a_stale_in_progress_work_order(db):
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    baseline = hub_service.admin_hub(db, creator, now=NOW).exceptions

    stale = _seed_work_order(
        db, created_by=creator, assigned_to=tech, status=wo.STATUS_IN_PROGRESS
    )
    _seed_session(
        db,
        stale,
        tech,
        started_at=NOW - timedelta(days=4, minutes=30),
        ended_at=NOW - timedelta(days=4),
    )
    fresh = _seed_work_order(
        db, created_by=creator, assigned_to=tech, status=wo.STATUS_IN_PROGRESS
    )
    _seed_session(
        db, fresh, tech, started_at=NOW - timedelta(minutes=30), ended_at=NOW - timedelta(minutes=10)
    )

    exceptions = hub_service.admin_hub(db, creator, now=NOW).exceptions

    assert exceptions.stale_work_orders - baseline.stale_work_orders == 1


def test_admin_hub_billing_sums_materials_and_labor_completed_this_week(db):
    # NOW (2026-08-20, a Thursday) falls in the Central week Aug 17-23.
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    baseline = hub_service.admin_hub(db, creator, now=NOW).billing

    item = _seed_item(db, price="10.00")
    work_order = _seed_work_order(
        db, created_by=creator, assigned_to=tech, status=wo.STATUS_COMPLETED
    )
    work_order.completed_at = NOW
    _seed_work_order_item(db, work_order, item, quantity=2)
    _seed_labor_entry(db, work_order, tech, minutes=90)
    db.flush()

    billing = hub_service.admin_hub(db, creator, now=NOW).billing

    # 2 units * $10.00 * 1.15 markup = $23.00.
    assert billing.materials_total - baseline.materials_total == Decimal("23.00")
    # 90 minutes already lands on a 30-min increment; $62.50/hr * 1.5h.
    assert billing.labor_total - baseline.labor_total == Decimal("93.75")
    assert billing.total - baseline.total == Decimal("116.75")


def test_admin_hub_billing_excludes_work_completed_outside_this_week(db):
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    baseline = hub_service.admin_hub(db, creator, now=NOW).billing

    item = _seed_item(db, price="10.00")
    work_order = _seed_work_order(
        db, created_by=creator, assigned_to=tech, status=wo.STATUS_COMPLETED
    )
    work_order.completed_at = NOW - timedelta(days=8)
    _seed_work_order_item(db, work_order, item, quantity=2)
    db.flush()

    billing = hub_service.admin_hub(db, creator, now=NOW).billing

    assert billing.materials_total == baseline.materials_total


def test_admin_hub_billing_sparkline_has_fourteen_points_and_counts_completions(db):
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    baseline = hub_service.admin_hub(db, creator, now=NOW).billing

    work_order = _seed_work_order(
        db, created_by=creator, assigned_to=tech, status=wo.STATUS_COMPLETED
    )
    work_order.completed_at = NOW
    db.flush()

    billing = hub_service.admin_hub(db, creator, now=NOW).billing

    assert len(billing.completed_per_day) == 14
    assert sum(billing.completed_per_day) - sum(baseline.completed_per_day) == 1
    assert billing.avg_days_to_complete is not None


def test_admin_hub_billing_legacy_count_is_owner_only(db):
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    owner = _seed_user(db, roles.ROLE_OWNER, first_name="Sam", last_name="Boyd")

    assert hub_service.admin_hub(db, creator, now=NOW).billing.legacy_live_count is None
    assert hub_service.admin_hub(db, owner, now=NOW).billing.legacy_live_count is not None


def test_admin_hub_on_the_clock_lists_a_running_session_company_wide(db):
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN, first_name="Marisol", last_name="Chen")
    work_order = _seed_work_order(
        db, created_by=creator, assigned_to=tech, status=wo.STATUS_IN_PROGRESS
    )
    work_order.community = "Commons B3"
    db.flush()
    started = NOW - timedelta(minutes=30)
    _seed_session(db, work_order, tech, started_at=started)

    payload = hub_service.admin_hub(db, creator, now=NOW)

    entry = next(e for e in payload.on_the_clock if e.work_order_number == work_order.number)
    assert entry.technician_name == "Marisol Chen"
    assert entry.community == "Commons B3"
    assert entry.elapsed_minutes == 30
    assert entry.flag is None


def test_admin_hub_on_the_clock_flags_a_long_running_session(db):
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN, first_name="Dana", last_name="Ortiz")
    work_order = _seed_work_order(
        db, created_by=creator, assigned_to=tech, status=wo.STATUS_IN_PROGRESS
    )
    started = NOW - timedelta(minutes=hub_domain.LONG_SESSION_WARN_MINUTES)
    _seed_session(db, work_order, tech, started_at=started)

    payload = hub_service.admin_hub(db, creator, now=NOW)

    entry = next(e for e in payload.on_the_clock if e.work_order_number == work_order.number)
    assert entry.flag == hub_domain.FLAG_LONG_SESSION


def test_admin_hub_on_the_clock_excludes_closed_sessions(db):
    creator = _seed_user(db, roles.ROLE_SUPERVISOR)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _seed_work_order(
        db, created_by=creator, assigned_to=tech, status=wo.STATUS_COMPLETED
    )
    _seed_session(
        db, work_order, tech, started_at=NOW - timedelta(hours=1), ended_at=NOW
    )

    payload = hub_service.admin_hub(db, creator, now=NOW)

    assert all(e.work_order_number != work_order.number for e in payload.on_the_clock)


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
    assert "pipeline" in body
    assert "in_progress" in body["pipeline"]
    assert "on_the_clock" in body
    entry = next(
        e for e in body["on_the_clock"] if e["work_order_number"] == work_order.number
    )
    assert entry["technician_name"] == "Jose Rivera"
    assert "exceptions" in body
    assert "stale_work_orders" in body["exceptions"]
    assert "billing" in body
    assert "total" in body["billing"]
    assert body["billing"]["legacy_live_count"] is None


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


def test_timesheets_hub_widens_to_everyone_for_a_techfm_oa_caller(db):
    oa = _seed_user(db, roles.ROLE_TECHFM_OA, first_name="Pat", last_name="Nguyen")
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR, first_name="Sam", last_name="Boss")
    stranger_tech = _seed_user(db, first_name="Not", last_name="Routed")
    # No work order routes stranger_tech to the OA caller at all -- P3b's
    # scope would have excluded them; P4 includes every live technician.
    _seed_work_order(db, created_by=supervisor, assigned_to=stranger_tech)

    payload = hub_service.timesheets_hub(
        db, oa, start=date(2026, 8, 17), end=date(2026, 8, 17), now=NOW
    )

    row_ids = {row.user.id for row in payload.rows}
    assert stranger_tech.id in row_ids
    assert supervisor.id in row_ids
    # The caller's own account (techfm_oa) is excluded, same as admin_hub's
    # two time buckets exclude it -- their own time is the clock widget.
    assert oa.id not in row_ids


def test_timesheets_hub_a_supervisor_caller_still_sees_only_their_own_crew(db):
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR, first_name="Sam", last_name="Boss")
    stranger_tech = _seed_user(db, first_name="Not", last_name="Mine")
    other_supervisor = _seed_user(
        db, roles.ROLE_SUPERVISOR, first_name="Other", last_name="Boss"
    )
    _seed_work_order(db, created_by=other_supervisor, assigned_to=stranger_tech)

    payload = hub_service.timesheets_hub(
        db, supervisor, start=date(2026, 8, 17), end=date(2026, 8, 17), now=NOW
    )

    assert payload.rows == []


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
