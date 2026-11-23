"""tutorial_progress cascade rules (0b spec 6): deleting a user removes their
rows, archiving one leaves them."""

import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import TutorialProgress, User
from app.services import auth as auth_service


def _seed_user(db, role="technician"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth_service.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _rows(db, user_id):
    return db.query(TutorialProgress).filter_by(user_id=user_id).count()


def test_deleting_a_user_removes_their_progress(db):
    user = _seed_user(db)
    user_id = user.id
    db.add(TutorialProgress(user_id=user_id, script_key="work-orders.card.notes"))
    db.flush()

    db.delete(user)
    db.flush()

    assert _rows(db, user_id) == 0


def test_archiving_a_user_keeps_their_progress(db):
    user = _seed_user(db)
    db.add(TutorialProgress(user_id=user.id, script_key="work-orders.card.notes"))
    db.flush()

    user.archived_at = datetime.now(timezone.utc)
    db.flush()

    assert _rows(db, user.id) == 1
