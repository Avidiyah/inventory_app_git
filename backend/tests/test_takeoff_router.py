"""Takeoff HTTP routes, the dispense hook, the arrival hook and the detail field.

Driven through a real `TestClient` (never by calling handlers directly).
"""

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.domain import roles
from app.main import app
from app.models import Item, TakeoffPurchase, User, WorkOrderTakeoffLine
from app.services import auth as auth_service
from app.services import work_orders as wos

D = Decimal


def _user(db, role):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth_service.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _item(db, qty="10", price="5"):
    item = Item(
        barcode=f"BC-{uuid.uuid4().hex[:10]}",
        name=f"Widget {uuid.uuid4().hex[:6]}",
        quantity=D(qty),
        location="Bay 1",
        price=D(price),
    )
    db.add(item)
    db.flush()
    return item


def _order(db, owner):
    order = wos.get_or_create_work_order(
        db, number=f"WO-{uuid.uuid4().hex[:8]}", service_type="Water", created_by_id=owner.id
    )
    db.flush()
    return order


def _client(db, user):
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    client.cookies.set("session", auth_service.create_session(db, user))
    return client


def _setup(db, role=roles.ROLE_SUPERVISOR):
    owner = _user(db, roles.ROLE_OWNER)
    actor = _user(db, role)
    order = _order(db, owner)
    item = _item(db)
    db.commit()
    return actor, order, item


def _post_line(client, order, item, qty="4"):
    return client.post(f"/work-orders/{order.id}/takeoff", json={"item_id": str(item.id), "quantity": qty})


def test_technician_cannot_add_takeoff_line(db):
    actor, order, item = _setup(db, roles.ROLE_TECHNICIAN)
    try:
        with _client(db, actor) as client:
            assert _post_line(client, order, item).status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_team_lead_adds_line(db):
    actor, order, item = _setup(db)
    try:
        with _client(db, actor) as client:
            resp = _post_line(client, order, item, "2.5")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert D(resp.json()["quantity"]) == D("2.5")
    assert resp.json()["item_name"] == item.name


def test_patch_and_delete_line(db):
    actor, order, item = _setup(db)
    try:
        with _client(db, actor) as client:
            line_id = _post_line(client, order, item).json()["id"]
            patched = client.patch(f"/work-orders/{order.id}/takeoff/{line_id}", json={"quantity": "9"})
            assert patched.status_code == 200 and D(patched.json()["quantity"]) == 9
            assert client.delete(f"/work-orders/{order.id}/takeoff/{line_id}").status_code == 204
            assert client.delete(f"/work-orders/{order.id}/takeoff/{line_id}").status_code == 409
    finally:
        app.dependency_overrides.clear()
    assert db.query(WorkOrderTakeoffLine).filter_by(work_order_id=order.id).count() == 0


def test_detail_includes_takeoff_lines(db):
    actor, order, item = _setup(db)
    try:
        with _client(db, actor) as client:
            _post_line(client, order, item, "3")
            detail = client.get(f"/work-orders/{order.id}").json()
    finally:
        app.dependency_overrides.clear()
    assert [(t["item_id"], D(t["quantity"])) for t in detail["takeoff"]] == [(str(item.id), D(3))]


def test_dispense_with_takeoff_line_reduces_it(db):
    actor, order, item = _setup(db)
    try:
        with _client(db, actor) as client:
            line_id = _post_line(client, order, item, "4").json()["id"]
            resp = client.post(
                f"/work-orders/{order.id}/items",
                json={"item_id": str(item.id), "quantity": "3", "takeoff_line_id": line_id},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert D(resp.json()["quantity"]) == 3
    db.expire_all()
    line = db.query(WorkOrderTakeoffLine).filter_by(work_order_id=order.id).one()
    assert line.quantity == 1
    assert db.get(Item, item.id).quantity == 7


def test_dispense_with_stale_takeoff_line_409_and_no_stock_change(db):
    actor, order, item = _setup(db)
    try:
        with _client(db, actor) as client:
            line_id = _post_line(client, order, item, "4").json()["id"]
            assert client.delete(f"/work-orders/{order.id}/takeoff/{line_id}").status_code == 204
            resp = client.post(
                f"/work-orders/{order.id}/items",
                json={"item_id": str(item.id), "quantity": "3", "takeoff_line_id": line_id},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 409
    assert resp.json()["detail"] == "This takeoff line changed. Refresh and try again."
    db.rollback()
    assert db.get(Item, item.id).quantity == 10
    assert order.items == []


def test_stock_transaction_counts_down_purchase(db):
    actor, order, item = _setup(db)
    db.add(TakeoffPurchase(
        item_id=item.id, service_type_key="water", service_type_label="Water",
        quantity_on_the_way=D(100),
    ))
    db.commit()
    try:
        with _client(db, actor) as client:
            resp = client.post(
                "/transactions/", json={"item_id": str(item.id), "transaction_type": "stock", "quantity": "50"}
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    db.expire_all()
    assert db.query(TakeoffPurchase).filter_by(item_id=item.id).one().quantity_on_the_way == 50
    assert db.get(Item, item.id).quantity == 60


def test_overview_gate(db):
    lead, _, _ = _setup(db, roles.ROLE_SUPERVISOR)
    oa = _user(db, roles.ROLE_TECHFM_OA)
    db.commit()
    try:
        with _client(db, lead) as client:
            assert client.get("/takeoff/").status_code == 403
        with _client(db, oa) as client:
            resp = client.get("/takeoff/")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert "groups" in resp.json()


def test_put_purchase_zero_clears(db):
    _, _, item = _setup(db)
    oa = _user(db, roles.ROLE_TECHFM_OA)
    db.commit()
    body = {"item_id": str(item.id), "service_type_key": "water", "service_type_label": "Water", "quantity": "6"}
    try:
        with _client(db, oa) as client:
            assert client.put("/takeoff/purchases", json=body).status_code == 204
            assert db.query(TakeoffPurchase).filter_by(item_id=item.id).one().quantity_on_the_way == 6
            assert client.put("/takeoff/purchases", json={**body, "quantity": "0"}).status_code == 204
    finally:
        app.dependency_overrides.clear()
    assert db.query(TakeoffPurchase).filter_by(item_id=item.id).count() == 0
