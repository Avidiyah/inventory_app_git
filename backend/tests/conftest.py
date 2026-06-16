"""Shared pytest fixtures.

`db` is the repo's first database-backed test fixture. It joins a session to an
external transaction that is rolled back after each test, using the SQLAlchemy
2.0 `join_transaction_mode="create_savepoint"` pattern -- so service code under
test can call `commit()` freely without persisting anything (each commit is a
savepoint release inside the outer transaction, which is discarded at teardown).

Tests that take `db` need a reachable Postgres (per `DATABASE_URL`). If the
connection fails, the fixture skips rather than errors, so the pure (no-DB)
suite still runs for contributors without a database.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database import engine


@pytest.fixture
def db():
    try:
        connection = engine.connect()
    except OperationalError as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"database unreachable: {exc}")

    trans = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
    )
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()
