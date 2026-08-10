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
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.errors import (
    DuplicateToolBarcodeError,
    NegativeQuantityError,
    NoChangeError,
    ToolHasOutstandingCustodyError,
    ToolNotFoundError,
    ToolReturnExceedsCheckedOutError,
    UserNotFoundError,
)
from app.models import ToolTransaction, User
from app.services import auth
from app.services import tools as tools_service


def _seed_user(db, role="technician"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        first_name="Tool",
        last_name=f"User-{uuid.uuid4().hex[:6]}",
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


def _named_user(db, first, last, role="technician"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        first_name=first,
        last_name=last,
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def test_custody_is_ordered_by_name(db):
    # C2, ordering half (2026-08-10). `_custody_query` used to end at
    # `.having(...)` with no ORDER BY, so the order of holders within a tool
    # was whatever Postgres returned -- a user-visible list on the Tools page
    # with an unspecified order, free to change after a vacuum or plan change.
    #
    # Checked out deliberately in reverse alphabetical order, so a query that
    # simply preserved insertion order would fail this.
    tool = _seed_tool(db, quantity=20)
    admin = _seed_user(db, role="admin")
    for first, last in (("Zoe", "Zimmer"), ("Mia", "Mercer"), ("Abe", "Archer")):
        holder = _named_user(db, first, last)
        tools_service.checkout_tool(
            db,
            tool.id,
            quantity=Decimal(1),
            assigned_to_id=holder.id,
            performed_by_id=admin.id,
        )

    names = [name for _, name, _ in tools_service.tool_custody(db, tool.id)]

    assert names == ["Abe Archer", "Mia Mercer", "Zoe Zimmer"]


def test_custody_order_is_deterministic_for_duplicate_full_names(db):
    # Full names are NOT unique (docs/current-state.md -> `users`), so sorting
    # by name alone would leave two same-named holders in an undefined order.
    # `assigned_to_id` is the final tiebreaker; this asserts the result is
    # stable rather than asserting which of the two comes first.
    tool = _seed_tool(db, quantity=20)
    admin = _seed_user(db, role="admin")
    for _ in range(2):
        twin = _named_user(db, "Sam", "Rivera")
        tools_service.checkout_tool(
            db,
            tool.id,
            quantity=Decimal(1),
            assigned_to_id=twin.id,
            performed_by_id=admin.id,
        )

    first_read = tools_service.tool_custody(db, tool.id)
    second_read = tools_service.tool_custody(db, tool.id)

    assert [uid for uid, _, _ in first_read] == [uid for uid, _, _ in second_read]
    assert [name for _, name, _ in first_read] == ["Sam Rivera", "Sam Rivera"]


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
    assert custody == [(user.id, user.full_name, Decimal(2))]


def test_checkout_rejects_archived_user_without_mutation(db):
    tool = _seed_tool(db, quantity=5)
    user = _seed_user(db)
    user.archived_at = datetime.now(timezone.utc)
    db.commit()
    before_transactions = db.query(ToolTransaction).count()

    with pytest.raises(UserNotFoundError):
        tools_service.checkout_tool(
            db,
            tool.id,
            quantity=Decimal(2),
            assigned_to_id=user.id,
            performed_by_id=None,
        )

    db.refresh(tool)
    assert tool.quantity == Decimal(5)
    assert db.query(ToolTransaction).count() == before_transactions


def test_checkout_rejects_unknown_user_without_mutation(db):
    tool = _seed_tool(db, quantity=5)

    with pytest.raises(UserNotFoundError):
        tools_service.checkout_tool(
            db,
            tool.id,
            quantity=Decimal(2),
            assigned_to_id=uuid.uuid4(),
            performed_by_id=None,
        )

    db.refresh(tool)
    assert tool.quantity == Decimal(5)


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
    assert custody == [(user.id, user.full_name, Decimal(1))]


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

    custody = {uid: qty for uid, _name, qty in tools_service.tool_custody(db, tool.id)}
    assert custody[alice.id] == Decimal(3)
    assert custody[bob.id] == Decimal(2)

    # Alice returning her 3 doesn't touch Bob's outstanding balance.
    tools_service.return_tool(
        db, tool.id, quantity=Decimal(3), assigned_to_id=alice.id, performed_by_id=None
    )
    custody_after = {
        uid: qty for uid, _name, qty in tools_service.tool_custody(db, tool.id)
    }
    assert alice.id not in custody_after
    assert custody_after[bob.id] == Decimal(2)


def test_user_custody_aggregates_tools_and_excludes_adjustments(db):
    user = _seed_user(db)
    first = _seed_tool(db, quantity=5)
    second = _seed_tool(db, quantity=5)

    tools_service.checkout_tool(
        db, first.id, quantity=Decimal(2), assigned_to_id=user.id, performed_by_id=None
    )
    tools_service.checkout_tool(
        db, second.id, quantity=Decimal(3), assigned_to_id=user.id, performed_by_id=None
    )
    tools_service.return_tool(
        db, second.id, quantity=Decimal(1), assigned_to_id=user.id, performed_by_id=None
    )
    tools_service.adjust_tool_quantity(
        db, first.id, new_quantity=Decimal(9), reason="Count fix", performed_by_id=None
    )

    custody = {
        tool_id: quantity
        for tool_id, _name, _barcode, quantity in tools_service.user_custody(db, user.id)
    }
    assert custody == {first.id: Decimal(2), second.id: Decimal(2)}


def test_archive_hides_tool_from_list(db):
    tool = _seed_tool(db)
    before = {t.id for t in tools_service.list_tools(db)}
    assert tool.id in before

    tools_service.delete_tool(db, tool.id)

    after = {t.id for t in tools_service.list_tools(db)}
    assert tool.id not in after


def test_archive_tool_blocked_until_full_return(db):
    tool = _seed_tool(db)
    user = _seed_user(db)
    tools_service.checkout_tool(
        db, tool.id, quantity=Decimal(2), assigned_to_id=user.id, performed_by_id=None
    )

    with pytest.raises(ToolHasOutstandingCustodyError):
        tools_service.delete_tool(db, tool.id)

    db.refresh(tool)
    assert tool.archived_at is None

    tools_service.return_tool(
        db, tool.id, quantity=Decimal(2), assigned_to_id=user.id, performed_by_id=None
    )
    tools_service.delete_tool(db, tool.id)
    assert tool.archived_at is not None


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
    assert custody == [(user.id, user.full_name, Decimal(2))]


def test_adjust_unknown_tool_raises_not_found(db):
    admin = _seed_user(db, role="admin")
    with pytest.raises(ToolNotFoundError):
        tools_service.adjust_tool_quantity(
            db, uuid.uuid4(), new_quantity=Decimal(1), reason="x", performed_by_id=admin.id
        )
