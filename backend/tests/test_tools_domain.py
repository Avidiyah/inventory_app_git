"""Tests for `app.domain.tools.validate_return` -- the pure rule that
guards a tool return before the service applies it.

Pure, no DB (consistent with the rest of this suite). The rule: a return
may never exceed what's currently outstanding for that (tool, user) pair.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

import pytest

from app.domain.errors import ToolReturnExceedsCheckedOutError
from app.domain.tools import validate_return


def test_return_under_outstanding_passes():
    validate_return(Decimal("5"), Decimal("2"))  # no raise


def test_return_equal_to_outstanding_passes():
    validate_return(Decimal("5"), Decimal("5"))  # no raise


def test_return_over_outstanding_rejected():
    with pytest.raises(ToolReturnExceedsCheckedOutError) as exc_info:
        validate_return(Decimal("5"), Decimal("6"))
    assert exc_info.value.requested == Decimal("6")
    assert exc_info.value.outstanding == Decimal("5")


def test_return_against_zero_outstanding_rejected():
    with pytest.raises(ToolReturnExceedsCheckedOutError):
        validate_return(Decimal("0"), Decimal("1"))


# --- custody spell start -------------------------------------------------

from datetime import datetime, timezone

from app.domain import tools as tools_domain


def _t(hour):
    return datetime(2026, 8, 20, hour, 0, tzinfo=timezone.utc)


def test_custody_since_is_the_checkout_that_opened_the_current_spell():
    # Returned on Tuesday, taken out again on Wednesday: "since" is Wednesday.
    events = [
        ("checkout", Decimal("1"), _t(8)),
        ("return", Decimal("1"), _t(10)),
        ("checkout", Decimal("2"), _t(12)),
    ]
    assert tools_domain.custody_since(events) == _t(12)


def test_custody_since_survives_a_partial_return():
    # Still holding one of the two, so the spell never broke.
    events = [
        ("checkout", Decimal("2"), _t(8)),
        ("return", Decimal("1"), _t(10)),
    ]
    assert tools_domain.custody_since(events) == _t(8)


def test_custody_since_is_none_when_everything_came_back():
    events = [
        ("checkout", Decimal("1"), _t(8)),
        ("return", Decimal("1"), _t(10)),
    ]
    assert tools_domain.custody_since(events) is None


def test_custody_since_ignores_adjust_rows():
    # Correct Count has no custody holder and must not open or close a spell.
    events = [
        ("adjust", Decimal("-3"), _t(7)),
        ("checkout", Decimal("1"), _t(8)),
    ]
    assert tools_domain.custody_since(events) == _t(8)


def test_custody_since_of_nothing_is_none():
    assert tools_domain.custody_since([]) is None
