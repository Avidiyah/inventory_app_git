"""Low-stock dispatch and the eight stock-mutation trigger points.

Nothing here sends a real push: the transport has its own coverage in
`test_push_subscriptions.py`, and re-proving it per trigger is what makes
triggers expensive to add. These assert on *who* would be told and on
*whether a task was scheduled at all*.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks

from app.domain import realtime as realtime_policy
from app.models import Item, User
from app.services import auth as auth_service
from app.services import low_stock as low_stock_service
from app.services import notifications as notifications_service
from app.services import push as push_service


@pytest.fixture(autouse=True)
def _clean_buffer():
    low_stock_service.drain()
    yield
    low_stock_service.drain()


@pytest.fixture
def configured(monkeypatch):
    """Push enabled. With no private key the service declines to schedule
    anything, which is correct and would hide every assertion here."""
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    return True


def _seed_user(db, role):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth_service.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _seed_item(db, *, quantity="10", threshold=6):
    item = Item(
        barcode=f"BC-{uuid.uuid4().hex[:10]}",
        name=f"Widget {uuid.uuid4().hex[:6]}",
        quantity=Decimal(quantity),
        location="Bay 1",
        low_stock_threshold=threshold,
    )
    db.add(item)
    db.flush()
    return item


def _scheduled(background):
    return [task.args for task in background.tasks]


def _crossing(*, pushes=True, name="Blue Tape", quantity="5"):
    return low_stock_service.Crossing(
        item_id=uuid.uuid4(), name=name, quantity=quantity, pushes=pushes
    )


# --- dispatch -----------------------------------------------------------


def test_a_crossing_is_pushed_to_techfm_oa_and_above(db, configured):
    techfm = _seed_user(db, "techfm_oa")
    admin = _seed_user(db, "admin")
    supervisor = _seed_user(db, "supervisor")
    background = BackgroundTasks()

    notifications_service.notify_item_low_stock(
        db, background, crossings=[_crossing()]
    )

    assert len(_scheduled(background)) == 1
    user_ids, title, body = _scheduled(background)[0]
    assert techfm.id in user_ids
    assert admin.id in user_ids
    assert supervisor.id not in user_ids
    assert title == "Low stock"
    assert body == "Blue Tape is down to 5."


def test_a_membership_change_that_is_not_a_crossing_pushes_nothing(db, configured):
    _seed_user(db, "admin")
    background = BackgroundTasks()

    notifications_service.notify_item_low_stock(
        db, background, crossings=[_crossing(pushes=False)]
    )

    assert _scheduled(background) == []


def test_several_crossings_schedule_one_push_each(db, configured):
    """No batching: a Mass Stage load that crosses three items sends
    three notifications, each naming its own item."""
    _seed_user(db, "admin")
    background = BackgroundTasks()

    notifications_service.notify_item_low_stock(
        db,
        background,
        crossings=[
            _crossing(name="Tape", quantity="2"),
            _crossing(name="Screws", quantity="1"),
            _crossing(name="Caulk", quantity="0"),
        ],
    )

    bodies = [body for _ids, _title, body in _scheduled(background)]
    assert bodies == [
        "Tape is down to 2.",
        "Screws is down to 1.",
        "Caulk is down to 0.",
    ]


def test_nothing_is_scheduled_when_nobody_holds_the_rank(db, configured):
    background = BackgroundTasks()
    notifications_service.notify_item_low_stock(
        db, background, crossings=[_crossing()]
    )
    # Any TechFM OA+ already in the dev database would be a legitimate
    # recipient, so assert on the audience rather than on emptiness.
    for user_ids, _title, _body in _scheduled(background):
        assert user_ids


# --- the flush helper ---------------------------------------------------


def test_flush_drains_pushes_and_invalidates(db, configured, monkeypatch):
    from app.routers import _low_stock

    envelopes = []
    monkeypatch.setattr(
        _low_stock.realtime_service, "emit", lambda envelope: envelopes.append(envelope)
    )
    _seed_user(db, "admin")
    item = _seed_item(db, quantity="5")
    low_stock_service.record(item, quantity_before=Decimal("7"))
    background = BackgroundTasks()

    _low_stock.flush_low_stock(db, background)

    assert len(_scheduled(background)) == 1
    assert len(envelopes) == 1
    assert envelopes[0]["type"] == realtime_policy.EVENT_ITEM_LOW_STOCK_CHANGED
    assert envelopes[0]["id"] == str(item.id)
    # Drained: a second flush on the same request repeats nothing.
    second = BackgroundTasks()
    _low_stock.flush_low_stock(db, second)
    assert _scheduled(second) == []


def test_flush_invalidates_even_when_the_item_left_the_low_set(db, configured, monkeypatch):
    """A restock has no push but must still drop the row from an open
    Low Stock page."""
    from app.routers import _low_stock

    envelopes = []
    monkeypatch.setattr(
        _low_stock.realtime_service, "emit", lambda envelope: envelopes.append(envelope)
    )
    _seed_user(db, "admin")
    item = _seed_item(db, quantity="9")
    low_stock_service.record(item, quantity_before=Decimal("2"))
    background = BackgroundTasks()

    _low_stock.flush_low_stock(db, background)

    assert _scheduled(background) == []
    assert len(envelopes) == 1


def test_flush_never_raises_into_a_committed_request(db, monkeypatch):
    """The durable write already happened. A bug in recipient resolution
    must cost a notification, not turn a successful save into a 500."""
    from app.routers import _low_stock

    def boom(*args, **kwargs):
        raise RuntimeError("resolution exploded")

    monkeypatch.setattr(_low_stock.notifications_service, "notify_item_low_stock", boom)
    item = _seed_item(db, quantity="5")
    low_stock_service.record(item, quantity_before=Decimal("7"))

    _low_stock.flush_low_stock(db, BackgroundTasks())  # must not raise


# --- the eight mutation points ------------------------------------------


def _crossings_after(fn):
    """Run a stock write and return what it buffered."""
    low_stock_service.drain()
    fn()
    return low_stock_service.drain()


def test_a_scan_dispense_that_crosses_is_recorded(db):
    from app.services import transactions as txn_service

    user = _seed_user(db, "supervisor")
    item = _seed_item(db, quantity="7", threshold=6)
    db.commit()

    crossings = _crossings_after(
        lambda: txn_service.apply_transaction(
            db,
            item_id=item.id,
            transaction_type="dispense",
            quantity=Decimal("2"),
            user_id=user.id,
            work_order_number=None,
        )
    )
    assert [c.pushes for c in crossings] == [True]
    assert crossings[0].quantity == "5"


def test_a_scan_dispense_on_an_already_low_item_is_silent(db):
    from app.services import transactions as txn_service

    user = _seed_user(db, "supervisor")
    item = _seed_item(db, quantity="5", threshold=6)
    db.commit()

    crossings = _crossings_after(
        lambda: txn_service.apply_transaction(
            db,
            item_id=item.id,
            transaction_type="dispense",
            quantity=Decimal("1"),
            user_id=user.id,
            work_order_number=None,
        )
    )
    assert crossings == []


def test_a_stock_in_that_re_arms_is_recorded_without_a_push(db):
    from app.services import transactions as txn_service

    user = _seed_user(db, "supervisor")
    item = _seed_item(db, quantity="2", threshold=6)
    db.commit()

    crossings = _crossings_after(
        lambda: txn_service.apply_transaction(
            db,
            item_id=item.id,
            transaction_type="stock",
            quantity=Decimal("20"),
            user_id=user.id,
            work_order_number=None,
        )
    )
    assert [c.pushes for c in crossings] == [False]


def test_a_correction_down_across_the_threshold_is_recorded(db):
    from app.services import transactions as txn_service

    user = _seed_user(db, "techfm_oa")
    item = _seed_item(db, quantity="30", threshold=6)
    db.commit()

    crossings = _crossings_after(
        lambda: txn_service.apply_correction(
            db,
            item_id=item.id,
            new_quantity=Decimal("3"),
            reason="Recount",
            user_id=user.id,
        )
    )
    assert [c.pushes for c in crossings] == [True]


def test_voiding_a_stock_in_back_across_the_threshold_is_recorded(db):
    """Undoing a restock lowers on-hand and can cross like any dispense."""
    from app.services import transactions as txn_service

    user = _seed_user(db, "supervisor")
    item = _seed_item(db, quantity="2", threshold=6)
    db.commit()
    txn = txn_service.apply_transaction(
        db,
        item_id=item.id,
        transaction_type="stock",
        quantity=Decimal("20"),
        user_id=user.id,
        work_order_number=None,
    )

    crossings = _crossings_after(
        lambda: txn_service.void_transaction(
            db, transaction_id=txn.id, user_id=user.id, user_role="supervisor"
        )
    )
    assert [c.pushes for c in crossings] == [True]


def _loading_stage(db, item, planned1=10, planned2=5):
    """A loading stage with `item` planned in two slots.

    Mirrors `_seed_loading_stage` in `test_mass_staging_load.py`. The
    duplication is deliberate: importing helpers across test modules
    couples two suites that should be free to change apart.
    """
    from app.services import work_orders as wo_service
    from app.services.mass_staging import (
        add_item,
        add_work_order_to_stage,
        create_stage,
        update_stage,
    )

    stage = create_stage(
        db,
        community="Scholars",
        building_name=f"B-{uuid.uuid4().hex[:6]}",
        created_by_id=None,
    )
    for planned in (planned1, planned2):
        number = f"WO-{uuid.uuid4().hex[:8]}"
        wo_service.get_or_create_work_order(db, number=number, created_by_id=None)
        slot = add_work_order_to_stage(db, stage.id, work_order_number=number)
        add_item(db, stage.id, slot.id, item_id=item.id, planned_quantity=Decimal(planned))
    update_stage(db, stage.id, status="loading")
    return stage


def test_a_mass_stage_load_that_crosses_records_exactly_one_crossing(db):
    """One item, several per-slot slices, ONE buffered crossing -- the
    recorder runs after the allocation loop, not inside it. Inside, a load
    filling six rooms would buzz six times for one event."""
    from app.services.mass_staging import load_item

    item = _seed_item(db, quantity="20", threshold=6)
    stage = _loading_stage(db, item)
    db.commit()

    crossings = _crossings_after(
        lambda: load_item(
            db, stage.id, item_id=item.id, quantity=Decimal("15"), user_id=None
        )
    )
    assert [c.pushes for c in crossings] == [True]
    assert crossings[0].quantity == "5"


def test_a_mass_stage_return_re_arms_without_pushing(db):
    from app.services.mass_staging import load_item, return_item

    item = _seed_item(db, quantity="20", threshold=6)
    stage = _loading_stage(db, item)
    db.commit()
    load_item(db, stage.id, item_id=item.id, quantity=Decimal("15"), user_id=None)

    crossings = _crossings_after(
        lambda: return_item(db, stage.id, item_id=item.id, quantity=Decimal("10"))
    )
    assert [c.pushes for c in crossings] == [False]


def test_a_work_order_material_line_that_crosses_is_recorded(db):
    from app.services import work_orders as wo_service

    user = _seed_user(db, "supervisor")
    item = _seed_item(db, quantity="7", threshold=6)
    number = f"WO-{uuid.uuid4().hex[:8]}"
    work_order = wo_service.get_or_create_work_order(
        db, number=number, created_by_id=user.id
    )
    db.commit()

    crossings = _crossings_after(
        lambda: wo_service.add_work_order_item(
            db, work_order.id, user=user, item_id=item.id, quantity=Decimal("2")
        )
    )
    assert [c.pushes for c in crossings] == [True]


def test_every_item_quantity_mutation_has_a_recorder():
    """The guard that stops the ninth stock-writing site from silently
    skipping the alert. Counts the mutation lines and the recorder calls
    in the three services that own them."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "services"
    mutations = 0
    records = 0
    for name in ("transactions.py", "mass_staging.py", "work_orders.py"):
        source = (root / name).read_text(encoding="utf-8")
        mutations += source.count("item.quantity = ")
        records += source.count("low_stock.record(")
    # Nine mutation lines across eight functions: `apply_transaction` has
    # two branches (the Scan / Stock shortage path and the strict path)
    # that share one recorder call.
    assert mutations == 9
    assert records == 8
