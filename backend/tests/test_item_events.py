"""W6: every change to a low item emits `item.low_stock.changed` once, after commit.

The listener in `app/item_events.py` is the only emitter, so each writer is
driven through its service or its real route and the envelopes are counted.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import item_events
from app.database import get_db
from app.domain import realtime as realtime_policy
from app.main import app
from app.models import Item, User
from app.services import auth
from app.services import low_stock as low_stock_service
from app.services.transactions import apply_correction, apply_transaction


@pytest.fixture(autouse=True)
def _clean_buffer():
    low_stock_service.drain()
    yield
    low_stock_service.drain()


@pytest.fixture
def sent(monkeypatch):
    envelopes = []
    monkeypatch.setattr(item_events.realtime_service, "emit", envelopes.append)
    return envelopes


def _ids(envelopes):
    low = [e for e in envelopes if e["type"] == realtime_policy.EVENT_ITEM_LOW_STOCK_CHANGED]
    return [e["id"] for e in low]


def _user(db, role="admin"):
    user = User(
        username=f"iev-{uuid.uuid4().hex[:10]}", first_name="Test", last_name=role.title(),
        password_hash=auth.hash_password("hunter2"), role=role,
    )
    db.add(user)
    db.flush()
    return user


def _item(db, quantity, threshold=6):
    item = Item(
        barcode=f"IEV-{uuid.uuid4().hex[:10]}", name="Event Item", quantity=Decimal(quantity),
        location="Shelf E", price=Decimal("1.00"), low_stock_threshold=threshold,
    )
    db.add(item)
    db.commit()
    return item


def _move(db, item, transaction_type, quantity):
    return apply_transaction(
        db, item_id=item.id, transaction_type=transaction_type, quantity=Decimal(quantity),
        user_id=_user(db).id, work_order_number=None,
    )


def _http(db, method, path, **kwargs):
    token = auth.create_session(db, _user(db))
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            client.cookies.set("session", token)
            return client.request(method, path, **kwargs)
    finally:
        del app.dependency_overrides[get_db]


def test_dispense_of_a_low_item_emits_once(db, sent):
    item = _item(db, "4")
    sent.clear()
    _move(db, item, "dispense", "1")
    assert _ids(sent) == [str(item.id)]


def test_restock_that_clears_the_condition_emits(db, sent):
    item = _item(db, "4")
    sent.clear()
    _move(db, item, "stock", "16")
    assert _ids(sent) == [str(item.id)]


def test_dispense_that_crosses_into_low_emits(db, sent):
    item = _item(db, "8")
    sent.clear()
    _move(db, item, "dispense", "3")
    assert _ids(sent) == [str(item.id)]


def test_healthy_item_stays_silent(db, sent):
    item = _item(db, "20")
    _move(db, item, "dispense", "1")
    assert _ids(sent) == []


def test_correction_emits(db, sent):
    item = _item(db, "4")
    sent.clear()
    apply_correction(db, item_id=item.id, new_quantity=Decimal("5"), reason="Counted.", user_id=_user(db).id)
    assert _ids(sent) == [str(item.id)]


def test_threshold_edit_emits(db, sent):
    item = _item(db, "4")
    sent.clear()
    response = _http(db, "PATCH", f"/items/{item.id}/low-stock-threshold", json={"low_stock_threshold": 2})
    assert response.status_code == 200, response.text
    assert _ids(sent) == [str(item.id)]


def test_name_edit_of_a_low_item_emits(db, sent):
    item = _item(db, "4")
    sent.clear()
    response = _http(db, "PATCH", f"/items/{item.id}", json={"name": "Renamed"})
    assert response.status_code == 200, response.text
    assert _ids(sent) == [str(item.id)]


def test_name_edit_of_a_healthy_item_stays_silent(db, sent):
    item = _item(db, "20")
    response = _http(db, "PATCH", f"/items/{item.id}", json={"name": "Renamed"})
    assert response.status_code == 200, response.text
    assert _ids(sent) == []


def test_create_below_threshold_emits(db, sent):
    response = _http(db, "POST", "/items/", json={
        "barcode": f"IEV-{uuid.uuid4().hex[:10]}", "name": "Nearly Empty",
        "location": "Bay 1", "quantity": "1",
    })
    assert response.status_code == 201, response.text
    assert _ids(sent) == [response.json()["id"]]


def test_archive_of_a_low_item_emits(db, sent):
    item = _item(db, "4")
    sent.clear()
    response = _http(db, "DELETE", f"/items/{item.id}")
    assert response.status_code == 204, response.text
    assert _ids(sent) == [str(item.id)]


def test_rollback_emits_nothing(db, sent):
    item = _item(db, "4")
    sent.clear()
    item.quantity = Decimal("3")
    db.flush()
    db.rollback()
    _user(db)
    db.commit()
    assert _ids(sent) == []


def test_two_writes_in_one_commit_emit_once(db, sent):
    item = _item(db, "4")
    sent.clear()
    item.quantity = Decimal("3")
    db.flush()
    item.quantity = Decimal("2")
    db.flush()
    db.commit()
    assert _ids(sent) == [str(item.id)]


def test_untouched_item_in_the_session_stays_silent(db, sent):
    item = _item(db, "4")
    sent.clear()
    assert db.get(Item, item.id).quantity == Decimal("4")
    _user(db)
    db.commit()
    assert _ids(sent) == []
