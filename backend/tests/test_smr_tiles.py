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
from app.domain import work_orders_smr_lines as rules
from app.schemas.work_orders_smr_lines import SmrLineEditIn, SmrLineIn, SmrReadingIn
from app.services import work_orders_smr_lines as lines_service


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
    assert page.counts.orders >= 2
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


def test_smr_tiles_filter_by_community_priority_and_date(db):
    owner = _user(db)
    a, b, tag = _seed_filterable(db, owner)
    assert _numbers(smr_service.list_smr_tiles(db, search=tag, community="scholars")) == [b]
    assert _numbers(smr_service.list_smr_tiles(db, search=tag, priority="Emergency")) == [a]
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
    assert page.remaining.hours >= Decimal(2) and page.remaining.materials_total >= Decimal("67.16")


# --- paper check (spec 2026-10-27-smr-paper-check) --------------------------

def test_smr_tiles_carry_paper_check_and_counts(db):
    owner = _user(db)
    short_checked, matched_checked, short_open, none_checked = [f"SMR-{uuid.uuid4().hex[:8]}" for _ in range(4)]
    numbers = [short_checked, matched_checked, short_open, none_checked]
    smr_service.import_smr(db, csv_bytes=_sheet(numbers), user=owner)
    smr_service.import_smr_targets(
        db,
        csv_bytes=_breakdown([(short_checked, "2", "$0.00"), (matched_checked, "0", "$0.00"), (short_open, "2", "$0.00")]),
        user=owner,
    )
    before = smr_service.list_smr_tiles(db).counts
    for number in (short_checked, matched_checked, none_checked):
        smr_service.set_paper_check(db, work_order_id=wos.find_by_number(db, number).id, checked=True, user=owner)

    page = smr_service.list_smr_tiles(db)

    mine = {t.number: t for t in page.tiles if t.number in numbers}
    assert mine[short_open].paper_check is None
    assert mine[short_checked].paper_check.checked_by_name == owner.full_name
    assert mine[none_checked].paper_check is not None
    assert page.counts.orders == before.orders  # the check moves no count (spec 2026-11-06)


# --- paper-correction lines (spec 2026-11-04 D9) ----------------------------

def _line_in(**overrides):
    fields = dict(vendor="Belfor", hours_each=Decimal("2.0"), reason_code="accurate", work_date=date(2026, 6, 20), reason="paper")
    fields.update(overrides)
    return SmrLineIn(**fields)


def test_smr_tiles_carry_lines_and_the_counts_and_filters_follow(db):
    owner = _user(db)
    with_lines, without = [f"SMR-{uuid.uuid4().hex[:8]}" for _ in range(2)]
    smr_service.import_smr(db, csv_bytes=_sheet([with_lines, without]), user=owner)
    smr_service.import_smr_targets(db, csv_bytes=_breakdown([(with_lines, "1", "$0.00")]), user=owner)
    order = wos.find_by_number(db, with_lines)
    wos.add_work_order_labor(db, order.id, user=owner, technician_id=None, minutes=600)  # legacy: listed, never charged
    lines_service.add_line(db, work_order_id=order.id, payload=_line_in(), user=owner)
    lines_service.add_line(db, work_order_id=order.id,
                           payload=_line_in(work_date=None, hours_each=Decimal("1.0"), status="excluded", exclusion_ground="undated"),
                           user=owner)

    page = smr_service.list_smr_tiles(db)

    mine = {t.number: t for t in page.tiles if t.number in (with_lines, without)}
    assert mine[without].lines is None
    # No lines: nothing to place, so "Undated" and still untouched.
    assert (mine[without].weeks, mine[without].edited) == (["Undated"], False)
    tile = mine[with_lines]
    # 06/20 is week 4 from 05/25; the undated excluded line adds "Undated" last.
    # Paper lines alone make the order edited (no catalogue change here).
    assert (tile.weeks, tile.edited) == (["Week 4", "Undated"], True)
    assert (tile.lines.count, tile.lines.charged_hours, tile.lines.excluded_hours) == (2, Decimal("2.0"), Decimal("1.0"))
    assert tile.lines.change_hours == Decimal("1.0") and tile.lines.block_version is None and tile.lines.block_stale is False
    assert tile.after.labor_total == Decimal("125.00") and tile.after.skilled_minutes == 600
    assert tile.target.current_hours == Decimal("2.0") and tile.target.matched is True
    assert page.counts.blocks_not_pasted >= 1
    assert page.counts.charged_hours >= Decimal("2.0") and page.counts.excluded_hours >= Decimal("1.0")

    block = lines_service.generate_block(db, work_order_id=order.id, user=owner)
    only = _numbers(smr_service.list_smr_tiles(db, has_lines=True))
    assert with_lines in only and without not in only
    assert with_lines in _numbers(smr_service.list_smr_tiles(db, block_stale_or_unpasted=True))

    lines_service.mark_pasted(db, block_id=block.id, user=owner)
    pasted = next(t for t in smr_service.list_smr_tiles(db).tiles if t.number == with_lines)
    assert (pasted.lines.block_version, pasted.lines.block_stale) == (1, False) and pasted.lines.block_pasted_at is not None
    assert with_lines not in _numbers(smr_service.list_smr_tiles(db, block_stale_or_unpasted=True))


