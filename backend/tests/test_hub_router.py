"""Router-boundary tests for the User Hub timesheet endpoints."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import User
from app.routers import hub as hub_router
from app.services import auth as auth_service
from app.services import hub as hub_service


def _empty_payload(start=date(2026, 8, 17), end=date(2026, 8, 23)):
    return hub_service.HubTimesheetPayload(
        range=hub_service.TimesheetRange(start=start, end=end),
        crew_totals_by_day=[
            hub_service.TimesheetDayTotal(
                date=start + timedelta(days=offset), minutes=0
            )
            for offset in range((end - start).days + 1)
        ],
    )


def test_default_timesheet_range_is_the_current_central_week():
    now = datetime(2026, 8, 20, 19, 0, tzinfo=timezone.utc)
    assert hub_router._default_range(now) == (
        date(2026, 8, 17),
        date(2026, 8, 23),
    )


def test_timesheet_route_maps_the_92_day_domain_error_to_422():
    user = SimpleNamespace(id=uuid.uuid4())

    with pytest.raises(HTTPException) as exc_info:
        hub_router.get_hub_timesheets(
            start=date(2026, 1, 1),
            end=date(2026, 4, 3),
            user_id=None,
            user=user,
            db=None,
        )

    assert exc_info.value.status_code == 422
    assert "92" in exc_info.value.detail


def test_timesheet_export_returns_csv_and_the_payroll_filename(monkeypatch):
    monkeypatch.setattr(
        hub_router.hub_service,
        "timesheets_hub",
        lambda *args, **kwargs: _empty_payload(
            start=kwargs["start"], end=kwargs["end"]
        ),
    )
    user = SimpleNamespace(id=uuid.uuid4())

    response = hub_router.export_hub_timesheets(
        start=date(2026, 8, 17),
        end=date(2026, 8, 23),
        user_id=None,
        user=user,
        db=None,
    )

    assert response.media_type == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="timesheet_2026-08-17_to_2026-08-23.csv"'
    )
    assert response.body.decode() == "Technician,2026-08-17,2026-08-18,2026-08-19,2026-08-20,2026-08-21,2026-08-22,2026-08-23,Total\r\nCrew total,0:00,0:00,0:00,0:00,0:00,0:00,0:00,0:00\r\n"


def test_graphs_route_passes_the_guided_range_and_serializes(monkeypatch):
    captured = {}
    payload = SimpleNamespace(
        generated_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        weeks=26,
        statuses=[],
        priority_high=SimpleNamespace(key="high", label="High priority", total=0, counts={}),
        priority_medium=SimpleNamespace(key="medium", label="Medium priority", total=0, counts={}),
        communities=[],
        service_types=[],
        duration=SimpleNamespace(
            range=SimpleNamespace(start=date(2026, 2, 23), end=date(2026, 8, 23)),
            buckets=[],
        ),
    )
    def graphs_hub(db, user, *, weeks):
        captured["weeks"] = weeks
        return payload

    monkeypatch.setattr(hub_router.hub_service, "graphs_hub", graphs_hub)

    body = hub_router.get_hub_graphs(weeks=26, user=SimpleNamespace(), db=None).model_dump()

    assert captured["weeks"] == 26
    assert body["duration"]["range"]["start"] == date(2026, 2, 23)


def test_graphs_route_serializes_the_two_priority_distributions(monkeypatch):
    payload = SimpleNamespace(
        generated_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        weeks=12,
        statuses=[],
        priority_high=SimpleNamespace(key="high", label="High priority", total=3, counts={"created": 3}),
        priority_medium=SimpleNamespace(key="medium", label="Medium priority", total=1, counts={"created": 1}),
        communities=[],
        service_types=[],
        duration=SimpleNamespace(
            range=SimpleNamespace(start=date(2026, 2, 23), end=date(2026, 8, 23)),
            buckets=[],
        ),
    )
    monkeypatch.setattr(hub_router.hub_service, "graphs_hub", lambda db, user, *, weeks: payload)

    body = hub_router.get_hub_graphs(weeks=12, user=SimpleNamespace(), db=None).model_dump()

    assert body["priority_high"]["total"] == 3
    assert body["priority_medium"]["counts"]["created"] == 1


def test_graphs_route_rejects_an_unsupported_week_count():
    with pytest.raises(HTTPException) as exc_info:
        hub_router.get_hub_graphs(weeks=99, user=SimpleNamespace(), db=None)

    assert exc_info.value.status_code == 422
    assert "12, 26, or 52" in exc_info.value.detail


def test_graphs_route_accepts_the_default_week_count_over_real_http(db):
    """Regression guard for a framework-level bug: FastAPI 0.136 / Pydantic
    2.13 do not coerce a numeric query string into an int `Literal`, so
    `weeks: Literal[12, 26, 52] = Query(12)` 422s on every real request even
    for `?weeks=12`, the default. `test_graphs_route_passes_the_guided_range`
    above calls the handler function directly and never exercises FastAPI's
    query-string parsing, so it could not catch this. This test drives the
    route the way a browser does."""
    user = User(
        username="hub_graphs_http_user",
        first_name="Hub",
        last_name="Graphs",
        role="techfm_oa",
        password_hash=auth_service.hash_password("correct horse"),
    )
    db.add(user)
    db.flush()
    db.commit()
    token = auth_service.create_session(db, user)

    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            client.cookies.set("session", token)
            response = client.get("/hub/graphs?weeks=12")
    finally:
        del app.dependency_overrides[get_db]

    assert response.status_code == 200
    assert response.json()["weeks"] == 12
