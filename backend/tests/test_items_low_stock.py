"""The Low Stock column, list route, and threshold route.

Route tests drive real HTTP through `TestClient` rather than calling the
handler function directly: a direct call never exercises FastAPI's
path/query parsing, which is where this repo has been bitten before
(FastAPI 0.136 / Pydantic 2.13 and int `Literal` params).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from decimal import Decimal

from app.domain import low_stock as low_stock_policy
from app.models import Item


def _seed_item(db, *, quantity="10", threshold=None):
    item = Item(
        barcode=f"BC-{uuid.uuid4().hex[:10]}",
        name=f"Widget {uuid.uuid4().hex[:6]}",
        quantity=Decimal(quantity),
        location="Bay 1",
    )
    if threshold is not None:
        item.low_stock_threshold = threshold
    db.add(item)
    db.flush()
    return item


def test_new_items_default_to_the_shared_threshold(db):
    item = _seed_item(db)
    db.commit()
    db.refresh(item)
    assert item.low_stock_threshold == low_stock_policy.DEFAULT_LOW_STOCK_THRESHOLD


import uuid as _uuid

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import User
from app.services import auth as auth_service
from app.services import push as push_service


def _seed_user(db, role):
    user = User(
        username=f"u-{_uuid.uuid4().hex[:10]}",
        password_hash=auth_service.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _client(db):
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_a_dispense_over_real_http_schedules_a_low_stock_push(db, monkeypatch):
    """End to end through FastAPI: the handler must actually receive a
    `BackgroundTasks` and the drain must run on the success path."""
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    sent = []
    monkeypatch.setattr(
        push_service,
        "send_to_users",
        lambda session, ids, title, body: sent.append((title, body))
        or {"sent": 1, "dropped": 0, "failed": 0},
    )
    _seed_user(db, "admin")
    actor = _seed_user(db, "supervisor")
    item = _seed_item(db, quantity="7")
    db.commit()
    token = auth_service.create_session(db, actor)

    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.post(
                "/transactions/",
                json={
                    "item_id": str(item.id),
                    "transaction_type": "dispense",
                    "quantity": "2",
                },
            )
    finally:
        del app.dependency_overrides[get_db]

    assert response.status_code == 201, response.text
    assert sent, "no low-stock push was delivered"
    assert sent[0][1] == f"{item.name} is down to 5."


from datetime import datetime, timedelta, timezone

from app.models import Transaction


def _dispense(db, item, *, quantity="3", hours_ago=1, voided=False, affects_stock=True,
              transaction_type="dispense"):
    txn = Transaction(
        item_id=item.id,
        user_id=None,
        transaction_type=transaction_type,
        quantity=Decimal(quantity),
        work_order_number=None,
        affects_stock=affects_stock,
        created_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        voided_at=datetime.now(timezone.utc) if voided else None,
    )
    db.add(txn)
    db.flush()
    return txn


def _low_stock_rows(db, role="admin"):
    user = _seed_user(db, role)
    db.commit()
    token = auth_service.create_session(db, user)
    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.get("/items/low-stock")
    finally:
        del app.dependency_overrides[get_db]
    return response


def test_low_stock_lists_only_items_at_or_below_their_threshold(db):
    low = _seed_item(db, quantity="6", threshold=6)
    fast = _seed_item(db, quantity="15", threshold=20)
    healthy = _seed_item(db, quantity="7", threshold=6)

    response = _low_stock_rows(db)

    assert response.status_code == 200, response.text
    ids = {row["id"] for row in response.json()}
    assert str(low.id) in ids
    assert str(fast.id) in ids
    assert str(healthy.id) not in ids


def test_low_stock_excludes_archived_items(db):
    archived = _seed_item(db, quantity="1", threshold=6)
    archived.archived_at = datetime.now(timezone.utc)

    response = _low_stock_rows(db)

    assert str(archived.id) not in {row["id"] for row in response.json()}


def test_low_stock_is_not_shadowed_by_the_barcode_lookup(db):
    """`GET /items/{barcode}` would swallow the literal path if it were
    registered first, answering 404 for a route that exists."""
    _seed_item(db, quantity="1", threshold=6)
    response = _low_stock_rows(db)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_low_stock_is_gated_at_techfm_oa(db):
    _seed_item(db, quantity="1", threshold=6)
    assert _low_stock_rows(db, role="supervisor").status_code == 403
    assert _low_stock_rows(db, role="techfm_oa").status_code == 200


def test_seven_day_usage_counts_a_recent_dispense(db):
    item = _seed_item(db, quantity="2", threshold=6)
    _dispense(db, item, quantity="3", hours_ago=1)
    _dispense(db, item, quantity="4", hours_ago=167)

    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    assert Decimal(row["dispensed_last_7_days"]) == Decimal("7")


def test_seven_day_usage_excludes_anything_older_than_the_window(db):
    item = _seed_item(db, quantity="2", threshold=6)
    _dispense(db, item, quantity="9", hours_ago=169)

    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    assert Decimal(row["dispensed_last_7_days"]) == Decimal("0")


def test_seven_day_usage_excludes_voided_rows(db):
    """A voided transaction is a mistake that was undone; counting it
    would overstate how fast the item moves."""
    item = _seed_item(db, quantity="2", threshold=6)
    _dispense(db, item, quantity="5", voided=True)

    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    assert Decimal(row["dispensed_last_7_days"]) == Decimal("0")


def test_seven_day_usage_includes_retroactive_dispenses(db):
    """Stock consumed off-app and backfilled on paper is still usage. It
    is stored as a `dispense` with `affects_stock=false`, so including it
    means simply not filtering on that column."""
    item = _seed_item(db, quantity="2", threshold=6)
    _dispense(db, item, quantity="6", affects_stock=False)

    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    assert Decimal(row["dispensed_last_7_days"]) == Decimal("6")


def test_seven_day_usage_excludes_corrections(db):
    """A recount write-off is not consumption. Counting it would make a
    mis-stocked item look fast-moving and invite the wrong threshold."""
    item = _seed_item(db, quantity="2", threshold=6)
    _dispense(db, item, quantity="-8", transaction_type="adjust")

    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    assert Decimal(row["dispensed_last_7_days"]) == Decimal("0")


def test_an_item_with_no_usage_reports_zero(db):
    item = _seed_item(db, quantity="1", threshold=6)
    row = next(r for r in _low_stock_rows(db).json() if r["id"] == str(item.id))
    assert Decimal(row["dispensed_last_7_days"]) == Decimal("0")


def test_low_stock_is_ordered_by_headroom(db):
    """Deepest below its own threshold first, so the item most likely to
    run out is the one nearest the top of the page."""
    barely = _seed_item(db, quantity="6", threshold=6)     # headroom 0
    deep = _seed_item(db, quantity="1", threshold=20)      # headroom -19

    ids = [row["id"] for row in _low_stock_rows(db).json()]
    assert ids.index(str(deep.id)) < ids.index(str(barely.id))


def _set_threshold(db, item, value, *, role="admin"):
    user = _seed_user(db, role)
    db.commit()
    token = auth_service.create_session(db, user)
    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.patch(
                f"/items/{item.id}/low-stock-threshold",
                json={"low_stock_threshold": value},
            )
    finally:
        del app.dependency_overrides[get_db]
    return response


def test_setting_a_threshold_persists_it(db):
    item = _seed_item(db, quantity="30", threshold=6)
    response = _set_threshold(db, item, 20)
    assert response.status_code == 200, response.text
    assert response.json()["low_stock_threshold"] == 20


def test_a_threshold_below_one_is_rejected(db):
    """No mute value: stock cannot go below zero, so a zero threshold
    would be an invisible off-switch rather than a threshold."""
    item = _seed_item(db, quantity="30", threshold=6)
    assert _set_threshold(db, item, 0).status_code == 422


def test_a_missing_threshold_is_rejected(db):
    item = _seed_item(db, quantity="30", threshold=6)
    user = _seed_user(db, "admin")
    db.commit()
    token = auth_service.create_session(db, user)
    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.patch(
                f"/items/{item.id}/low-stock-threshold", json={}
            )
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 422


def test_the_threshold_route_is_gated_at_techfm_oa(db):
    item = _seed_item(db, quantity="30", threshold=6)
    assert _set_threshold(db, item, 10, role="supervisor").status_code == 403


def test_an_unknown_item_is_404(db):
    user = _seed_user(db, "admin")
    db.commit()
    token = auth_service.create_session(db, user)
    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.patch(
                f"/items/{_uuid.uuid4()}/low-stock-threshold",
                json={"low_stock_threshold": 5},
            )
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 404


def test_raising_a_threshold_past_the_current_count_pushes(db, monkeypatch):
    """The retune case. Nothing moved, but the item is newly low, and the
    crew is told the same way a dispense would tell them."""
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    sent = []
    monkeypatch.setattr(
        push_service,
        "send_to_users",
        lambda session, ids, title, body: sent.append(body)
        or {"sent": 1, "dropped": 0, "failed": 0},
    )
    item = _seed_item(db, quantity="10", threshold=6)

    assert _set_threshold(db, item, 20).status_code == 200
    assert sent == [f"{item.name} is down to 10."]


def test_lowering_a_threshold_clear_of_the_count_pushes_nothing(db, monkeypatch):
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    sent = []
    monkeypatch.setattr(
        push_service,
        "send_to_users",
        lambda session, ids, title, body: sent.append(body)
        or {"sent": 1, "dropped": 0, "failed": 0},
    )
    item = _seed_item(db, quantity="10", threshold=20)

    assert _set_threshold(db, item, 6).status_code == 200
    assert sent == []


def test_raising_a_threshold_that_keeps_a_low_item_low_pushes_nothing(db, monkeypatch):
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    sent = []
    monkeypatch.setattr(
        push_service,
        "send_to_users",
        lambda session, ids, title, body: sent.append(body)
        or {"sent": 1, "dropped": 0, "failed": 0},
    )
    item = _seed_item(db, quantity="3", threshold=6)

    assert _set_threshold(db, item, 20).status_code == 200
    assert sent == []


def test_creating_an_item_below_its_threshold_lists_it_without_pushing(db, monkeypatch):
    monkeypatch.setattr(push_service, "VAPID_PRIVATE_KEY", "test-private-key")
    sent = []
    monkeypatch.setattr(
        push_service,
        "send_to_users",
        lambda session, ids, title, body: sent.append(body)
        or {"sent": 1, "dropped": 0, "failed": 0},
    )
    envelopes = []
    from app.routers import _low_stock
    monkeypatch.setattr(
        _low_stock.realtime_service, "emit", lambda e: envelopes.append(e)
    )
    user = _seed_user(db, "admin")
    db.commit()
    token = auth_service.create_session(db, user)
    barcode = f"BC-{_uuid.uuid4().hex[:10]}"

    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            created = client.post(
                "/items/",
                json={
                    "barcode": barcode,
                    "name": "Nearly Empty",
                    "location": "Bay 1",
                    "quantity": "2",
                },
            )
            listed = client.get("/items/low-stock")
    finally:
        del app.dependency_overrides[get_db]

    assert created.status_code == 201, created.text
    assert sent == []
    assert len(envelopes) == 1
    assert barcode in {row["barcode"] for row in listed.json()}


def test_archiving_a_low_item_invalidates_the_page(db, monkeypatch):
    envelopes = []
    from app.routers import _low_stock
    monkeypatch.setattr(
        _low_stock.realtime_service, "emit", lambda e: envelopes.append(e)
    )
    item = _seed_item(db, quantity="1", threshold=6)
    user = _seed_user(db, "admin")
    db.commit()
    token = auth_service.create_session(db, user)

    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.delete(f"/items/{item.id}")
    finally:
        del app.dependency_overrides[get_db]

    assert response.status_code == 204
    assert len(envelopes) == 1
