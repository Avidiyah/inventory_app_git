"""Tests for `app.domain.quantity.reverse_delta` -- the pure arithmetic
that undoes a transaction when it is voided.

No DB, no HTTP -- consistent with the rest of the suite. Reversal is the
inverse of `apply_delta`:

- undo `stock`   -> subtract the stocked amount (and never go negative),
- undo `dispense`-> add the dispensed amount back,
- undo `adjust`  -> apply the negated signed delta.

The negative guard matters: voiding a stock-in whose units have since
been dispensed must raise rather than silently produce negative stock.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

import pytest

from app.domain.errors import NegativeQuantityError
from app.domain.quantity import reverse_delta


def test_reverse_stock_subtracts():
    # A stock-in of 5 added 5; undoing it removes them again.
    assert reverse_delta(Decimal("12"), "stock", Decimal("5")) == Decimal("7")


def test_reverse_dispense_adds_back():
    # A dispense of 5 removed 5; undoing it returns them to stock.
    assert reverse_delta(Decimal("3"), "dispense", Decimal("5")) == Decimal("8")


def test_reverse_adjust_up_subtracts_the_delta():
    # An adjust that raised stock by +4 is undone by removing 4.
    assert reverse_delta(Decimal("10"), "adjust", Decimal("4")) == Decimal("6")


def test_reverse_adjust_down_adds_the_delta_back():
    # An adjust that lowered stock by -4 (stored as -4) is undone by +4.
    assert reverse_delta(Decimal("6"), "adjust", Decimal("-4")) == Decimal("10")


def test_reverse_stock_that_would_go_negative_raises():
    # Voiding a stock-in of 5 when only 2 remain (the rest dispensed)
    # would drive stock below zero -- must raise, not produce -3.
    with pytest.raises(NegativeQuantityError):
        reverse_delta(Decimal("2"), "stock", Decimal("5"))


def test_reverse_adjust_up_that_would_go_negative_raises():
    with pytest.raises(NegativeQuantityError):
        reverse_delta(Decimal("1"), "adjust", Decimal("5"))


def test_reverse_dispense_never_raises_even_from_zero():
    # Undoing a dispense only adds stock, so it can never overdraw.
    assert reverse_delta(Decimal("0"), "dispense", Decimal("9")) == Decimal("9")
