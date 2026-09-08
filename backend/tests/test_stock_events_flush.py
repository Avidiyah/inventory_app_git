"""One flush, two buffers.

The low-stock crossing buffer and the material-request fact buffer are
drained by the same router helper on every stock route's success path.
What matters: both drain on one call, and a raise in either branch costs
that branch's push -- never the other's, never the committed write.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

from app.domain import realtime as realtime_policy
from app.routers import _stock_events
from app.services import low_stock as low_stock_service
from app.services import material_requests as material_service
from app.services import push as push_service


@pytest.fixture(autouse=True)
def _clean():
    low_stock_service.drain()
    material_service.drain()
    yield
    low_stock_service.drain()
    material_service.drain()


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")


def _capture_emits(monkeypatch):
    envelopes = []
    monkeypatch.setattr(
        _stock_events.realtime_service, "emit", lambda envelope: envelopes.append(envelope)
    )
    return envelopes


def _low_item():
    return SimpleNamespace(id=uuid.uuid4(), name="Tape", quantity=Decimal("5"), low_stock_threshold=6)


def _fact():
    return material_service.StockedFact(
        request_id=uuid.uuid4(), item_name="Tape", work_order_id=uuid.uuid4(),
        work_order_number="WO-1", assignee_ids=(uuid.uuid4(),), supervisor_id=None,
        requester_id=None,
    )


def test_one_flush_drains_both_buffers(db, configured, monkeypatch):
    envelopes = _capture_emits(monkeypatch)
    low_stock_service.record(_low_item(), quantity_before=Decimal("7"))
    fact = _fact()
    material_service._buffer_fact(fact)
    background = BackgroundTasks()

    _stock_events.flush_stock_events(db, background)

    titles = sorted(task.args[1] for task in background.tasks)
    assert titles == ["Low stock", "Material in stock"]
    types = sorted(e["type"] for e in envelopes)
    assert types == [
        realtime_policy.EVENT_ITEM_LOW_STOCK_CHANGED,
        realtime_policy.EVENT_USER_REQUEST_CHANGED,
    ]
    assert any(e["id"] == str(fact.request_id) for e in envelopes)
    assert low_stock_service.drain() == []
    assert material_service.drain() == []


def test_a_low_stock_failure_does_not_lose_the_stocked_push(db, configured, monkeypatch):
    _capture_emits(monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("low stock exploded")

    monkeypatch.setattr(_stock_events.notifications_service, "notify_item_low_stock", boom)
    low_stock_service.record(_low_item(), quantity_before=Decimal("7"))
    material_service._buffer_fact(_fact())
    background = BackgroundTasks()

    _stock_events.flush_stock_events(db, background)  # must not raise

    assert [task.args[1] for task in background.tasks] == ["Material in stock"]


def test_a_stocked_failure_does_not_lose_the_low_stock_push(db, configured, monkeypatch):
    _capture_emits(monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("stocked exploded")

    monkeypatch.setattr(
        _stock_events.notifications_service, "notify_material_request_stocked", boom
    )
    low_stock_service.record(_low_item(), quantity_before=Decimal("7"))
    material_service._buffer_fact(_fact())
    background = BackgroundTasks()

    _stock_events.flush_stock_events(db, background)  # must not raise

    assert [task.args[1] for task in background.tasks] == ["Low stock"]


def test_an_empty_flush_does_nothing(db, configured, monkeypatch):
    envelopes = _capture_emits(monkeypatch)
    background = BackgroundTasks()
    _stock_events.flush_stock_events(db, background)
    assert background.tasks == []
    assert envelopes == []


def test_every_stock_route_still_calls_the_renamed_flush():
    """The seven stock routes and the threshold route each call the helper
    exactly where they called `flush_low_stock`. A grep, not an import: the
    thing that breaks is a route forgetting the call, and that is textual."""
    from pathlib import Path

    routers = Path(__file__).resolve().parents[1] / "app" / "routers"
    counts = {
        name: (routers / name).read_text(encoding="utf-8").count("flush_stock_events(db, background)")
        for name in ("transactions.py", "mass_stages.py", "work_orders.py", "items.py")
    }
    assert counts == {"transactions.py": 3, "mass_stages.py": 2, "work_orders.py": 3, "items.py": 1}
    for name in ("transactions.py", "mass_stages.py", "work_orders.py", "items.py"):
        assert "flush_low_stock" not in (routers / name).read_text(encoding="utf-8")
