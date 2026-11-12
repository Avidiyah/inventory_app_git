"""`PUT /work-orders/smr/{id}/ready` (spec
docs/superpowers/specs/2026-11-06-smr-paper-stage-design.md), over real HTTP.

TestClient, never a direct handler call (see test_smr_paper_check.py).
"""
import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import User
from app.schemas.work_orders_smr_lines import SmrLineIn, SmrReadingIn
from app.services import auth as auth_service
from app.services import work_orders as wos
from app.services import work_orders_smr as smr_service
from app.services import work_orders_smr_lines as lines_service


def _user(db, role="technician"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}", first_name="Pat", last_name="Keyer",
                password_hash=auth_service.hash_password("hunter2"), role=role)
    db.add(user)
    db.flush()
    return user


def _smr_order(db, owner, *, dated=False):
    number = f"SMR-{uuid.uuid4().hex[:8]}"
    sheet = ("WORK ORDER,CREATOR,SERVICE TYPE,SCHEDULE DATE,COMPLETION DATE,ASSIGNED TO,FILED STATUS,LOCATION\r\n"
             f"{number},c,SMR27 - Belfor,05/15/2026,05/21/2026,a,Closed,\"B:1,U 1,x\"\r\n").encode()
    smr_service.import_smr(db, csv_bytes=sheet, user=owner)
    order = wos.find_by_number(db, number)
    if dated:
        lines_service.add_reading(db, work_order_id=order.id, payload=SmrReadingIn(printing_no=1), user=owner)
        lines_service.add_line(db, work_order_id=order.id, user=owner, payload=SmrLineIn(
            vendor="Belfor", hours_each=Decimal("2.0"), reason_code="accurate", work_date=date(2026, 6, 2), reason="paper"))
    return order


def _client(db, user):
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    if user is not None:
        client.cookies.set("session", auth_service.create_session(db, user))
    return client


def _put(db, user, work_order_id, ready):
    try:
        with _client(db, user) as client:
            return client.put(f"/work-orders/smr/{work_order_id}/ready", json={"ready": ready})
    finally:
        del app.dependency_overrides[get_db]


def test_a_technician_is_forbidden(db):
    owner = _user(db, "owner")
    order = _smr_order(db, owner, dated=True)
    assert _put(db, _user(db), order.id, True).status_code == 403


def test_an_undated_order_refuses_the_stamp(db):
    owner, admin = _user(db, "owner"), _user(db, "admin")
    order = _smr_order(db, owner)
    refused = _put(db, admin, order.id, True)
    assert refused.status_code == 409
    assert "Date a line in Weeks 1–7 first." in refused.json()["detail"]


def test_a_line_after_week_7_refuses_the_stamp(db):
    owner, admin = _user(db, "owner"), _user(db, "admin")
    order = _smr_order(db, owner)
    lines_service.add_line(db, work_order_id=order.id, user=owner, payload=SmrLineIn(
        vendor="Belfor", hours_each=Decimal("2.0"), reason_code="accurate", work_date=date(2026, 7, 20),
        reason="paper", status="excluded", exclusion_ground="after 07/12 (no invoices)"))
    assert _put(db, admin, order.id, True).status_code == 409


def test_stamp_is_idempotent_and_clears(db):
    owner, admin, second = _user(db, "owner"), _user(db, "admin"), _user(db, "admin")
    order = _smr_order(db, owner, dated=True)

    stamped = _put(db, admin, order.id, True)
    assert stamped.status_code == 200
    body = stamped.json()
    assert body["stage"] == "ready" and body["ready"]["by_name"] == "Pat Keyer"

    again = _put(db, second, order.id, True).json()
    assert again["ready"]["at"] == body["ready"]["at"]

    cleared = _put(db, admin, order.id, False)
    assert cleared.status_code == 200
    # Labor-only order: stamped above without materials, so clearing lands on no_material.
    assert cleared.json()["stage"] == "no_material" and cleared.json()["ready"] is None


def test_clearing_a_never_stamped_order_is_a_no_op(db):
    owner, admin = _user(db, "owner"), _user(db, "admin")
    order = _smr_order(db, owner)
    cleared = _put(db, admin, order.id, False)
    assert cleared.status_code == 200 and cleared.json()["ready"] is None


def test_the_card_detail_carries_stage_and_stamp(db):
    owner, admin = _user(db, "owner"), _user(db, "admin")
    order = _smr_order(db, owner, dated=True)
    _put(db, admin, order.id, True)
    try:
        with _client(db, admin) as client:
            detail = client.get(f"/work-orders/{order.id}").json()
    finally:
        del app.dependency_overrides[get_db]
    assert detail["smr_stage"] == "ready"
    assert detail["smr_ready"]["by_name"] == "Pat Keyer"
