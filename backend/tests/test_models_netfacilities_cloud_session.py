"""Schema-level test for the netfacilities_cloud_sessions table (D8)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import NetFacilitiesCloudSession, User


def _user(db):
    user = User(
        username=f"tech-{uuid.uuid4().hex[:8]}",
        first_name="Test",
        last_name="User",
        password_hash="x",
        role="technician",
    )
    db.add(user)
    db.commit()
    return user


def test_one_cloud_session_per_user(db):
    # A plain str, not bytes: the column stores the ascii-decoded Fernet
    # token (see Task 6's `_persist`), never raw ciphertext bytes.
    user = _user(db)
    db.add(
        NetFacilitiesCloudSession(
            id=uuid.uuid4(),
            user_id=user.id,
            storage_state="ciphertext-one",
            signed_in_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    db.add(
        NetFacilitiesCloudSession(
            id=uuid.uuid4(),
            user_id=user.id,
            storage_state="ciphertext-two",
            signed_in_at=datetime.now(timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_cascade_deletes_with_user(db):
    user = _user(db)
    db.add(
        NetFacilitiesCloudSession(
            id=uuid.uuid4(),
            user_id=user.id,
            storage_state="ciphertext",
            signed_in_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    db.delete(user)
    db.commit()

    # Scoped to this user: a developer database can hold a real cloud session
    # for another account, and an unscoped count would see that row.
    assert (
        db.query(NetFacilitiesCloudSession)
        .filter(NetFacilitiesCloudSession.user_id == user.id)
        .count()
        == 0
    )
