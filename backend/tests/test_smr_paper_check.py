"""`PUT /work-orders/smr/{id}/paper-check` (spec
docs/superpowers/specs/2026-10-27-smr-paper-check-design.md), over real HTTP.

TestClient, never a direct handler call: this repo has been bitten once by
FastAPI parsing a signature differently than a direct call does.
"""
import uuid

from fastapi.testclient import TestClient

from app.database import get_db
from app.domain import work_orders_smr as smr
from app.main import app
from app.models import User, WorkOrder
from app.services import auth as auth_service
from app.services import work_orders as wos
from app.services import work_orders_smr as smr_service


def _user(db, role="technician"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}", first_name="Pat", last_name="Keyer",
                password_hash=auth_service.hash_password("hunter2"), role=role)
    db.add(user)
    db.flush()
    return user


def _smr_order(db, owner):
    number = f"SMR-{uuid.uuid4().hex[:8]}"
    sheet = ("WORK ORDER,CREATOR,SERVICE TYPE,SCHEDULE DATE,COMPLETION DATE,ASSIGNED TO,FILED STATUS,LOCATION\r\n"
             f"{number},c,SMR27 - Belfor,05/15/2026,05/21/2026,a,Closed,\"B:1,U 1,x\"\r\n").encode()
    smr_service.import_smr(db, csv_bytes=sheet, user=owner)
    return wos.find_by_number(db, number)


def _put(db, user, work_order_id, checked):
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            if user is not None:
                client.cookies.set("session", auth_service.create_session(db, user))
            return client.put(f"/work-orders/smr/{work_order_id}/paper-check", json={"checked": checked})
    finally:
        del app.dependency_overrides[get_db]


def test_a_technician_marks_and_clears(db):
    owner, tech = _user(db, "owner"), _user(db)
    order = _smr_order(db, owner)

    marked = _put(db, tech, order.id, True)
    assert marked.status_code == 200
    assert marked.json()["checked_by_name"] == "Pat Keyer"
    assert marked.json()["checked_at"]
    assert smr.is_edited(order) is False

    cleared = _put(db, tech, order.id, False)
    assert cleared.status_code == 200
    assert cleared.json() is None
    db.refresh(order)
    assert order.smr_paper_checked_at is None and order.smr_paper_checked_by_id is None


def test_marking_twice_keeps_the_first_who_and_when(db):
    owner, first, second = _user(db, "owner"), _user(db), _user(db, "admin")
    order = _smr_order(db, owner)
    original = _put(db, first, order.id, True).json()

    again = _put(db, second, order.id, True)

    assert again.json() == original
    db.refresh(order)
    assert order.smr_paper_checked_by_id == first.id


def test_a_live_order_is_refused(db):
    owner = _user(db, "owner")
    live = WorkOrder(number=f"WO-{uuid.uuid4().hex[:8]}", created_by_id=owner.id)
    db.add(live)
    db.flush()

    assert _put(db, owner, live.id, True).status_code == 400


def test_unknown_order_is_404(db):
    assert _put(db, _user(db), uuid.uuid4(), True).status_code == 404


def test_signed_out_is_401(db):
    owner = _user(db, "owner")
    order = _smr_order(db, owner)
    assert _put(db, None, order.id, True).status_code == 401


def test_the_editor_detail_carries_the_mark(db):
    owner, tech = _user(db, "owner"), _user(db)
    order = _smr_order(db, owner)
    _put(db, tech, order.id, True)

    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            client.cookies.set("session", auth_service.create_session(db, tech))
            detail = client.get(f"/work-orders/{order.id}").json()
    finally:
        del app.dependency_overrides[get_db]

    assert detail["smr_paper_check"]["checked_by_name"] == "Pat Keyer"
