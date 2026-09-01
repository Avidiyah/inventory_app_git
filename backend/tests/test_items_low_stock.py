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
