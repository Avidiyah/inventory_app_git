"""`GET /work-orders/smr` tiles (spec 2026-10-23 D7/D8): before / after /
delta per order computed from the frozen baseline, archived orders included,
edited ones first."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.domain import roles
from app.domain import work_orders as wo
from app.models import Item, User
from app.services import auth
from app.services import work_orders as wos
from app.services import work_orders_smr as smr_service


def _user(db, role=roles.ROLE_OWNER):
    user = User(username=f"u-{uuid.uuid4().hex[:8]}", password_hash=auth.hash_password("x"), role=role)
    db.add(user)
    db.flush()
    return user


def _sheet(numbers):
    head = "WORK ORDER,CREATOR,SERVICE TYPE,SCHEDULE DATE,COMPLETION DATE,ASSIGNED TO,FILED STATUS,LOCATION\r\n"
    rows = "".join(f"{n},c,SMR27 - Belfor,05/15/2026,05/21/2026,a,Closed,\"B:1,U 1,x\"\r\n" for n in numbers)
    return (head + rows).encode()


def test_smr_tiles_before_after_delta(db):
    owner = _user(db)
    numbers = [f"SMR-{uuid.uuid4().hex[:8]}" for _ in range(2)]
    smr_service.import_smr(db, csv_bytes=_sheet(numbers), user=owner)
    edited = wos.find_by_number(db, numbers[1])
    wos.add_work_order_labor(db, edited.id, user=owner, technician_id=None, minutes=45)

    page = smr_service.list_smr_tiles(db)

    mine = {t.number: t for t in page.tiles if t.number in numbers}
    assert mine[numbers[1]].edited is True and mine[numbers[0]].edited is False
    assert mine[numbers[1]].delta.skilled_minutes == 45
    assert mine[numbers[1]].delta.labor_total == wo.labor_charge(45)
    assert mine[numbers[1]].after.labor_total == wo.labor_charge(45)
    assert mine[numbers[1]].before.total == Decimal("0.00")
    assert mine[numbers[0]].delta.total == Decimal(0)
    assert page.tiles.index(mine[numbers[1]]) < page.tiles.index(mine[numbers[0]])
    assert page.counts.orders >= 2 and page.counts.edited >= 1
    assert page.delta.labor_total >= wo.labor_charge(45)
    assert page.imported_at is not None


def test_smr_tiles_include_archived(db):
    owner = _user(db)
    number = f"SMR-{uuid.uuid4().hex[:8]}"
    smr_service.import_smr(db, csv_bytes=_sheet([number]), user=owner)
    order = wos.find_by_number(db, number)
    wos.archive_work_order(db, order.id, user=owner)

    page = smr_service.list_smr_tiles(db)

    tile = next(t for t in page.tiles if t.number == number)
    assert tile.archived_at is not None
    assert page.counts.archived >= 1


# --- search and filters (same server rules as the Work Orders list) --------

def _sheet_rows(rows):
    head = "WORK ORDER,CREATOR,SERVICE TYPE,SCHEDULE DATE,COMPLETION DATE,ASSIGNED TO,FILED STATUS,LOCATION\r\n"
    body = "".join(
        f"{n},c,SMR27 - Belfor,{sched},05/21/2026,{assignee},Closed,\"{loc}\"\r\n"
        for n, sched, assignee, loc in rows
    )
    return (head + body).encode()


def _seed_filterable(db, owner):
    tag = uuid.uuid4().hex[:6]
    a, b = f"SMR-{tag}-A", f"SMR-{tag}-B"
    smr_service.import_smr(db, csv_bytes=_sheet_rows([
        (a, "05/15/2026", "Chris Coburn", "Young Hall:1st Floor,108A,drawer"),
        (b, "07/20/2026", "Hayden Hurst", "Scholars Inn Apartments:2nd Floor,9G,blinds"),
    ]), user=owner)
    first = wos.find_by_number(db, a)
    first.description = "Repair sticking drawer"
    first.priority = "Emergency"
    db.flush()
    return a, b, tag


def _numbers(page):
    return [t.number for t in page.tiles]


def test_smr_tiles_filter_by_number_task_and_location(db):
    owner = _user(db)
    a, b, tag = _seed_filterable(db, owner)
    assert _numbers(smr_service.list_smr_tiles(db, search=f"{tag}-A")) == [a]
    assert _numbers(smr_service.list_smr_tiles(db, task_search="sticking")) == [a]
    assert _numbers(smr_service.list_smr_tiles(db, search=tag, location_search="Scholars")) == [b]


def test_smr_tiles_filter_by_community_priority_status_and_date(db):
    owner = _user(db)
    a, b, tag = _seed_filterable(db, owner)
    assert _numbers(smr_service.list_smr_tiles(db, search=tag, community="scholars")) == [b]
    assert _numbers(smr_service.list_smr_tiles(db, search=tag, priority="Emergency")) == [a]
    assert sorted(_numbers(smr_service.list_smr_tiles(db, search=tag, status="created"))) == [a, b]
    assert _numbers(smr_service.list_smr_tiles(db, search=tag, scheduled_date=date(2026, 7, 20))) == [b]


def test_smr_tiles_sort_follows_schedule_date(db):
    owner = _user(db)
    a, b, tag = _seed_filterable(db, owner)
    assert _numbers(smr_service.list_smr_tiles(db, search=tag, descending=True)) == [b, a]
    assert _numbers(smr_service.list_smr_tiles(db, search=tag, descending=False)) == [a, b]


def test_smr_tiles_counts_are_whole_population_and_matched_is_filtered(db):
    owner = _user(db)
    a, b, tag = _seed_filterable(db, owner)
    page = smr_service.list_smr_tiles(db, search=f"{tag}-A")
    assert page.matched == 1
    assert page.counts.orders >= 2


def test_smr_tiles_filter_options_cover_smr_rows(db):
    owner = _user(db)
    a, b, tag = _seed_filterable(db, owner)
    sup = _user(db, roles.ROLE_SUPERVISOR)
    wos.find_by_number(db, b).supervisor_id = sup.id
    db.flush()
    options = smr_service.list_smr_tiles(db).filter_options
    assert "Emergency" in options.priorities
    assert sup.id in [s.id for s in options.supervisors]
    assert {c.value for c in options.communities} >= {"scholars", "young_hall"}


# --- target match (spec 2026-10-23-smr-target-match) ----------------------

def _breakdown(rows):
    head = "WO#,Unit#,Closed Date,Labor Type,BELFOR HRS,Add HRS,Duplicate HRS,Hours,Labor $,OT Hours,OT $,Total Material Cost,Total L&M,\r\n"
    body = "".join(f'{n},Young Hall 108,05/21/26,SL,,,,{h},$0.00,,$0.00,"{m}",$0.00,\r\n' for n, h, m in rows)
    return (head + body).encode()


def test_smr_tiles_carry_target_and_match_counts(db):
    owner = _user(db)
    short, matched, none = [f"SMR-{uuid.uuid4().hex[:8]}" for _ in range(3)]
    smr_service.import_smr(db, csv_bytes=_sheet([short, matched, none]), user=owner)
    smr_service.import_smr_targets(db, csv_bytes=_breakdown([(short, "2", "$67.16"), (matched, "0.5", "$0.00")]), user=owner)
    wos.add_work_order_labor(db, wos.find_by_number(db, matched).id, user=owner, technician_id=None, minutes=30)

    page = smr_service.list_smr_tiles(db)

    mine = {t.number: t for t in page.tiles if t.number in (short, matched, none)}
    assert mine[none].target is None
    assert mine[short].target.matched is False and mine[short].target.remaining_hours == Decimal(2)
    assert mine[short].target.remaining_materials_total == Decimal("67.16")
    assert mine[matched].target.matched is True and mine[matched].target.current_hours == Decimal("0.5")
    assert page.counts.matched >= 1 and page.counts.short >= 1 and page.counts.no_target >= 1
    assert page.remaining.hours >= Decimal(2) and page.remaining.materials_total >= Decimal("67.16")
