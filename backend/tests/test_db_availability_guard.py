"""The guard that stops CI reporting success over a half-skipped suite.

`conftest.py` skips DB-backed tests when Postgres is unreachable so that a
contributor without a local database can still run the pure tests. In CI that
same skip is a liability: 244 of 425 test functions take the `db` fixture, so a
bad DATABASE_URL would produce a green run over 43% of the suite. In CI an
unreachable database must be an error instead.
"""

import pytest

from tests._db_availability import handle_unreachable_database


def test_raises_in_ci(monkeypatch):
    monkeypatch.setenv("CI", "true")

    with pytest.raises(RuntimeError) as excinfo:
        handle_unreachable_database(OSError("connection refused"))

    assert "connection refused" in str(excinfo.value)


def test_skips_outside_ci(monkeypatch):
    monkeypatch.delenv("CI", raising=False)

    with pytest.raises(pytest.skip.Exception):
        handle_unreachable_database(OSError("connection refused"))


def test_ci_set_to_false_still_skips(monkeypatch):
    """`CI=false` is not CI. Matches the SQL_ECHO idiom in app/database.py:48."""
    monkeypatch.setenv("CI", "false")

    with pytest.raises(pytest.skip.Exception):
        handle_unreachable_database(OSError("connection refused"))


def test_ci_gate_proof():
    assert False, "TEMPORARY: proving the deploy gate blocks a red build"
