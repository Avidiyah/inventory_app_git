"""Tests for `app.domain.billing.validate_billable_quantity` -- the pure
rule that guards an Admin's billable-quantity override before the service
persists it.

Pure, no DB (consistent with the rest of this suite). The rule: clearing
(None) always passes; only stock/dispense rows may be overridden; the
override must be in [0, recorded quantity].
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

import pytest

from app.domain.billing import validate_billable_quantity
from app.domain.errors import BillingQuantityError


def test_none_clears_override_and_passes():
    # Clearing is valid regardless of type (even on an adjust row).
    assert validate_billable_quantity("dispense", Decimal("5"), None) is None
    assert validate_billable_quantity("adjust", Decimal("-3"), None) is None


def test_zero_is_allowed_record_but_do_not_charge():
    assert validate_billable_quantity("dispense", Decimal("5"), Decimal("0")) == Decimal("0")


def test_partial_count_is_allowed():
    assert validate_billable_quantity("dispense", Decimal("5"), Decimal("2")) == Decimal("2")


def test_full_count_is_allowed():
    assert validate_billable_quantity("stock", Decimal("5"), Decimal("5")) == Decimal("5")


def test_negative_override_rejected():
    with pytest.raises(BillingQuantityError):
        validate_billable_quantity("dispense", Decimal("5"), Decimal("-1"))


def test_override_exceeding_quantity_rejected():
    with pytest.raises(BillingQuantityError):
        validate_billable_quantity("dispense", Decimal("5"), Decimal("6"))


def test_adjust_row_cannot_be_billed():
    with pytest.raises(BillingQuantityError):
        validate_billable_quantity("adjust", Decimal("5"), Decimal("1"))


def test_unknown_type_cannot_be_billed():
    with pytest.raises(BillingQuantityError):
        validate_billable_quantity("mystery", Decimal("5"), Decimal("1"))
