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
