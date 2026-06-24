"""Tests for `schemas.items.ItemUpdate` partial-update semantics.

Pure, no DB. These pin the two behaviours that close the long-standing
gaps in `docs/current-state.md`:

- A price-only (or product-link-only) PATCH is accepted — the old
  `_at_least_one_field` rule wrongly required barcode/name/location.
- An explicit `null` for the nullable `price` / `product_link` columns is
  carried through (so a stored value can be cleared), while an omitted
  field is simply not forwarded.

The router forwards `model_dump(exclude_unset=True)` to the service, so
each test asserts on that dict — it is exactly what the service receives.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.items import ItemUpdate


def _sent(**kwargs):
    """The payload the service actually receives for the given body."""
    return ItemUpdate(**kwargs).model_dump(exclude_unset=True)


def test_price_only_patch_is_accepted():
    assert _sent(price="5.50") == {"price": Decimal("5.50")}


def test_product_link_only_patch_is_accepted():
    assert _sent(product_link="https://example.com/x") == {
        "product_link": "https://example.com/x"
    }


def test_explicit_null_clears_price():
    # Present-and-null reaches the service so it can clear the column.
    assert _sent(price=None) == {"price": None}


def test_explicit_null_clears_product_link():
    assert _sent(product_link=None) == {"product_link": None}


def test_omitted_field_is_not_forwarded():
    # Only the field actually sent is in the dump; price is left untouched.
    assert _sent(name="Widget") == {"name": "Widget"}


def test_text_fields_are_trimmed():
    assert _sent(name="  Widget  ") == {"name": "Widget"}


def test_empty_body_is_rejected():
    with pytest.raises(ValidationError):
        ItemUpdate()


@pytest.mark.parametrize("field", ["barcode", "name", "location"])
def test_explicit_null_rejected_for_not_null_columns(field):
    with pytest.raises(ValidationError):
        ItemUpdate(**{field: None})


@pytest.mark.parametrize("field", ["barcode", "name", "location"])
def test_blank_rejected_for_not_null_columns(field):
    with pytest.raises(ValidationError):
        ItemUpdate(**{field: "   "})
