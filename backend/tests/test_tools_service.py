"""Database integration tests for `app.services.tools`.

Covers: create/duplicate-barcode, checkout/return round-trip, the
NegativeQuantityError overdraft guard on checkout, the
ToolReturnExceedsCheckedOutError cap on return, multi-user custody
aggregation for a bulk (quantity > 1) tool, and archive hiding a tool from
`list_tools`. Skip if no DB (see `conftest.py`).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from decimal import Decimal

import pytest

from app.domain.errors import (
    DuplicateToolBarcodeError,
    NegativeQuantityError,
    NoChangeError,
    ToolNotFoundError,
    ToolReturnExceedsCheckedOutError,
)
from app.models import User
from app.services import auth
from app.services import tools as tools_service


def _seed_user(db, role="technician"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _seed_tool(db, quantity=5):
    return tools_service.create_tool(
        db,
        barcode=f"TOOL-{uuid.uuid4().hex[:10]}",
        name="Cordless Drill",
        quantity=Decimal(quantity),
    )


def test_create_tool_rejects_live_duplicate_barcode(db):
    tool = _seed_tool(db)
    with pytest.raises(DuplicateToolBarcodeError):
        tools_service.create_tool(
            db, barcode=tool.barcode, name="Another Drill", quantity=Decimal(1)
        )


def test_archived_tool_barcode_is_reusable(db):
    tool = _seed_tool(db)
    tools_service.delete_tool(db, tool.id)
    # No conflict/override dance -- an archived tool's barcode is just free.
    new_tool = tools_service.create_tool(
        db, barcode=tool.barcode, name="Replacement Drill", quantity=Decimal(1)
    )
    assert new_tool.barcode == tool.barcode
    assert new_tool.id != tool.id


def test_checkout_decrements_quantity_and_creates_custody(db):
    tool = _seed_tool(db, quantity=5)
    user = _seed_user(db)
    admin = _seed_user(db, role="admin")

    tools_service.checkout_tool(
        db,
        tool.id,
        quantity=Decimal(2),
        assigned_to_id=user.id,
        performed_by_id=admin.id,
    )

    refreshed = tools_service.get_tool(db, tool.id)
    assert refreshed.quantity == Decimal(3)

    custody = tools_service.tool_custody(db, tool.id)
    assert custody == [(user.id, user.username, Decimal(2))]


def test_checkout_beyond_on_hand_raises_negative_quantity(db):
    tool = _seed_tool(db, quantity=1)
    user = _seed_user(db)

    with pytest.raises(NegativeQuantityError):
        tools_service.checkout_tool(
            db,
            tool.id,
            quantity=Decimal(2),
            assigned_to_id=user.id,
            performed_by_id=None,
        )


def test_return_increments_quantity_and_reduces_custody(db):
    tool = _seed_tool(db, quantity=5)
    user = _seed_user(db)

    tools_service.checkout_tool(
        db, tool.id, quantity=Decimal(3), assigned_to_id=user.id, performed_by_id=None
    )
    tools_service.return_tool(
        db, tool.id, quantity=Decimal(2), assigned_to_id=user.id, performed_by_id=None
    )

    refreshed = tools_service.get_tool(db, tool.id)
    assert refreshed.quantity == Decimal(4)  # 5 - 3 + 2

    custody = tools_service.tool_custody(db, tool.id)
    assert custody == [(user.id, user.username, Decimal(1))]


def test_full_return_clears_custody_entry(db):
    tool = _seed_tool(db, quantity=5)
    user = _seed_user(db)

    tools_service.checkout_tool(
        db, tool.id, quantity=Decimal(3), assigned_to_id=user.id, performed_by_id=None
    )
    tools_service.return_tool(
        db, tool.id, quantity=Decimal(3), assigned_to_id=user.id, performed_by_id=None
    )

    assert tools_service.tool_custody(db, tool.id) == []


def test_return_beyond_outstanding_rejected(db):
    tool = _seed_tool(db, quantity=5)
    user = _seed_user(db)

    tools_service.checkout_tool(
        db, tool.id, quantity=Decimal(2), assigned_to_id=user.id, performed_by_id=None
    )
    with pytest.raises(ToolReturnExceedsCheckedOutError):
        tools_service.return_tool(
            db,
            tool.id,
            quantity=Decimal(3),
            assigned_to_id=user.id,
            performed_by_id=None,
        )


def test_return_with_no_checkout_rejected(db):
    tool = _seed_tool(db, quantity=5)
    user = _seed_user(db)

    with pytest.raises(ToolReturnExceedsCheckedOutError):
        tools_service.return_tool(
            db,
            tool.id,
            quantity=Decimal(1),
            assigned_to_id=user.id,
            performed_by_id=None,
        )


def test_bulk_tool_custody_splits_across_multiple_users(db):
    tool = _seed_tool(db, quantity=5)
    alice = _seed_user(db)
    bob = _seed_user(db)

    tools_service.checkout_tool(
        db, tool.id, quantity=Decimal(3), assigned_to_id=alice.id, performed_by_id=None
    )
    tools_service.checkout_tool(
        db, tool.id, quantity=Decimal(2), assigned_to_id=bob.id, performed_by_id=None
    )

    refreshed = tools_service.get_tool(db, tool.id)
    assert refreshed.quantity == Decimal(0)

    custody = {uid: qty for uid, _uname, qty in tools_service.tool_custody(db, tool.id)}
    assert custody[alice.id] == Decimal(3)
    assert custody[bob.id] == Decimal(2)

    # Alice returning her 3 doesn't touch Bob's outstanding balance.
    tools_service.return_tool(
        db, tool.id, quantity=Decimal(3), assigned_to_id=alice.id, performed_by_id=None
    )
    custody_after = {
        uid: qty for uid, _uname, qty in tools_service.tool_custody(db, tool.id)
    }
    assert alice.id not in custody_after
    assert custody_after[bob.id] == Decimal(2)


def test_archive_hides_tool_from_list(db):
    tool = _seed_tool(db)
    before = {t.id for t in tools_service.list_tools(db)}
    assert tool.id in before

    tools_service.delete_tool(db, tool.id)

    after = {t.id for t in tools_service.list_tools(db)}
    assert tool.id not in after


def test_checkout_unknown_tool_raises_not_found(db):
    user = _seed_user(db)
    with pytest.raises(ToolNotFoundError):
        tools_service.checkout_tool(
            db,
            uuid.uuid4(),
            quantity=Decimal(1),
            assigned_to_id=user.id,
            performed_by_id=None,
        )


# --- adjust_tool_quantity ("Correct Count") -------------------------------

def test_adjust_increases_quantity(db):
    tool = _seed_tool(db, quantity=5)
    admin = _seed_user(db, role="admin")

    tools_service.adjust_tool_quantity(
        db, tool.id, new_quantity=Decimal(8), reason="Bought 3 more", performed_by_id=admin.id
    )

    refreshed = tools_service.get_tool(db, tool.id)
    assert refreshed.quantity == Decimal(8)


def test_adjust_decreases_quantity(db):
    tool = _seed_tool(db, quantity=5)
    admin = _seed_user(db, role="admin")

    tools_service.adjust_tool_quantity(
        db, tool.id, new_quantity=Decimal(2), reason="Miscount", performed_by_id=admin.id
    )

    refreshed = tools_service.get_tool(db, tool.id)
    assert refreshed.quantity == Decimal(2)


def test_adjust_no_change_raises(db):
    tool = _seed_tool(db, quantity=5)
    admin = _seed_user(db, role="admin")

    with pytest.raises(NoChangeError):
        tools_service.adjust_tool_quantity(
            db, tool.id, new_quantity=Decimal(5), reason="No-op", performed_by_id=admin.id
        )


def test_adjust_does_not_affect_custody(db):
    # Regression: an `adjust` row must never be counted by the custody
    # aggregate (it carries no assigned_to_id / is not checkout|return).
    tool = _seed_tool(db, quantity=5)
    user = _seed_user(db)
    admin = _seed_user(db, role="admin")

    tools_service.checkout_tool(
        db, tool.id, quantity=Decimal(2), assigned_to_id=user.id, performed_by_id=admin.id
    )
    tools_service.adjust_tool_quantity(
        db, tool.id, new_quantity=Decimal(10), reason="Found more", performed_by_id=admin.id
    )

    refreshed = tools_service.get_tool(db, tool.id)
    assert refreshed.quantity == Decimal(10)

    custody = tools_service.tool_custody(db, tool.id)
    assert custody == [(user.id, user.username, Decimal(2))]


def test_adjust_unknown_tool_raises_not_found(db):
    admin = _seed_user(db, role="admin")
    with pytest.raises(ToolNotFoundError):
        tools_service.adjust_tool_quantity(
            db, uuid.uuid4(), new_quantity=Decimal(1), reason="x", performed_by_id=admin.id
        )
