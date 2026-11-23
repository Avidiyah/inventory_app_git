"""Tutorial progress service (0b spec 5.1, 5.2).

Layer: services. Owns commits. Timestamps are first-write-wins: the insert
is `ON CONFLICT DO NOTHING` so two devices racing cannot overwrite each
other, and `completed_at` is only ever filled while still null.
"""

import uuid
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domain import tutorials as rules
from app.domain.errors import TutorialProgressLimitError
from app.domain.list_limits import fetch_limit
from app.models import TutorialProgress, User
from app.schemas.tutorials import ProgressEvent
from app.services._list_cap import capped


def list_mine(db: Session, user_id: uuid.UUID) -> list[TutorialProgress]:
    """The caller's rows, oldest first. Bounded by the 500-row write cap."""
    return (
        db.query(TutorialProgress)
        .filter(TutorialProgress.user_id == user_id)
        .order_by(TutorialProgress.seen_at, TutorialProgress.script_key)
        .populate_existing()  # core UPDATEs in record() bypass the identity map
        .all()
    )


def record(db: Session, user_id: uuid.UUID, key: str, event: ProgressEvent) -> None:
    """Record `seen` or `completed` for one key; repeats change nothing."""
    rules.validate_key(key)
    exists = (
        db.query(TutorialProgress.script_key)
        .filter_by(user_id=user_id, script_key=key)
        .first()
        is not None
    )
    if not exists:
        held = db.query(func.count()).select_from(TutorialProgress).filter(
            TutorialProgress.user_id == user_id
        ).scalar()
        if held >= rules.MAX_ROWS_PER_USER:
            raise TutorialProgressLimitError("Too many tutorial records.")
    now = datetime.now(timezone.utc)
    done = event == ProgressEvent.completed
    db.execute(
        insert(TutorialProgress)
        .values(
            user_id=user_id,
            script_key=key,
            seen_at=now,
            completed_at=now if done else None,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "script_key"])
    )
    if done:
        db.execute(
            update(TutorialProgress)
            .where(
                TutorialProgress.user_id == user_id,
                TutorialProgress.script_key == key,
                TutorialProgress.completed_at.is_(None),
            )
            .values(completed_at=now)
        )
    db.commit()


def completed_by_user(db: Session) -> dict[str, list[str]]:
    """`{user_id: [completed keys]}` for active users who finished any."""
    rows = capped(
        db.query(TutorialProgress.user_id, TutorialProgress.script_key)
        .join(User, User.id == TutorialProgress.user_id)
        .filter(User.archived_at.is_(None), TutorialProgress.completed_at.isnot(None))
        .order_by(TutorialProgress.user_id, TutorialProgress.script_key)
        .limit(fetch_limit())
        .all(),
        what="tutorial progress",
    )
    out: dict[str, list[str]] = defaultdict(list)
    for user_id, key in rows:
        out[str(user_id)].append(key)
    return dict(out)
