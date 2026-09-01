"""The low-stock edge rule.

The state ("is it low") is trivial; the *edge* ("did this write make it
low") is the whole feature, and it is what stops a fast-moving item
pushing on every dispense while it sits below its threshold.

Because a threshold edit is a write with a before and an after, the same
function decides both a stock drop and a threshold raise. Each is pinned
here so a later refactor cannot quietly split them apart again.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

from app.domain import low_stock


def test_at_the_threshold_is_low():
    """`<=`, not `<`. Six with a threshold of six is the alerting case
    the whole feature was asked for."""
    assert low_stock.is_low(Decimal("6"), 6) is True


def test_above_the_threshold_is_not_low():
    assert low_stock.is_low(Decimal("7"), 6) is False


def test_a_negative_count_is_low():
    """Scan / Stock deliberately allows a dispense to drive the recorded
    count below zero and raises a recount request. That item is as low as
    an item can be."""
    assert low_stock.is_low(Decimal("-2"), 6) is True


def test_a_decimal_count_compares_against_a_whole_threshold():
    assert low_stock.is_low(Decimal("2.5"), 6) is True
    assert low_stock.is_low(Decimal("6.5"), 6) is False


def test_a_dispense_that_crosses_the_threshold_fires():
    assert low_stock.crossed_into_low(
        quantity_before=Decimal("7"), threshold_before=6,
        quantity_after=Decimal("6"), threshold_after=6,
    ) is True


def test_a_dispense_that_leaves_an_already_low_item_low_is_silent():
    """The noise case. Without this the crew gets a push per dispense for
    the rest of the item's life below its threshold."""
    assert low_stock.crossed_into_low(
        quantity_before=Decimal("5"), threshold_before=6,
        quantity_after=Decimal("4"), threshold_after=6,
    ) is False


def test_a_restock_back_above_the_threshold_does_not_fire():
    assert low_stock.crossed_into_low(
        quantity_before=Decimal("2"), threshold_before=6,
        quantity_after=Decimal("9"), threshold_after=6,
    ) is False


def test_raising_the_threshold_past_the_current_count_fires():
    """The retune case: nothing moved, but the item is newly low."""
    assert low_stock.crossed_into_low(
        quantity_before=Decimal("10"), threshold_before=6,
        quantity_after=Decimal("10"), threshold_after=20,
    ) is True


def test_lowering_the_threshold_below_the_current_count_does_not_fire():
    assert low_stock.crossed_into_low(
        quantity_before=Decimal("10"), threshold_before=20,
        quantity_after=Decimal("10"), threshold_after=6,
    ) is False


def test_membership_changes_in_both_directions():
    """The realtime predicate is wider than the push predicate: an item
    leaving the list must invalidate an open Low Stock page too."""
    assert low_stock.membership_changed(
        quantity_before=Decimal("2"), threshold_before=6,
        quantity_after=Decimal("9"), threshold_after=6,
    ) is True
    assert low_stock.membership_changed(
        quantity_before=Decimal("9"), threshold_before=6,
        quantity_after=Decimal("2"), threshold_after=6,
    ) is True


def test_membership_is_unchanged_when_a_low_item_stays_low():
    assert low_stock.membership_changed(
        quantity_before=Decimal("5"), threshold_before=6,
        quantity_after=Decimal("4"), threshold_after=6,
    ) is False
