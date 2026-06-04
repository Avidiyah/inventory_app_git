"""User CRUD service.

Layer: services. Called by `app/routers/users.py`. Like the items
service, this module translates database integrity violations into
the domain vocabulary so the router can stay free of SQLAlchemy
imports.

Notable rule: deleting a user that has transactions is refused
rather than cascaded. The decision log in `docs/spec.md` records
that the audit trail must be preserved, so the FK on
`transactions.user_id` is `ON DELETE RESTRICT` and the
`IntegrityError` it raises here is surfaced as
`UserHasTransactionsError`.
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.errors import (
    DuplicateUsernameError,
    UserHasTransactionsError,
    UserNotFoundError,
)
from app.models import User


def create_user(db: Session, *, username: str) -> User:
    """Insert a new user. Raises `DuplicateUsernameError` if the
    UNIQUE constraint on `username` fires."""
    new_user = User(username=username)
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateUsernameError("A user with this username already exists.") from exc
    db.refresh(new_user)
    return new_user


def list_users(db: Session):
    """Return every user, newest first. Used to populate the user
    dropdowns in the frontend transaction form."""
    return db.query(User).order_by(User.created_at.desc()).all()


def delete_user(db: Session, user_id: uuid.UUID) -> None:
    """Hard-delete a user, refusing if any audit-log rows reference
    them. The FK violation is converted to
    `UserHasTransactionsError` so the router can return 400 with a
    meaningful message instead of leaking the database error."""
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
