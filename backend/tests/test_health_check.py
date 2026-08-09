"""Tests for the unauthenticated `/healthz` liveness probe.

Layer: unit (no DB, no HTTP client). Matches the "pure, call the handler
directly" style of `test_route_role_gates.py` -- the connection check is
monkeypatched, so these run without a reachable Postgres.

Two of the four are regression guards rather than behavior tests:

- `test_failure_does_not_leak_connection_detail` -- the whole reason this
  endpoint is separate from `/db-test` is that it is unauthenticated. A
  driver error carries the host, port, and database name from the DSN, so
  surfacing `str(exc)` in the response body would hand an anonymous caller
  the connection string.
- `test_healthz_has_no_dependencies` -- a health checker sends no cookie.
  Adding any auth dependency here would make every future deploy fail its
  health check, which is a confusing failure to diagnose from the platform
  side. Better to fail here.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from sqlalchemy.exc import OperationalError

from app import main


def _healthz_route():
    for route in main.app.routes:
        if isinstance(route, APIRoute) and route.endpoint.__name__ == "healthz":
            return route
    raise AssertionError("route 'healthz' not found on the app")


def test_healthz_returns_ok_when_the_database_answers(monkeypatch):
    monkeypatch.setattr(main, "check_connection", lambda: None)

    assert main.healthz() == {"status": "ok"}


def test_healthz_returns_503_when_the_database_is_unreachable(monkeypatch):
    def unreachable():
        raise OperationalError("SELECT 1;", {}, Exception("connection refused"))

    monkeypatch.setattr(main, "check_connection", unreachable)

    with pytest.raises(HTTPException) as exc:
        main.healthz()

    assert exc.value.status_code == 503
    assert exc.value.detail == "Database unavailable."


def test_failure_does_not_leak_connection_detail(monkeypatch):
    # Shaped like a real psycopg failure, which quotes the DSN back.
    leaky = (
        'connection to server at "db.internal" (10.0.0.7), port 5432 failed: '
        'FATAL: password authentication failed for user "inventory" '
        'dbname=inventory'
    )

    def unreachable():
        raise OperationalError("SELECT 1;", {}, Exception(leaky))

    monkeypatch.setattr(main, "check_connection", unreachable)

    with pytest.raises(HTTPException) as exc:
        main.healthz()

    body = str(exc.value.detail)
    for secret in ("db.internal", "10.0.0.7", "5432", "inventory", "password"):
        assert secret not in body


def test_a_handler_bug_is_not_laundered_into_a_503(monkeypatch):
    # Only `SQLAlchemyError` maps to 503. Anything else is a real bug and
    # must keep propagating as a 500 rather than being reported as a
    # database outage.
    def broken():
        raise RuntimeError("typo in the handler")

    monkeypatch.setattr(main, "check_connection", broken)

    with pytest.raises(RuntimeError):
        main.healthz()


def test_healthz_has_no_dependencies():
    route = _healthz_route()

    assert route.dependant.dependencies == []
    assert route.dependencies == []


def test_healthz_is_in_the_openapi_schema():
    assert _healthz_route().include_in_schema is True
