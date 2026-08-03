"""Database integration tests for user archival (soft delete).

Archiving a user keeps their row (so the history join still resolves
their name) but blocks login, revokes their sessions, and hides them from
the active Saved Users list while keeping them available to the History
"by user" filter. Restore reverses it. These skip if no DB (the `db`
fixture).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from decimal import Decimal

import pytest

from app.domain.errors import InvalidCredentialsError, UserHasCheckedOutToolsError
from app.models import AuthSession, ToolTransaction, User
from app.services import auth
from app.services import tools as tools_service
from app.services import users as users_service


def _seed_user(db, role="technician"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def test_archive_blocks_authentication(db):
    user = _seed_user(db)
    # Active user authenticates fine.
    assert auth.authenticate(db, username=user.username, password="hunter2").id == user.id

    users_service.archive_user(db, user.id)

    with pytest.raises(InvalidCredentialsError):
        auth.authenticate(db, username=user.username, password="hunter2")


def test_archive_revokes_sessions(db):
    user = _seed_user(db)
    token = auth.create_session(db, user, remember=False)
    assert auth.get_active_session_user(db, token) is not None

    users_service.archive_user(db, user.id)

    # Session row is gone, and even a lingering one would not resolve.
    assert db.query(AuthSession).filter(AuthSession.user_id == user.id).count() == 0
    assert auth.get_active_session_user(db, token) is None


def test_archived_user_hidden_from_default_list_but_visible_with_flag(db):
    user = _seed_user(db)
    users_service.archive_user(db, user.id)

    active_ids = {u.id for u in users_service.list_users(db)}
    assert user.id not in active_ids

    all_ids = {u.id for u in users_service.list_users(db, include_archived=True)}
    assert user.id in all_ids


def test_restore_reactivates_login(db):
    user = _seed_user(db)
    users_service.archive_user(db, user.id)
    users_service.restore_user(db, user.id)

    assert auth.authenticate(db, username=user.username, password="hunter2").id == user.id
    assert user.archived_at is None


def test_archive_user_blocked_until_tools_are_returned(db):
    user = _seed_user(db)
    admin = _seed_user(db, role="admin")
    tool = tools_service.create_tool(
        db,
        barcode=f"TOOL-{uuid.uuid4().hex[:10]}",
        name="Cordless Drill",
        quantity=Decimal(2),
    )
    tools_service.checkout_tool(
        db,
        tool.id,
        quantity=Decimal(1),
        assigned_to_id=user.id,
        performed_by_id=admin.id,
    )

    with pytest.raises(UserHasCheckedOutToolsError):
        users_service.archive_user(db, user.id)

    db.refresh(user)
    assert user.archived_at is None

    tools_service.return_tool(
        db,
        tool.id,
        quantity=Decimal(1),
        assigned_to_id=user.id,
        performed_by_id=admin.id,
    )
    users_service.archive_user(db, user.id)
    assert user.archived_at is not None


def test_archive_force_returns_every_outstanding_tool(db):
    user = _seed_user(db)
    admin = _seed_user(db, role="admin")
    drill = tools_service.create_tool(
        db,
        barcode=f"TOOL-{uuid.uuid4().hex[:10]}",
        name="Cordless Drill",
        quantity=Decimal(2),
    )
    meter = tools_service.create_tool(
        db,
        barcode=f"TOOL-{uuid.uuid4().hex[:10]}",
        name="Moisture Meter",
        quantity=Decimal(5),
    )
    for tool, quantity in ((drill, Decimal(1)), (meter, Decimal(3))):
        tools_service.checkout_tool(
            db,
            tool.id,
            quantity=quantity,
            assigned_to_id=user.id,
            performed_by_id=admin.id,
        )
    assert drill.quantity == Decimal(1)
    assert meter.quantity == Decimal(2)

    users_service.archive_user(
        db, user.id, force_return_tools=True, performed_by_id=admin.id
    )

    # Custody is cleared and the units are back on the shelf.
    assert tools_service.user_custody(db, user.id) == []
    db.refresh(drill)
    db.refresh(meter)
    assert drill.quantity == Decimal(2)
    assert meter.quantity == Decimal(5)
    assert user.archived_at is not None

    # The forced check-ins are ordinary `return` rows attributed to the
    # archiving admin, so the custody audit trail still reads correctly.
    returns = [
        (txn.tool_id, txn.quantity, txn.performed_by_id)
        for txn in db.query(ToolTransaction)
        .filter(
            ToolTransaction.assigned_to_id == user.id,
            ToolTransaction.transaction_type == "return",
        )
        .all()
    ]
    assert sorted(returns, key=lambda row: str(row[0])) == sorted(
        [
            (drill.id, Decimal(1), admin.id),
            (meter.id, Decimal(3), admin.id),
        ],
        key=lambda row: str(row[0]),
    )


def test_archive_force_is_harmless_without_custody(db):
    user = _seed_user(db)
    admin = _seed_user(db, role="admin")

    users_service.archive_user(
        db, user.id, force_return_tools=True, performed_by_id=admin.id
    )

    assert user.archived_at is not None
    assert (
        db.query(ToolTransaction)
        .filter(ToolTransaction.assigned_to_id == user.id)
        .count()
        == 0
    )
