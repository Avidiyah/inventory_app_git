"""The frozen-week table behind the weekly closed report.

Spec: docs/superpowers/specs/2026-09-13-weekly-closed-report-design.md §4.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.errors import DomainError, ReportWeekError
from app.models import WorkOrderReportWeek
from app.routers._errors import to_http

# A Monday no real week can collide with.
WEEK = date(1999, 1, 4)


def test_a_frozen_week_reads_back_with_a_server_stamped_frozen_at(db):
    db.query(WorkOrderReportWeek).filter_by(week_start=WEEK).delete()
    db.commit()

    db.add(WorkOrderReportWeek(week_start=WEEK, schema_version=1, payload={"a": 1}))
    db.commit()

    stored = db.get(WorkOrderReportWeek, WEEK)
    assert stored.payload == {"a": 1}
    assert stored.schema_version == 1
    assert stored.frozen_at is not None
    assert stored.frozen_at.tzinfo is not None

    db.delete(stored)
    db.commit()


def test_a_week_can_be_frozen_only_once(db):
    db.query(WorkOrderReportWeek).filter_by(week_start=WEEK).delete()
    db.commit()
    db.add(WorkOrderReportWeek(week_start=WEEK, schema_version=1, payload={}))
    db.commit()

    db.add(WorkOrderReportWeek(week_start=WEEK, schema_version=1, payload={}))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.query(WorkOrderReportWeek).filter_by(week_start=WEEK).delete()
    db.commit()


def test_report_week_error_is_a_422_domain_error():
    exc = ReportWeekError("week must be a Monday (YYYY-MM-DD).")

    assert isinstance(exc, DomainError)
    http = to_http(exc)
    assert http.status_code == 422
    assert http.detail == "week must be a Monday (YYYY-MM-DD)."
