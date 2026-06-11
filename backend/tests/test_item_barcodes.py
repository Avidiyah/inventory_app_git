"""Tests for the additional-barcodes feature (multiple barcodes per item).

Pure, no DB -- consistent with the rest of this suite. The DB-bound
behaviours (lookup resolving via an alternate code, the cross-table
uniqueness pre-check) are exercised through the manual verification flow,
since the suite has no database harness. What *is* unit-testable lives
here:

- `ItemBarcodesUpdate` payload normalisation (trim / drop blanks / reject
  in-list duplicates),
- `_item_response` flattening `item.alt_barcodes` into `barcodes: list[str]`
  (and not leaking the extra codes into the cost-sensitive redaction),
- the route gate on `PATCH /items/{id}/barcodes` (Admin+).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from app.domain import roles
from app.routers import items as items_router
from app.routers.items import _item_response
from app.schemas.items import ItemBarcodesUpdate


# --- ItemBarcodesUpdate normalisation ---------------------------------

def test_codes_are_trimmed():
    payload = ItemBarcodesUpdate(barcodes=["  abc  ", "def\t"])
    assert payload.barcodes == ["abc", "def"]


def test_blank_codes_are_dropped():
    payload = ItemBarcodesUpdate(barcodes=["abc", "   ", ""])
    assert payload.barcodes == ["abc"]


def test_empty_list_is_allowed():
    # Clearing all additional barcodes is a valid wholesale replace.
    assert ItemBarcodesUpdate(barcodes=[]).barcodes == []


def test_in_list_duplicate_is_rejected():
    with pytest.raises(ValidationError):
        ItemBarcodesUpdate(barcodes=["abc", "abc"])


def test_duplicate_only_after_trim_is_rejected():
    with pytest.raises(ValidationError):
        ItemBarcodesUpdate(barcodes=["abc", "  abc"])


# --- _item_response flattens alt_barcodes -----------------------------

def _fake_item(alt_codes):
    return SimpleNamespace(
        id=uuid.uuid4(),
        barcode="012345678905",
        name="Widget",
        quantity=Decimal("7"),
        location="Bay 1",
        notes={},
        alt_barcodes=[SimpleNamespace(code=c) for c in alt_codes],
        price=Decimal("12.50"),
        product_link="https://example.com/widget",
        created_at=datetime.now(timezone.utc),
    )


def test_response_flattens_alt_barcodes_to_strings():
    resp = _item_response(_fake_item(["AAA", "BBB"]), roles.ROLE_ADMIN)
    assert resp.barcode == "012345678905"
    assert resp.barcodes == ["AAA", "BBB"]


def test_response_barcodes_empty_when_no_alternates():
    resp = _item_response(_fake_item([]), roles.ROLE_TECHNICIAN)
    assert resp.barcodes == []


def test_alternate_barcodes_are_not_cost_sensitive():
    # A Technician still sees the additional barcodes (they are not
    # redacted like price/product_link) -- they need them to scan.
    resp = _item_response(_fake_item(["AAA"]), roles.ROLE_TECHNICIAN)
    assert resp.barcodes == ["AAA"]
    assert resp.price is None
    assert resp.product_link is None


# --- route gate -------------------------------------------------------

def _route(router, endpoint_name):
    for route in router.router.routes:
        if isinstance(route, APIRoute) and route.endpoint.__name__ == endpoint_name:
            return route
    raise AssertionError(f"route {endpoint_name!r} not found")


def _find_min_role(dependant):
    for sub in dependant.dependencies:
        call = getattr(sub, "call", None)
        closure = getattr(call, "__closure__", None) or ()
        freevars = call.__code__.co_freevars if call is not None else ()
        for name, cell in zip(freevars, closure):
            if name == "minimum" and isinstance(cell.cell_contents, str):
                return cell.cell_contents
        found = _find_min_role(sub)
        if found is not None:
            return found
    return None


def test_update_item_barcodes_requires_admin():
    # Same gate as the structural PATCH /items/{id} edit.
    route = _route(items_router, "update_item_barcodes")
    assert _find_min_role(route.dependant) == roles.ROLE_ADMIN