# --- paper stage (spec 2026-11-06-smr-paper-stage) ---------------------------

def _staged(db, owner, *, reading=True):
    number = f"SMR-{uuid.uuid4().hex[:8]}"
    smr_service.import_smr(db, csv_bytes=_sheet([number]), user=owner)
    order = wos.find_by_number(db, number)
    if reading:
        lines_service.add_reading(db, work_order_id=order.id, payload=SmrReadingIn(printing_no=1), user=owner)
    return order


def _tile(db, order):
    return next(t for t in smr_service.list_smr_tiles(db).tiles if t.number == order.number)


def test_stage_not_reviewed_without_readings(db):
    owner = _user(db)
    order = _staged(db, owner, reading=False)
    page = smr_service.list_smr_tiles(db)
    tile = next(t for t in page.tiles if t.number == order.number)
    assert tile.stage == "not_reviewed"
    assert tile.closed_week == "Before W1"  # the fixture closes 05/21
    assert tile.belfor_only is False and tile.ready is None
    assert page.counts.not_reviewed >= 1


def test_stage_undated_with_a_reading_and_no_dated_line(db):
    owner = _user(db)
    order = _staged(db, owner)
    assert _tile(db, order).stage == "undated"  # the reading alone
    lines_service.add_line(db, work_order_id=order.id,
                           payload=_line_in(work_date=None, status="excluded", exclusion_ground="undated"), user=owner)
    tile = _tile(db, order)
    assert tile.stage == "undated" and tile.closed_week == "Before W1"


def test_stage_dated_by_any_week_charged_or_excluded(db):
    owner = _user(db)
    order = _staged(db, owner)
    lines_service.add_line(db, work_order_id=order.id,
                           payload=_line_in(work_date=date(2026, 6, 2), status="excluded", exclusion_ground="note only"), user=owner)
    tile = _tile(db, order)
    assert tile.stage == "dated" and "Week 2" in tile.weeks and tile.closed_week is None

    placed = _staged(db, owner)
    lines_service.add_line(db, work_order_id=placed.id,
                           payload=_line_in(work_date=None, date_basis=rules.WEEK1_PLACEMENT_BASIS), user=owner)
    assert _tile(db, placed).stage == "dated"


def test_removed_lines_do_not_count(db):
    owner = _user(db)
    order = _staged(db, owner)
    line = lines_service.add_line(db, work_order_id=order.id, payload=_line_in(), user=owner)
    assert _tile(db, order).stage == "dated"
    lines_service.edit_line(db, line_id=line.id,
                            payload=SmrLineEditIn(status="excluded", exclusion_ground="removed", reason="x"), user=owner)
    tile = _tile(db, order)
    assert tile.stage == "undated" and tile.belfor_only is False


def test_belfor_only(db):
    owner = _user(db)
    order = _staged(db, owner)
    assert _tile(db, order).belfor_only is False  # no lines
    lines_service.add_line(db, work_order_id=order.id, payload=_line_in(), user=owner)
    lines_service.add_line(db, work_order_id=order.id, payload=_line_in(hours_each=Decimal("0.5")), user=owner)
    page = smr_service.list_smr_tiles(db)
    assert next(t for t in page.tiles if t.number == order.number).belfor_only is True
    assert page.counts.belfor_only >= 1
    lines_service.add_line(db, work_order_id=order.id,
                           payload=_line_in(vendor="Unknown", status="excluded", exclusion_ground="vendor unknown"), user=owner)
    assert _tile(db, order).belfor_only is False


def test_ready_stage_needs_a_dated_line(db):
    owner = _user(db)
    order = _staged(db, owner)
    line = lines_service.add_line(db, work_order_id=order.id, payload=_line_in(), user=owner)
    order.smr_ready_at = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
    order.smr_ready_by_id = owner.id
    db.commit()
    tile = _tile(db, order)
    assert tile.stage == "ready" and tile.ready.by_name == owner.full_name
    lines_service.edit_line(db, line_id=line.id,
                            payload=SmrLineEditIn(status="excluded", exclusion_ground="removed", reason="x"), user=owner)
    tile = _tile(db, order)
    assert tile.stage == "undated" and tile.ready is not None
