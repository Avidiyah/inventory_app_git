"""Performance score rules: which days count, and how counted days become
one ranked number. Pure; no database."""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.domain import performance as perf

NOW = datetime(2026, 10, 29, 20, 0, tzinfo=timezone.utc)


def punch(end_source="manual", needs_review=False, crosses_midnight=False):
    return SimpleNamespace(end_source=end_source, needs_review=needs_review,
                           crosses_midnight=crosses_midnight)


def session(hours=4, auto_closed=False, needs_review=False, running=False):
    start = NOW - timedelta(hours=hours)
    return SimpleNamespace(started_at=start, ended_at=None if running else NOW,
                           auto_closed=auto_closed, needs_review=needs_review)


def exclusions(**kw):
    args = dict(punches=[punch()], timeline=[session()], clocked_minutes=480,
                charged_minutes=240, outside_shift_minutes=0, now=NOW)
    args.update(kw)
    return perf.day_exclusions(**args)


def test_clean_day_has_no_exclusions():
    assert exclusions() == []


@pytest.mark.parametrize("kw, code", [
    ({"punches": [punch(end_source="auto_clock_out")]}, perf.PUNCH_ESTIMATED),
    ({"punches": [punch(end_source="self_reported")]}, perf.PUNCH_ESTIMATED),
    ({"punches": [punch(needs_review=True)]}, perf.PUNCH_ESTIMATED),
    ({"punches": [punch(crosses_midnight=True)]}, perf.PUNCH_ESTIMATED),
    ({"timeline": [session(auto_closed=True)]}, perf.SESSION_AUTO_CLOSED),
    ({"timeline": [session(running=True, needs_review=True)]}, perf.SESSION_AUTO_CLOSED),
    ({"timeline": [session(hours=13)]}, perf.SESSION_OVER_CAP),
    ({"outside_shift_minutes": 6}, perf.CHARGED_OFF_SHIFT),
    ({"charged_minutes": 481}, perf.CHARGED_OVER_CLOCKED),
])
def test_day_exclusions_each_reason(kw, code):
    assert exclusions(**kw) == [code]


def test_five_minutes_off_shift_is_grace():
    assert exclusions(outside_shift_minutes=5) == []


def test_reviewed_estimate_is_still_an_estimate():
    # Review clears the flag; the time is still a guess (spec D4).
    assert exclusions(punches=[punch(end_source="auto_clock_out", needs_review=False)]) == [perf.PUNCH_ESTIMATED]
    assert exclusions(timeline=[session(auto_closed=True, needs_review=False)]) == [perf.SESSION_AUTO_CLOSED]


def test_every_reason_has_a_label():
    assert set(perf.REASON_LABELS) == {
        perf.PUNCH_ESTIMATED, perf.SESSION_AUTO_CLOSED, perf.SESSION_OVER_CAP,
        perf.CHARGED_OFF_SHIFT, perf.CHARGED_OVER_CLOCKED}


def person(clocked=2400, sessions=0, adjust=0, billed="0", counted=5, active=5):
    return perf.PersonInput(
        user_id=uuid.uuid4(), clocked_minutes=clocked, session_minutes=sessions,
        adjustment_minutes=adjust, billed_dollars=Decimal(billed),
        counted_days=counted, active_days=active, day_reasons={}, excluded_orders=[])


def test_score_rows_weights_and_scaling():
    ann = person(clocked=1000, sessions=800, adjust=100, billed="1000", counted=5, active=5)
    bo = person(clocked=1000, sessions=1000, adjust=0, billed="500", counted=2, active=4)
    rows = perf.score_rows([bo, ann], window="week")
    a, b = rows
    assert a.user_id == ann.user_id and a.rank == 1 and b.rank == 2
    assert a.raw == {"billed": Decimal("1000"), "efficiency": 90, "accuracy": 80, "clean_days": 100}
    assert a.scaled == {"billed": 100, "efficiency": 90, "accuracy": 80, "clean_days": 100}
    assert a.score == 94  # 40 + 22.5 + 16 + 15 = 93.5, half-even
    assert b.scaled == {"billed": 50, "efficiency": 100, "accuracy": 100, "clean_days": 50}
    assert b.score == 72  # 20 + 25 + 20 + 7.5 = 72.5, half-even


def test_percent_caps_at_100():
    row = perf.score_rows([person(clocked=100, sessions=150)], window="week")[0]
    assert row.raw["accuracy"] == 100 and row.raw["efficiency"] == 100


def test_score_rows_floor():
    below = perf.score_rows([person(clocked=15 * 60)], window="week")[0]
    assert below.rank is None and below.below_floor
    at = perf.score_rows([person(clocked=16 * 60)], window="week")[0]
    assert at.rank == 1 and not at.below_floor
    month = perf.score_rows([person(clocked=59 * 60)], window="month")[0]
    assert month.rank is None


def test_floor_rows_follow_ranked_rows_and_scale_against_the_eligible_best():
    ann = person(clocked=2400, billed="200")
    cy = person(clocked=300, billed="400")
    rows = perf.score_rows([cy, ann], window="week")
    assert [r.rank for r in rows] == [1, None]
    assert rows[0].scaled["billed"] == 100
    assert rows[1].scaled["billed"] == 200  # above the eligible best, still shown honestly


def test_score_rows_zero_clocked_is_unranked():
    row = perf.score_rows([person(clocked=0, sessions=60, counted=0, active=1)], window="week")[0]
    assert row.raw["efficiency"] == 0 and row.raw["accuracy"] == 0 and row.raw["clean_days"] == 0
    assert row.rank is None


def test_score_rows_empty():
    assert perf.score_rows([], window="month") == []


def test_best_of_zero_scales_to_zero():
    row = perf.score_rows([person()], window="week")[0]
    assert row.scaled["billed"] == 0 and row.scaled["accuracy"] == 0


def test_score_rows_tie_breaks_on_billed_then_order():
    first = person(billed="100")
    second = person(billed="100")
    richer = person(billed="100.01")
    rows = perf.score_rows([first, second, richer], window="week")
    # Equal scores after scaling: richer wins on raw billed, then input order.
    assert rows[0].score == rows[1].score == rows[2].score
    assert [r.user_id for r in rows] == [richer.user_id, first.user_id, second.user_id]
