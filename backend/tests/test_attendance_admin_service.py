"""The Admin's audited punch writes (spec D2, §1, §9).

A soft-deleted punch is gone for every purpose except the audit trail: the
partial unique index must not count it, and no read may return it.
"""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from app.models import AttendancePunch, User
from app.services import attendance as attendance_service
from app.services import auth as auth_service


def _seed_user(db, role="technician"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"), role=role)
    db.add(user); db.flush()
    return user


def test_a_soft_deleted_open_punch_does_not_block_a_new_punch_in(db):
    # The partial unique index is the reason this is a real risk: if it still
    # counted the deleted row, the insert would raise IntegrityError and the
    # person could never clock in again.
    user = _seed_user(db)
    now = datetime.now(timezone.utc)
    stale = AttendancePunch(id=uuid.uuid4(), user_id=user.id,
                            started_at=now - timedelta(hours=30),
                            start_source="manual", deleted_at=now)
    db.add(stale); db.commit()

    punch = attendance_service.punch_in(db, user=user, now=now)

    assert punch.ended_at is None
    assert attendance_service.open_punch_for(db, user.id).id == punch.id
