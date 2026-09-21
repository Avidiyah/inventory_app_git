"""The one thing the table itself must guarantee: one open punch per person."""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import AttendancePunch, User
from app.services import auth as auth_service


def _seed_user(db):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"), role="technician")
    db.add(user); db.flush()
    return user


def test_a_second_open_punch_is_refused_by_the_database(db):
    user = _seed_user(db)
    now = datetime.now(timezone.utc)
    db.add(AttendancePunch(user_id=user.id, started_at=now, start_source="manual"))
    db.flush()
    db.add(AttendancePunch(user_id=user.id, started_at=now, start_source="manual"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_a_closed_punch_leaves_room_for_the_next_one(db):
    user = _seed_user(db)
    now = datetime.now(timezone.utc)
    db.add(AttendancePunch(user_id=user.id, started_at=now - timedelta(hours=9),
                           ended_at=now - timedelta(hours=1),
                           start_source="manual", end_source="manual"))
    db.flush()
    db.add(AttendancePunch(user_id=user.id, started_at=now, start_source="manual"))
    db.flush()  # no IntegrityError
