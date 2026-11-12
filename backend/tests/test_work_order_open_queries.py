"""SQL statements one card open costs: `GET /work-orders/{id}` over the real
TestClient route, auth dependency included. A guard for the card-open
optimisation (2026-11-12, 47 statements before): the budget pins today's
count, and the per-line test keeps SMR lines from costing a query each."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.database import engine, get_db
from app.main import app
from app.models import User, WorkOrderLabor, WorkOrderLaborSession
from app.models_smr import SmrWorker
from app.schemas.work_orders_smr_lines import SmrLineIn
from app.services import auth as auth_service
from app.services import work_orders as wos
from app.services import work_orders_smr_lines as lines_service

# Measured 2026-11-12 on the 12-line seed below (12 lines with edit history,
# 12 distinct workers, 2 labor entries with sessions by 2 other technicians).
BUDGET = 16

_TX_CONTROL = ("SAVEPOINT", "RELEASE", "ROLLBACK")


def _user(db, role="admin"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}", first_name="Pat", last_name=role.title(),
                password_hash=auth_service.hash_password("x"), role=role)
    db.add(user)
    db.flush()
    return user


def _seed(db, admin, *, lines: int):
    order = wos.get_or_create_work_order(db, number=f"WO-{uuid.uuid4().hex[:8]}", created_by_id=admin.id)
    order.smr_imported_at = datetime.now(timezone.utc)
    db.flush()
    now = datetime.now(timezone.utc)
    for i in range(lines):
        worker = SmrWorker(display_name=f"Worker {uuid.uuid4().hex[:8]}", vendor="Belfor")
        db.add(worker)
        db.flush()
        out = lines_service.add_line(db, work_order_id=order.id, user=admin, payload=SmrLineIn(
            vendor="Belfor", worker_id=worker.id, hours_each=Decimal("1.0"), reason_code="accurate",
            work_date=date(2026, 6, 1) + timedelta(days=i)))
        line = db.get(lines_service.SmrLaborLine, out.id)
        lines_service.history(db, line=line, actor=admin, field="hours_each", old="2.0", new="1.0",
                              reason="paper", now=now)
    for _ in range(2):
        tech = _user(db, "technician")
        labor = WorkOrderLabor(work_order_id=order.id, technician_id=tech.id, minutes=60, recorded_by_id=tech.id)
        db.add(labor)
        db.flush()
        db.add(WorkOrderLaborSession(work_order_id=order.id, technician_id=tech.id, labor_id=labor.id,
                                     started_at=now - timedelta(hours=2), ended_at=now - timedelta(hours=1)))
    db.commit()
    return order.id


@contextmanager
def _client(db, user):
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            client.cookies.set("session", auth_service.create_session(db, user))
            yield client
    finally:
        del app.dependency_overrides[get_db]


def _count_open(db, client, order_id) -> int:
    """Statements for one open, with an empty identity map as a fresh request has."""
    db.expunge_all()
    statements = []

    def listener(conn, cursor, statement, params, context, executemany):
        if not statement.lstrip().upper().startswith(_TX_CONTROL):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", listener)
    try:
        response = client.get(f"/work-orders/{order_id}")
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    assert response.status_code == 200, response.text
    assert not [s for s in statements if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
    return len(statements)


def test_one_open_stays_within_the_query_budget(db):
    admin = _user(db)
    order_id = _seed(db, admin, lines=12)
    with _client(db, admin) as client:
        count = _count_open(db, client, order_id)
    assert count <= BUDGET, f"{count} statements for one card open (budget {BUDGET})"


def test_query_count_does_not_grow_with_smr_lines(db):
    admin = _user(db)
    small, large = _seed(db, admin, lines=2), _seed(db, admin, lines=12)
    with _client(db, admin) as client:
        assert _count_open(db, client, small) == _count_open(db, client, large)
