"""Takeoff service rules: lines, purchases, count-downs and the overview."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.domain import roles
from app.domain import work_orders as wo
from app.domain.errors import (
    RoleManagementError,
    TakeoffLineConflictError,
    WorkOrderStateError,
)
from app.models import Item, TakeoffPurchase, User, WorkOrder, WorkOrderTakeoffLine
from app.services import auth
from app.services import takeoff as tk
from app.services import work_orders as wos

D = Decimal


def _user(db, role=roles.ROLE_OWNER):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _item(db, name="Toilet", qty=0, price="10"):
    item = Item(
        barcode=f"BC-{uuid.uuid4().hex[:10]}",
        name=name,
        quantity=D(qty),
        location="Bay 1",
        price=None if price is None else D(price),
    )
    db.add(item)
    db.flush()
    return item


def _order(db, user, service_type=None):
    order = wos.get_or_create_work_order(
        db,
        number=f"WO-{uuid.uuid4().hex[:8]}",
        service_type=service_type,
        created_by_id=user.id,
    )
    db.flush()
    return order


def _lines(db, order):
    return db.query(WorkOrderTakeoffLine).filter_by(work_order_id=order.id).all()


def _purchases(db, item):
    return db.query(TakeoffPurchase).filter_by(item_id=item.id).all()


def _rows(overview):
    return {(g.service_type_label, r.item_name): r for g in overview.groups for r in g.rows}


def test_add_line_aggregates_same_item(db):
    user, item = _user(db), _item(db)
    order = _order(db, user)
    tk.add_line(db, order.id, user=user, item_id=item.id, quantity=D(4))
    tk.add_line(db, order.id, user=user, item_id=item.id, quantity=D(3))
    lines = _lines(db, order)
    assert len(lines) == 1 and lines[0].quantity == D(7)


def test_update_and_delete_line(db):
    user, item = _user(db), _item(db)
    order = _order(db, user)
    line = tk.add_line(db, order.id, user=user, item_id=item.id, quantity=D(4))
    assert tk.update_line(db, order.id, line.id, user=user, quantity=D(9)).quantity == D(9)
    tk.delete_line(db, order.id, line.id, user=user)
    assert _lines(db, order) == []
    with pytest.raises(TakeoffLineConflictError):
        tk.delete_line(db, order.id, line.id, user=user)


def test_completed_order_takeoff_is_read_only(db):
    user, item = _user(db), _item(db)
    order = _order(db, user)
    line = tk.add_line(db, order.id, user=user, item_id=item.id, quantity=D(4))
    order.status = wo.STATUS_COMPLETED
    db.flush()
    with pytest.raises(WorkOrderStateError):
        tk.add_line(db, order.id, user=user, item_id=item.id, quantity=D(1))
    with pytest.raises(WorkOrderStateError):
        tk.update_line(db, order.id, line.id, user=user, quantity=D(1))
    with pytest.raises(WorkOrderStateError):
        tk.delete_line(db, order.id, line.id, user=user)


def test_consume_line_counts_down_and_deletes_at_zero(db):
    user, item = _user(db), _item(db)
    order = _order(db, user)
    line = tk.add_line(db, order.id, user=user, item_id=item.id, quantity=D(4))
    tk.consume_line(db, line_id=line.id, work_order_id=order.id, item_id=item.id, quantity=D(3))
    assert _lines(db, order)[0].quantity == D(1)
    tk.consume_line(db, line_id=line.id, work_order_id=order.id, item_id=item.id, quantity=D(2))
    assert _lines(db, order) == []


def test_consume_line_wrong_order_raises(db):
    user, item, other = _user(db), _item(db), _item(db, name="Valve")
    order, order2 = _order(db, user), _order(db, user)
    line = tk.add_line(db, order.id, user=user, item_id=item.id, quantity=D(4))
    with pytest.raises(TakeoffLineConflictError, match="This takeoff line changed"):
        tk.consume_line(db, line_id=line.id, work_order_id=order2.id, item_id=item.id, quantity=D(1))
    with pytest.raises(TakeoffLineConflictError):
        tk.consume_line(db, line_id=line.id, work_order_id=order.id, item_id=other.id, quantity=D(1))
    with pytest.raises(TakeoffLineConflictError):
        tk.consume_line(db, line_id=uuid.uuid4(), work_order_id=order.id, item_id=item.id, quantity=D(1))
    assert _lines(db, order)[0].quantity == D(4)


def test_overview_need_excludes_completed_and_archived(db):
    user, item = _user(db), _item(db)
    live, done, archived = (_order(db, user, "WMR") for _ in range(3))
    for order in (live, done, archived):
        tk.add_line(db, order.id, user=user, item_id=item.id, quantity=D(5))
    done.status = wo.STATUS_COMPLETED
    archived.archived_at = datetime.now(timezone.utc)
    db.flush()
    row = _rows(tk.overview(db))[("WMR", "Toilet")]
    assert row.need == D(5)
    assert [r.number for r in row.work_orders] == [live.number]


def test_overview_shortfall_pools_across_service_types(db):
    user, item = _user(db), _item(db, qty=12, price="120")
    wmr, plumbing = _order(db, user, "WMR"), _order(db, user, "Plumbing")
    tk.add_line(db, wmr.id, user=user, item_id=item.id, quantity=D(110))
    tk.add_line(db, plumbing.id, user=user, item_id=item.id, quantity=D(8))
    tk.set_purchase(
        db, user=user, item_id=item.id, service_type_key="wmr",
        service_type_label="WMR", quantity=D(100),
    )
    rows = _rows(tk.overview(db))
    assert rows[("WMR", "Toilet")].shortfall == D(6)
    assert rows[("Plumbing", "Toilet")].shortfall == D(6)
    assert rows[("WMR", "Toilet")].shared and rows[("Plumbing", "Toilet")].shared
    assert rows[("WMR", "Toilet")].on_the_way == D(100)
    assert rows[("Plumbing", "Toilet")].on_the_way == D(0)
    assert rows[("WMR", "Toilet")].total == D(13200)


def test_overview_merges_case_variant_service_types(db):
    user, item = _user(db), _item(db, qty=0)
    upper, lower = _order(db, user, "WMR"), _order(db, user, "wmr")
    tk.add_line(db, upper.id, user=user, item_id=item.id, quantity=D(3))
    tk.add_line(db, lower.id, user=user, item_id=item.id, quantity=D(5))
    tk.set_purchase(
        db, user=user, item_id=item.id, service_type_key="wmr",
        service_type_label="wmr", quantity=D(4),
    )
    groups = tk.overview(db).groups
    assert [(g.service_type_key, g.service_type_label) for g in groups] == [("wmr", "WMR")]
    row = groups[0].rows[0]
    assert row.need == D(8) and row.on_the_way == D(4)
    assert row.shared is False and row.shortfall == D(4)


def test_overview_covered_by_stock(db):
    user, item = _user(db), _item(db, name="Supply line", qty=60, price="8")
    order = _order(db, user, "WMR")
    tk.add_line(db, order.id, user=user, item_id=item.id, quantity=D(40))
    row = _rows(tk.overview(db))[("WMR", "Supply line")]
    assert row.shortfall == D(0) and row.on_the_way == D(0) and row.shared is False
    assert row.stock == D(60)


def test_service_type_change_moves_need(db):
    user, item = _user(db), _item(db)
    order = _order(db, user, "WMR")
    tk.add_line(db, order.id, user=user, item_id=item.id, quantity=D(5))
    tk.set_purchase(
        db, user=user, item_id=item.id, service_type_key="wmr",
        service_type_label="WMR", quantity=D(2),
    )
    order.service_type = "Plumbing"
    db.flush()
    overview = tk.overview(db)
    assert [g.service_type_label for g in overview.groups] == ["Plumbing", "WMR"]
    assert overview.groups[0].rows[0].need == D(5)
    assert overview.groups[0].rows[0].on_the_way == D(0)
    assert overview.groups[0].rows[0].shortfall == D(3)  # purchase pools by item
    assert overview.groups[1].rows[0].need == D(0)  # purchase stays on its old key
    assert _purchases(db, item)[0].service_type_key == "wmr"


def test_null_price_row_total_none_and_group_skips_it(db):
    user = _user(db)
    priced, unpriced = _item(db, name="Priced", price="3"), _item(db, name="Unpriced", price=None)
    order = _order(db, user, "WMR")
    tk.add_line(db, order.id, user=user, item_id=priced.id, quantity=D(2))
    tk.add_line(db, order.id, user=user, item_id=unpriced.id, quantity=D(9))
    group = tk.overview(db).groups[0]
    rows = {r.item_name: r for r in group.rows}
    assert rows["Unpriced"].total is None and rows["Unpriced"].price is None
    assert rows["Priced"].total == D(6)
    assert group.total == D(6)


def test_decimal_quantities_exact(db):
    user, item = _user(db), _item(db)
    order = _order(db, user)
    line = tk.add_line(db, order.id, user=user, item_id=item.id, quantity=D("2.5"))
    tk.consume_line(db, line_id=line.id, work_order_id=order.id, item_id=item.id, quantity=D("1.25"))
    assert _lines(db, order)[0].quantity == D("1.25")
    tk.set_purchase(
        db, user=user, item_id=item.id, service_type_key="wmr",
        service_type_label="WMR", quantity=D("2.5"),
    )
    tk.count_down_purchases(db, item_id=item.id, quantity=D("1.25"))
    assert _purchases(db, item)[0].quantity_on_the_way == D("1.25")


def test_count_down_oldest_first_and_surplus_ignored(db):
    user, item = _user(db), _item(db)
    tk.set_purchase(
        db, user=user, item_id=item.id, service_type_key="plumbing",
        service_type_label="Plumbing", quantity=D(10),
    )
    tk.set_purchase(
        db, user=user, item_id=item.id, service_type_key="wmr",
        service_type_label="WMR", quantity=D(100),
    )
    old = db.query(TakeoffPurchase).filter_by(service_type_key="plumbing").one()
    old.created_at = datetime.now(timezone.utc) - timedelta(days=2)
    db.flush()
    tk.count_down_purchases(db, item_id=item.id, quantity=D(50))
    left = _purchases(db, item)
    assert [(p.service_type_key, p.quantity_on_the_way) for p in left] == [("wmr", D(60))]
    tk.count_down_purchases(db, item_id=item.id, quantity=D(500))
    assert _purchases(db, item) == []


def test_set_purchase_adds_updates_and_clears(db):
    user, item = _user(db), _item(db)
    args = dict(user=user, item_id=item.id, service_type_key="wmr", service_type_label="WMR")
    tk.set_purchase(db, quantity=D(100), **args)
    row = _purchases(db, item)[0]
    assert row.quantity_on_the_way == D(100)
    created = row.created_at
    tk.set_purchase(db, quantity=D(40), **args)
    row = _purchases(db, item)[0]
    assert row.quantity_on_the_way == D(40) and row.created_at == created
    tk.set_purchase(db, quantity=D(0), **args)
    assert _purchases(db, item) == []
    tk.set_purchase(db, quantity=D(0), **args)  # clearing nothing is fine


def test_blank_service_type_groups_as_unspecified(db):
    user, item = _user(db), _item(db)
    for blank in (None, "   "):
        tk.add_line(db, _order(db, user, blank).id, user=user, item_id=item.id, quantity=D(1))
    overview = tk.overview(db)
    assert [(g.service_type_key, g.service_type_label) for g in overview.groups] == [
        ("__unspecified__", "Unspecified")
    ]
    assert overview.groups[0].rows[0].need == D(2)


def test_groups_sorted_by_label_and_rows_by_name(db):
    user = _user(db)
    for label, name in (("wmr", "b"), ("Plumbing", "z"), ("Plumbing", "A")):
        tk.add_line(
            db, _order(db, user, label).id, user=user,
            item_id=_item(db, name=name).id, quantity=D(1),
        )
    groups = tk.overview(db).groups
    assert [g.service_type_label for g in groups] == ["Plumbing", "wmr"]
    assert [r.item_name for r in groups[0].rows] == ["A", "z"]


def _way(db, user, item, key, label, qty):
    tk.set_purchase(
        db, user=user, item_id=item.id, service_type_key=key,
        service_type_label=label, quantity=D(qty),
    )


def test_purchase_without_need_still_listed(db):
    user, item = _user(db), _item(db, qty=0, price="10")
    order = _order(db, user, "WMR")
    tk.add_line(db, order.id, user=user, item_id=item.id, quantity=D(5))
    _way(db, user, item, "wmr", "WMR", 2)
    order.service_type = "Plumbing"
    db.flush()
    rows = _rows(tk.overview(db))
    old = rows[("WMR", "Toilet")]
    assert old.need == D(0) and old.on_the_way == D(2) and old.total == D(0)
    assert old.work_orders == [] and old.shared is True
    assert old.shortfall == D(3)
    assert rows[("Plumbing", "Toilet")].need == D(5)
    assert rows[("Plumbing", "Toilet")].on_the_way == D(0)


def test_purchase_listed_after_every_order_completed(db):
    user = _user(db)
    item, unpriced = _item(db, price="4"), _item(db, name="Unpriced", price=None)
    order = _order(db, user, "WMR")
    tk.add_line(db, order.id, user=user, item_id=item.id, quantity=D(5))
    _way(db, user, item, "wmr", "WMR", 5)
    _way(db, user, unpriced, "wmr", "WMR", 1)
    order.status = wo.STATUS_COMPLETED
    db.flush()
    group = tk.overview(db).groups[0]
    rows = {r.item_name: r for r in group.rows}
    assert group.service_type_label == "WMR"
    assert rows["Toilet"].need == D(0) and rows["Toilet"].on_the_way == D(5)
    assert rows["Toilet"].shortfall == D(0) and rows["Toilet"].shared is False
    assert rows["Unpriced"].total is None
    assert group.total == D(0)


def test_confirm_takeoff_marks_created_order_planned(db):
    owner = _user(db)
    lead = _user(db, roles.ROLE_SUPERVISOR)
    order = _order(db, owner)
    planned = {"status": wo.STATUS_PLANNED}
    # No takeoff lines: a job that needs no material can still be Planned.
    with pytest.raises(RoleManagementError):
        wos.update_work_order(db, order.id, user=lead, fields=planned)
    assert wos.update_work_order(db, order.id, user=owner, fields=planned).status == wo.STATUS_PLANNED
    # A Team Lead may take it back to Created.
    back = wos.update_work_order(db, order.id, user=lead, fields={"status": wo.STATUS_CREATED})
    assert back.status == wo.STATUS_CREATED


def test_only_created_can_be_planned_and_crew_moves_it_to_assigned(db):
    owner, item = _user(db), _item(db)
    tech = _user(db, roles.ROLE_TECHNICIAN)
    order = _order(db, owner)
    tk.add_line(db, order.id, user=owner, item_id=item.id, quantity=D(2))
    wos.update_work_order(db, order.id, user=owner, fields={"status": wo.STATUS_PLANNED})
    crewed = wos.update_work_order(db, order.id, user=owner, fields={"assigned_to_ids": [tech.id]})
    assert crewed.status == wo.STATUS_ASSIGNED
    with pytest.raises(WorkOrderStateError, match="Only a Created"):
        wos.update_work_order(db, order.id, user=owner, fields={"status": wo.STATUS_PLANNED})


def test_needs_assessment_keeps_its_flag_with_crew_then_plans(db):
    owner = _user(db)
    lead = _user(db, roles.ROLE_SUPERVISOR)
    tech = _user(db, roles.ROLE_TECHNICIAN)
    order = _order(db, owner)
    assess = {"status": wo.STATUS_NEEDS_ASSESSMENT}
    with pytest.raises(RoleManagementError):
        wos.update_work_order(db, order.id, user=lead, fields=assess)
    wos.update_work_order(db, order.id, user=owner, fields=assess)
    crewed = wos.update_work_order(db, order.id, user=owner, fields={"assigned_to_ids": [tech.id]})
    assert crewed.status == wo.STATUS_NEEDS_ASSESSMENT
    planned = wos.update_work_order(db, order.id, user=owner, fields={"status": wo.STATUS_PLANNED})
    # Planned never holds a crew, so a crewed order lands on Assigned.
    assert planned.status == wo.STATUS_ASSIGNED
    with pytest.raises(WorkOrderStateError, match="Only a Created"):
        wos.update_work_order(db, order.id, user=owner, fields=assess)
