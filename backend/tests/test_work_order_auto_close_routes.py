"""Router-boundary tests for import reconciliation.

Driven over real HTTP rather than by calling the handlers, following
`test_work_orders_router.py`: a direct call never exercises FastAPI's own path
matching, and path matching is the entire risk here -- `/auto-close/pending`
and `/auto-close/undo` sit on a router that also serves `/{work_order_id}`, and
a mis-ordered declaration would hand "auto-close" to the UUID parser instead.
DB-backed tests skip if no database.
"""

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.database import get_db
from app.domain import realtime as realtime_policy
from app.domain import roles
from app.domain import work_orders as wo
from app.main import app
from app.models import User, WorkOrder
from app.routers import work_orders as work_orders_router
from app.services import auth as auth_service
from app.services import work_orders as wos


def _seed_user(db, role):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        first_name="Ada",
        last_name="Nunez",
        password_hash=auth_service.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _num():
    return f"WO-{uuid.uuid4().hex[:8]}"


def _csv(rows):
    lines = [",".join(wo.IMPORT_HEADERS)]
    for r in rows:
        lines.append(",".join(r))
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def _row(number):
    return [number, "Commons: 8B", "Belfor", "", "SMR27", "7/29/2026", "Fix couch"]


def _reset_live(db, admin):
    """Leave no live sweepable work orders, so counts below are exact."""
    number = _num()
    wos.import_work_orders(db, csv_bytes=_csv([_row(number)]), user=admin)
    wos.archive_work_order(db, wos.find_by_number(db, number).id, user=admin)
    db.query(WorkOrder).filter(WorkOrder.auto_closed_at.is_not(None)).update(
        {WorkOrder.auto_closed_at: None, WorkOrder.auto_closed_batch_id: None},
        synchronize_session=False,
    )
    db.commit()


def _client(db):
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _release():
    app.dependency_overrides.pop(get_db, None)


def test_the_import_route_reports_the_sweep(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    doomed = _num()
    wos.import_work_orders(db, csv_bytes=_csv([_row(doomed)]), user=admin)
    token = auth_service.create_session(db, admin)

    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.post(
                "/work-orders/import",
                files={"file": ("wo.csv", _csv([_row(_num())]), "text/csv")},
            )
    finally:
        _release()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["auto_closed"] == 1
    assert body["reopened"] == 0
    assert wos.find_by_number(db, doomed).archived_at is not None


def test_the_import_route_reports_a_reopen(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    number = _num()
    wos.import_work_orders(db, csv_bytes=_csv([_row(number)]), user=admin)
    wos.import_work_orders(db, csv_bytes=_csv([_row(_num())]), user=admin)
    assert wos.find_by_number(db, number).archived_at is not None
    token = auth_service.create_session(db, admin)

    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.post(
                "/work-orders/import",
                files={"file": ("wo.csv", _csv([_row(number)]), "text/csv")},
            )
    finally:
        _release()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reopened"] == 1
    assert body["opened"] == 0
    assert wos.find_by_number(db, number).archived_at is None


def test_pending_and_undo_are_not_swallowed_by_the_work_order_id_route(db):
    """The whole reason both routes are declared before `/{work_order_id}`. A
    422 here would mean FastAPI tried to parse "auto-close" as a UUID."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    number = _num()
    wos.import_work_orders(db, csv_bytes=_csv([_row(number)]), user=admin)
    wos.import_work_orders(db, csv_bytes=_csv([_row(_num())]), user=admin)
    token = auth_service.create_session(db, admin)

    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            pending = client.get("/work-orders/auto-close/pending")
            undo = client.post("/work-orders/auto-close/undo")
    finally:
        _release()

    assert pending.status_code == 200, pending.text
    assert pending.json()["closed_count"] == 1
    assert pending.json()["batch_count"] == 1
    assert undo.status_code == 200, undo.text
    assert undo.json() == {"restored": 1}
    assert wos.find_by_number(db, number).archived_at is None


def test_pending_answers_null_with_nothing_to_undo(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    token = auth_service.create_session(db, admin)

    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.get("/work-orders/auto-close/pending")
    finally:
        _release()

    assert response.status_code == 200, response.text
    assert response.json() is None


def test_undo_with_nothing_pending_answers_200_and_zero(db):
    """A lapsed or empty window is not a failure -- there is simply nothing to
    take back, and the page says so in the same message slot."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    token = auth_service.create_session(db, admin)

    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            response = client.post("/work-orders/auto-close/undo")
    finally:
        _release()

    assert response.status_code == 200, response.text
    assert response.json() == {"restored": 0}


def test_undo_refuses_a_supervisor(db):
    """Single-work-order restore is Supervisor+; a bulk undo of an import is an
    import-operator action."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    _reset_live(db, admin)
    token = auth_service.create_session(db, supervisor)

    try:
        with _client(db) as client:
            client.cookies.set("session", token)
            pending = client.get("/work-orders/auto-close/pending")
            undo = client.post("/work-orders/auto-close/undo")
    finally:
        _release()

    assert pending.status_code == 403, pending.text
    assert undo.status_code == 403, undo.text


def test_undo_emits_the_review_queue_envelope_before_the_status_one(monkeypatch):
    """The established collection-level ordering, same as restore and the bulk
    legacy archive. No database: the emits are the subject."""
    envelopes = []
    monkeypatch.setattr(
        work_orders_router.realtime_service,
        "emit",
        lambda envelope: envelopes.append(envelope),
    )
    monkeypatch.setattr(
        work_orders_router.wo_service, "undo_auto_close", lambda db, *, user: 3
    )
    user = SimpleNamespace(id=uuid.uuid4(), role=roles.ROLE_ADMIN)

    result = work_orders_router.undo_work_order_auto_close(user=user, db=None)

    assert result.restored == 3
    assert [e["type"] for e in envelopes] == [
        realtime_policy.EVENT_WORK_ORDER_REVIEW_QUEUE_CHANGED,
        realtime_policy.EVENT_WORK_ORDER_STATUS_CHANGED,
    ]
    assert envelopes[1]["id"] is None
