"""The performance score: which of a person's days count, and how the counted
days become one ranked number (spec 2026-10-29).

Layer: domain. Pure. Every constant the Leaderboards tab reports lives here
and nowhere else, so the weights the UI prints and the weights the score uses
cannot drift apart.

The trust rule (D4): an estimate stays out until someone keys the real time.
Reviewing clears a warning; it never re-admits a day. So the tests here look
at `end_source` and `auto_closed`, not at `needs_review` alone.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Optional

from app.domain.attendance import END_SOURCE_ADMIN_EDIT, END_SOURCE_MANUAL, END_SOURCE_SELF_EDIT
from app.domain.labor_day import as_utc
from app.domain.work_orders import LABOR_SESSION_MAX_MINUTES

WEIGHTS: dict[str, int] = {"billed": 40, "efficiency": 25, "accuracy": 20, "clean_days": 15}
FLOOR_MINUTES: dict[str, int] = {"week": 16 * 60, "month": 60 * 60}
OUTSIDE_SHIFT_GRACE_MINUTES = 5

# Why a day is left out, in display order.
PUNCH_ESTIMATED = "punch_estimated"
SESSION_AUTO_CLOSED = "session_auto_closed"
SESSION_OVER_CAP = "session_over_cap"
CHARGED_OFF_SHIFT = "charged_off_shift"
CHARGED_OVER_CLOCKED = "charged_over_clocked"

REASON_LABELS: dict[str, str] = {
    PUNCH_ESTIMATED: "forgotten clock-out",
    SESSION_AUTO_CLOSED: "job clock auto-closed",
    SESSION_OVER_CAP: "job clock over 12 h",
    CHARGED_OFF_SHIFT: "charged off shift",
    CHARGED_OVER_CLOCKED: "charged more than clocked",
}

_REAL_END_SOURCES = {END_SOURCE_MANUAL, END_SOURCE_ADMIN_EDIT, END_SOURCE_SELF_EDIT}


def punch_is_estimate(punch) -> bool:
    """A punch whose end nobody set by hand, or that is still flagged."""
    if punch.needs_review or getattr(punch, "crosses_midnight", False):
        return True
    end_source = getattr(punch, "end_source", None)
    return end_source is not None and end_source not in _REAL_END_SOURCES


def session_is_auto_closed(entry) -> bool:
    """The cap closed it (reviewed or not), or it is running past the cap."""
    return bool(getattr(entry, "auto_closed", False)) or (
        entry.ended_at is None and bool(getattr(entry, "needs_review", False)))


def session_is_over_cap(entry) -> bool:
    """A closed span longer than the cap: recorded history, but not trusted."""
    if entry.ended_at is None:
        return False
    span = as_utc(entry.ended_at) - as_utc(entry.started_at)
    return span > timedelta(minutes=LABOR_SESSION_MAX_MINUTES)


def day_exclusions(*, punches, timeline, clocked_minutes: int, charged_minutes: int,
                   outside_shift_minutes: int, now: datetime) -> list[str]:
    """Every reason this day is left out, in display order; empty = counted."""
    reasons: list[str] = []
    if any(punch_is_estimate(p) for p in punches):
        reasons.append(PUNCH_ESTIMATED)
    if any(session_is_auto_closed(e) for e in timeline):
        reasons.append(SESSION_AUTO_CLOSED)
    if any(session_is_over_cap(e) for e in timeline):
        reasons.append(SESSION_OVER_CAP)
    if outside_shift_minutes > OUTSIDE_SHIFT_GRACE_MINUTES:
        reasons.append(CHARGED_OFF_SHIFT)
    if charged_minutes > clocked_minutes:
        reasons.append(CHARGED_OVER_CLOCKED)
    return reasons


@dataclass(frozen=True)
class PersonInput:
    user_id: uuid.UUID
    clocked_minutes: int
    session_minutes: int
    adjustment_minutes: int
    billed_dollars: Decimal
    counted_days: int
    active_days: int
    day_reasons: dict[str, int] = field(default_factory=dict)
    excluded_orders: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class PersonScore:
    user_id: uuid.UUID
    raw: dict
    scaled: dict[str, int]
    score: int
    rank: Optional[int]
    below_floor: bool
    clocked_minutes: int
    counted_days: int
    active_days: int
    day_reasons: dict[str, int]
    excluded_orders: list[tuple[str, str]]


def _round(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def _pct(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return min(100, _round(Decimal(numerator) * 100 / Decimal(denominator)))


def _raw(person: PersonInput) -> dict:
    return {
        "billed": person.billed_dollars,
        "efficiency": _pct(person.session_minutes + person.adjustment_minutes, person.clocked_minutes),
        "accuracy": _pct(person.session_minutes, person.clocked_minutes),
        "clean_days": _pct(person.counted_days, person.active_days),
    }


def score_rows(people: list[PersonInput], *, window: str) -> list[PersonScore]:
    """Ranked rows first, then the people under the floor with no rank.

    Every component is scaled against the best **eligible** value, so the
    best ranked person scores 100 on it; a short week above that best shows
    its honest figure but takes no rank.
    """
    floor = FLOOR_MINUTES[window]
    raws = [(p, _raw(p)) for p in people]
    eligible = [raw for p, raw in raws if p.clocked_minutes >= floor]
    best = {
        key: max((Decimal(raw[key]) for raw in eligible), default=Decimal(0))
        for key in WEIGHTS
    }

    def scale(raw: dict) -> dict[str, int]:
        return {
            key: (_round(Decimal(raw[key]) * 100 / best[key]) if best[key] else 0)
            for key in WEIGHTS
        }

    scored = []
    for index, (person, raw) in enumerate(raws):
        scaled = scale(raw)
        score = _round(sum(Decimal(scaled[key] * weight) for key, weight in WEIGHTS.items()) / 100)
        scored.append((person, raw, scaled, score, index))

    ranked = sorted(
        (row for row in scored if row[0].clocked_minutes >= floor),
        key=lambda row: (-row[3], -row[1]["billed"], row[4]),
    )
    unranked = [row for row in scored if row[0].clocked_minutes < floor]

    def build(row, rank: Optional[int]) -> PersonScore:
        person, raw, scaled, score, _ = row
        return PersonScore(
            user_id=person.user_id, raw=raw, scaled=scaled, score=score, rank=rank,
            below_floor=rank is None, clocked_minutes=person.clocked_minutes,
            counted_days=person.counted_days, active_days=person.active_days,
            day_reasons=dict(person.day_reasons), excluded_orders=list(person.excluded_orders),
        )

    return [build(row, i + 1) for i, row in enumerate(ranked)] + [build(row, None) for row in unranked]
