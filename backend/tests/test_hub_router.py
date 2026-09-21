"""Router-boundary tests for the User Hub reporting endpoints."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import openpyxl
import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.database import get_db
from app.domain import work_orders as wo
from app.main import app
from app.models import User
from app.routers import hub as hub_router
from app.services import auth as auth_service
from app.services import hub as hub_service
from app.services import work_order_report_xlsx as report_xlsx


def test_graphs_route_passes_the_guided_range_and_serializes(monkeypatch):
    captured = {}
    payload = SimpleNamespace(
        generated_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        weeks=26,
        statuses=[],
        communities=[],
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


def test_graphs_route_serializes_the_nested_community_shape(monkeypatch):
    payload = SimpleNamespace(
        generated_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        weeks=12,
        statuses=[],
        communities=[
            SimpleNamespace(
                key="commons",
                label="Commons",
                total=4,
                counts={"created": 4},
                service_types=[
                    SimpleNamespace(key="hvac", label="HVAC", total=3, counts={"created": 3})
                ],
                priorities=[
                    SimpleNamespace(key="high", label="High", total=1, counts={"created": 1})
                ],
            )
        ],
        duration=SimpleNamespace(
            range=SimpleNamespace(start=date(2026, 2, 23), end=date(2026, 8, 23)),
            buckets=[],
        ),
    )
    monkeypatch.setattr(hub_router.hub_service, "graphs_hub", lambda db, user, *, weeks: payload)

    body = hub_router.get_hub_graphs(weeks=12, user=SimpleNamespace(), db=None).model_dump()

    community = body["communities"][0]
    assert community["total"] == 4
    assert community["service_types"][0]["label"] == "HVAC"
    assert community["priorities"][0]["counts"]["created"] == 1
    # The three flat cross-sections the nested shape replaced are gone.
    assert "priority_high" not in body
    assert "priority_medium" not in body
    assert "service_types" not in body


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
    body = response.json()
    assert body["weeks"] == 12
    # The nested shape survives real serialization, not just a direct
    # handler call: five communities, each carrying its own two inner grids.
    assert [row["key"] for row in body["communities"]] == list(wo.ALL_COMMUNITY_FILTERS)
    assert all(
        isinstance(row["service_types"], list) and isinstance(row["priorities"], list)
        for row in body["communities"]
    )


# --- the Admin daily report (2026-08-30-work-order-daily-report-design) -----


def _signed_in(db, role):
    user = User(
        username=f"report_{role}_{uuid.uuid4().hex[:8]}",
        first_name="Report",
        last_name=role.title(),
        role=role,
        password_hash=auth_service.hash_password("correct horse"),
    )
    db.add(user)
    db.flush()
    db.commit()
    return auth_service.create_session(db, user)


def _get(db, token, path):
    """Drive the route the way a browser does -- through FastAPI's own gate,
    not by calling the handler, which would skip the role dependency."""
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            client.cookies.set("session", token)
            return client.get(path)
    finally:
        del app.dependency_overrides[get_db]


def test_admin_weekly_report_body_shape(db):
    response = _get(db, _signed_in(db, "admin"), "/hub/report")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "week_start",
        "week_end",
        "status",
        "generated_at",
        "frozen_at",
        "count",
        "rows",
        "new_work_order_count",
        "new_work_order_rows",
    }
    assert body["status"] == "in_progress"
    assert body["frozen_at"] is None
    assert date.fromisoformat(body["week_start"]).weekday() == 0
    assert body["count"] == len(body["rows"])
    assert body["new_work_order_count"] == len(body["new_work_order_rows"])


@pytest.mark.parametrize("path", ["/hub/report", "/hub/report/export"])
def test_a_non_monday_week_is_422_on_both_routes(db, path):
    response = _get(db, _signed_in(db, "admin"), f"{path}?week=2026-09-08")

    assert response.status_code == 422
    assert "Monday" in response.json()["detail"]


def test_a_past_monday_serves_a_completed_week(db):
    # 1999: no real row can fall into it, and the freeze row is cleaned up.
    from app.models import WorkOrderReportWeek

    week = date(1999, 2, 1)
    db.query(WorkOrderReportWeek).filter_by(week_start=week).delete()
    db.commit()
    try:
        body = _get(db, _signed_in(db, "admin"), f"/hub/report?week={week}").json()

        assert body["status"] == "completed"
        assert body["frozen_at"] is not None
        assert body["week_start"] == "1999-02-01"
        assert body["week_end"] == "1999-02-07"
    finally:
        db.query(WorkOrderReportWeek).filter_by(week_start=week).delete()
        db.commit()


@pytest.mark.parametrize("path", ["/hub/report", "/hub/report/export"])
def test_techfm_oa_is_forbidden_from_the_report(db, path):
    response = _get(db, _signed_in(db, "techfm_oa"), path)

    assert response.status_code == 403


def test_report_export_is_an_attachment_xlsx_named_for_the_monday(db):
    response = _get(db, _signed_in(db, "admin"), "/hub/report/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == report_xlsx.XLSX_MEDIA_TYPE
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    monday = date.fromisoformat(response.headers["content-disposition"].split("wo-report_")[1][:10])
    assert monday.weekday() == 0
    assert disposition.endswith('.xlsx"')

    workbook = openpyxl.load_workbook(io.BytesIO(response.content))
    assert workbook.sheetnames[-1] == report_xlsx.NEW_WORK_ORDERS_SHEET


def test_the_timesheet_routes_are_gone():
    """D6: `GET /hub/timesheets` retired in P4b, subsumed by the Admin
    comparison sub-tab, at the accepted cost that a Supervisor loses the tab.
    Re-adding the path would silently restore a second, sweeping, answer to
    "how many hours" beside the pay record."""
    from app.main import app as fastapi_app

    paths = {route.path for route in fastapi_app.routes if isinstance(route, APIRoute)}
    assert "/hub/timesheets" not in paths
    assert "/hub/timesheets/export" not in paths
