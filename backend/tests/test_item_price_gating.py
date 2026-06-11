"""Tests for `routers/items._item_response` -- the authoritative gate
that hides cost-sensitive `price` / `product_link` from anyone below
Admin.

Pure, no DB: we feed the helper a plain object with the same attributes
a SQLAlchemy `Item` would expose (`ItemResponse.model_validate` reads
them via `from_attributes`). The rule under test: Admin/Owner see the
values; Supervisor/Technician get `None`.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.domain import roles
from app.routers.items import _item_response


def _fake_item():
    return SimpleNamespace(
        id=uuid.uuid4(),
        barcode="012345678905",
        name="Widget",
        quantity=Decimal("7"),
        location="Bay 1",
        notes={},
        alt_barcodes=[],
        price=Decimal("12.50"),
        product_link="https://example.com/widget",
        created_at=datetime.now(timezone.utc),
    )


def test_owner_sees_price_and_link():
    resp = _item_response(_fake_item(), roles.ROLE_OWNER)
    assert resp.price == Decimal("12.50")
    assert resp.product_link == "https://example.com/widget"


def test_admin_sees_price_and_link():
    resp = _item_response(_fake_item(), roles.ROLE_ADMIN)
    assert resp.price == Decimal("12.50")
    assert resp.product_link == "https://example.com/widget"


def test_supervisor_does_not_see_price_or_link():
    resp = _item_response(_fake_item(), roles.ROLE_SUPERVISOR)
    assert resp.price is None
    assert resp.product_link is None
    # Non-sensitive fields are untouched.
    assert resp.name == "Widget"
    assert resp.quantity == Decimal("7")


def test_technician_does_not_see_price_or_link():
    resp = _item_response(_fake_item(), roles.ROLE_TECHNICIAN)
    assert resp.price is None
    assert resp.product_link is None
