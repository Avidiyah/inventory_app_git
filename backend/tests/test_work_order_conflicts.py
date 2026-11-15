"""W3: a save based on a value someone else has since changed is refused.

Real `TestClient` requests, two signed-in users. The 409 body names each
field, its current value, who changed it and how long ago (server-computed).
"""

import uuid
from contextlib import contextmanager
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import get_db
from app.domain import roles
from app.main import app
from app.models import Item, User, WorkOrder
from app.services import auth as auth_service
from app.services import work_orders as wos


def _user(db, role, first="Maria", last="Lopez"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        first_name=first,
        last_name=last,
        password_hash=auth_service.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _wo(db, creator):
    return wos.get_or_create_work_order(
        db, number=f"WO-{uuid.uuid4().hex[:8]}", created_by_id=creator.id
    )


@contextmanager
def _clients(db, *users):
    tokens = [auth_service.create_session(db, u) for u in users]
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as base:
            clients = []
            for token in tokens:
                client = TestClient(app)
                client.cookies.set("session", token)
                clients.append(client)
            yield clients
    finally:
        del app.dependency_overrides[get_db]


def _pair(db):
    a = _user(db, roles.ROLE_ADMIN, "Maria", "Lopez")
    b = _user(db, roles.ROLE_ADMIN, "Sam", "Ortiz")
    return a, b, _wo(db, a)


def _patch(client, w, body):
    return client.patch(f"/work-orders/{w.id}", json=body)


def _only_conflict(response):
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "field_conflict"
    assert detail["message"]
    [conflict] = detail["conflicts"]
    return conflict


def test_stale_priority_is_refused_with_who_and_when(db):
    a, b, w = _pair(db)
    with _clients(db, a, b) as (ca, cb):
        assert _patch(ca, w, {"priority": "P2"}).status_code == 200
        response = _patch(cb, w, {"priority": "P3", "expected": {"priority": None}})
    conflict = _only_conflict(response)
    assert conflict["field"] == "priority"
    assert conflict["label"] == "Priority"
    assert conflict["current"] == "P2"
    assert conflict["current_label"] == "P2"
    assert conflict["changed_by"] == a.full_name
    assert 0 <= conflict["seconds_ago"] < 5
    db.refresh(w)
    assert w.priority == "P2"


def test_clean_save_with_matching_expected_succeeds(db):
    a, b, w = _pair(db)
    with _clients(db, a, b) as (ca, cb):
        _patch(ca, w, {"priority": "P2"})
        response = _patch(cb, w, {"priority": "P3", "expected": {"priority": "P2"}})
    assert response.status_code == 200, response.text
    assert response.json()["priority"] == "P3"


def test_no_expected_means_no_check(db):
    a, b, w = _pair(db)
    with _clients(db, a, b) as (ca, cb):
        _patch(ca, w, {"priority": "P2"})
        response = _patch(cb, w, {"priority": "P3"})
    assert response.status_code == 200


def test_conflict_refuses_the_whole_save(db):
    a, b, w = _pair(db)
    with _clients(db, a, b) as (ca, cb):
        _patch(ca, w, {"priority": "P2"})
        response = _patch(
            cb, w,
            {"priority": "P3", "location": "Bldg 9", "expected": {"priority": None, "location": None}},
        )
    assert response.status_code == 409
    db.refresh(w)
    assert (w.priority, w.location) == ("P2", None)


def test_blank_and_null_compare_equal(db):
    a, b, w = _pair(db)
    with _clients(db, a, b) as (_, cb):
        response = _patch(cb, w, {"location": "Bldg 9", "expected": {"location": "  "}})
    assert response.status_code == 200, response.text


def test_expected_text_is_trimmed(db):
    a, b, w = _pair(db)
    with _clients(db, a, b) as (ca, cb):
        _patch(ca, w, {"location": "Bldg 4"})
        response = _patch(cb, w, {"location": "Bldg 9", "expected": {"location": " Bldg 4 "}})
    assert response.status_code == 200, response.text


def test_multiline_location_compares_without_line_breaks(db):
    a, b, w = _pair(db)
    db.execute(text("UPDATE work_orders SET location = :v WHERE id = :id"),
               {"v": "Bldg 4\r\nUnit 2", "id": w.id})
    with _clients(db, a, b) as (_, cb):
        response = _patch(cb, w, {"location": "Bldg 9", "expected": {"location": "Bldg 4Unit 2"}})
    assert response.status_code == 200, response.text


def test_crew_compares_as_a_set(db):
    a, b, w = _pair(db)
    t1 = _user(db, roles.ROLE_TECHNICIAN, "Tia", "Ng")
    t2 = _user(db, roles.ROLE_TECHNICIAN, "Ray", "Cole")
    with _clients(db, a, b) as (ca, cb):
        _patch(ca, w, {"assigned_to_ids": [str(t1.id), str(t2.id)]})
        response = _patch(cb, w, {
            "assigned_to_ids": [str(t1.id)],
            "expected": {"assigned_to_ids": [str(t2.id), str(t1.id)]},
        })
    assert response.status_code == 200, response.text


def test_crew_conflict_labels_names(db):
    a, b, w = _pair(db)
    t1 = _user(db, roles.ROLE_TECHNICIAN, "Tia", "Ng")
    t2 = _user(db, roles.ROLE_TECHNICIAN, "Ray", "Cole")
    with _clients(db, a, b) as (ca, cb):
        _patch(ca, w, {"assigned_to_ids": [str(t1.id), str(t2.id)]})
        response = _patch(cb, w, {"assigned_to_ids": [str(t1.id)], "expected": {"assigned_to_ids": []}})
    conflict = _only_conflict(response)
    assert conflict["label"] == "Assigned technicians"
    assert sorted(conflict["current"]) == sorted([str(t1.id), str(t2.id)])
    assert set(conflict["current_label"].split(", ")) == {t1.full_name, t2.full_name}


def test_status_conflict_uses_the_status_label(db):
    a, b, w = _pair(db)
    with _clients(db, a, b) as (ca, cb):
        _patch(ca, w, {"status": "on_hold"})
        response = _patch(cb, w, {"status": "in_progress", "expected": {"status": "created"}})
    conflict = _only_conflict(response)
    assert conflict["current"] == "on_hold"
    assert conflict["current_label"] == "On-Hold"
    assert conflict["label"] == "Status"


def test_supervisor_conflict_labels_the_name(db):
    a, b, w = _pair(db)
    lead = _user(db, roles.ROLE_SUPERVISOR, "Lee", "Park")
    with _clients(db, a, b) as (ca, cb):
        _patch(ca, w, {"supervisor_id": str(lead.id)})
        response = _patch(cb, w, {"supervisor_id": None, "expected": {"supervisor_id": None}})
    conflict = _only_conflict(response)
    assert conflict["label"] == "Team Lead"
    assert conflict["current"] == str(lead.id)
    assert conflict["current_label"] == lead.full_name


def test_cleared_value_reads_blank(db):
    a, b, w = _pair(db)
    with _clients(db, a, b) as (ca, cb):
        _patch(ca, w, {"location": "Bldg 4"})
        _patch(ca, w, {"location": None})
        response = _patch(cb, w, {"location": "Bldg 9", "expected": {"location": "Bldg 4"}})
    conflict = _only_conflict(response)
    assert conflict["current"] is None
    assert conflict["current_label"] == "(blank)"


def test_no_stamp_gives_null_seconds_and_name(db):
    a, b, w = _pair(db)
    db.execute(text("UPDATE work_orders SET priority = 'P5' WHERE id = :id"), {"id": w.id})
    with _clients(db, a, b) as (_, cb):
        response = _patch(cb, w, {"priority": "P3", "expected": {"priority": None}})
    conflict = _only_conflict(response)
    assert conflict["seconds_ago"] is None
    assert conflict["changed_by"] is None


def test_new_check_runs_before_legacy_supervisor_check(db):
    a, b, w = _pair(db)
    lead = _user(db, roles.ROLE_SUPERVISOR, "Lee", "Park")
    with _clients(db, a, b) as (ca, cb):
        _patch(ca, w, {"supervisor_id": str(lead.id)})
        response = _patch(cb, w, {
            "supervisor_id": str(b.id),
            "expected_supervisor_id": None,
            "expected": {"supervisor_id": None},
        })
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "field_conflict"


def test_legacy_expected_supervisor_still_409s(db):
    a, b, w = _pair(db)
    lead = _user(db, roles.ROLE_SUPERVISOR, "Lee", "Park")
    with _clients(db, a, b) as (ca, cb):
        _patch(ca, w, {"supervisor_id": str(lead.id)})
        response = _patch(cb, w, {"supervisor_id": str(b.id), "expected_supervisor_id": None})
    assert response.status_code == 409
    assert response.json()["detail"] == f"This Work Order was already assigned to {lead.full_name}"


def test_unknown_expected_key_is_422(db):
    a, b, w = _pair(db)
    with _clients(db, a, b) as (_, cb):
        response = _patch(cb, w, {"priority": "P3", "expected": {"notes": "x"}})
    assert response.status_code == 422
