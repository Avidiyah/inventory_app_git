"""Router-boundary tests for the User Hub timesheet endpoints."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers import hub as hub_router
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
