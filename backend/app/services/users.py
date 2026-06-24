"""User CRUD service.

Layer: services. Called by `app/routers/users.py`. Like the items
service, this module translates database integrity violations into
the domain vocabulary so the router can stay free of SQLAlchemy
imports.

Notable rule: deleting a user that has transactions is refused
rather than cascaded. `docs/current-state.md` records
that the audit trail must be preserved, so the FK on
`transactions.user_id` is `ON DELETE RESTRICT` and the
`IntegrityError` it raises here is surfaced as
`UserHasTransactionsError`.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.errors import (
    DuplicateUsernameError,
    UserHasTransactionsError,
    UserNotFoundError,
)
from app.models import AuthSession, User


def create_user(db: Session, *, username: str, password_hash: str, role: str) -> User:
    """Insert a new user with a pre-hashed password and a role. The
    caller (router) is responsible for hashing the password and for
    checking that it is allowed to assign `role`. Raises
    `DuplicateUsernameError` if the UNIQUE constraint on `username`
    fires."""
    new_user = User(username=username, password_hash=password_hash, role=role)
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateUsernameError("A user with this username already exists.") from exc
    db.refresh(new_user)
    return new_user


def list_users(db: Session, *, include_archived: bool = False):
    """Return users, newest first. By default only active (non-archived)
    users are returned -- the Saved Users management table. The History
    "by user" filter passes `include_archived=True` so a departed user's
    rows can still be filtered (their name still resolves in history)."""
    query = db.query(User)
    if not include_archived:
        query = query.filter(User.archived_at.is_(None))
    return query.order_by(User.created_at.desc()).all()


def get_user(db: Session, user_id: uuid.UUID) -> User:
    """Fetch one user by id. Raises `UserNotFoundError` if missing so
    routers can return 404 and inspect the target's role before acting
    on it."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise UserNotFoundError("User not found.")
    return user


def reset_password(db: Session, user_id: uuid.UUID, password_hash: str) -> None:
    """Replace a user's password hash. Raises `UserNotFoundError` if the
    user does not exist. Existing sessions are intentionally left
    intact; the idle timeout will retire them."""
    user = get_user(db, user_id)
    user.password_hash = password_hash
    db.commit()


def delete_user(db: Session, user_id: uuid.UUID) -> None:
    """Hard-delete a user, refusing if any audit-log rows reference
    them. The FK violation is converted to
    `UserHasTransactionsError` so the router can return 400 with a
    meaningful message instead of leaking the database error.

    This is the genuine row-removal path, kept for an unreferenced user
    created in error. The normal "remove a user" action is
    `archive_user`, which preserves the audit trail and works even for a
    user with transactions."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise UserNotFoundError("User not found.")
    db.delete(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise UserHasTransactionsError(
            "Cannot delete user with existing transactions."
        ) from exc


def archive_user(db: Session, user_id: uuid.UUID) -> User:
    """Soft-delete (archive) a user by setting `archived_at`, and revoke
    all of their sessions so any active login ends immediately. The row is
    deliberately retained: the history view resolves the acting user's
    name through a live join, so a hard delete would orphan those rows.
    Archiving keeps the audit trail intact while blocking login
    (`services.auth.authenticate` rejects archived users) and hiding the
    user from the active Saved Users list. Raises `UserNotFoundError` if
    the id is unknown. Idempotent: archiving an already-archived user
    refreshes the timestamp and re-clears any sessions."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise UserNotFoundError("User not found.")
    user.archived_at = datetime.now(timezone.utc)
    # Revoke active sessions now rather than waiting for them to lapse, so
    # archiving immediately locks the user out.
    db.query(AuthSession).filter(AuthSession.user_id == user_id).delete()
    db.commit()
    db.refresh(user)
    return user


def restore_user(db: Session, user_id: uuid.UUID) -> User:
    """Reactivate an archived user by clearing `archived_at`, allowing
    login again. Raises `UserNotFoundError` if the id is unknown.
    Idempotent: restoring an active user is a no-op."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise UserNotFoundError("User not found.")
    user.archived_at = None
    db.commit()
    db.refresh(user)
    return user
