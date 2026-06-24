"""Authentication service: password hashing and session lifecycle.

Layer: services (persistence + orchestration, no FastAPI). Called by
`app/routers/auth.py` and the user router (for hashing on create/reset),
and by the bootstrap script.

Password hashing uses the standard library's `hashlib.scrypt` -- a
memory-hard KDF -- so the project needs no third-party hashing
dependency. Hashes are stored self-describing as
`scrypt$n$r$p$salt_hex$hash_hex`, which keeps the cost parameters with
each hash and lets them be tuned later without breaking existing rows.

Sessions are server-side rows (`AuthSession`). `get_active_session_user`
is the single place that enforces the lifetime policy: it is called on
every authenticated request and expires-and-deletes a remembered session
once it passes its absolute `expires_at` cap. Non-remembered sessions
have no server-side cap (`expires_at` is NULL) and simply end when the
browser drops the session cookie; there is no idle timeout.
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.domain.errors import InvalidCredentialsError
from app.models import AuthSession, User

# Lifetime of a "remembered" session: an absolute cap measured from
# login, not a sliding/idle window. A remembered device stays signed in
# until this elapses (or the user logs out), then must sign in again.
# Non-remembered sessions carry no server-side cap (expires_at is NULL)
# and simply end when the browser closes -- there is no idle timeout.
REMEMBER_LIFETIME = timedelta(hours=12)

# scrypt cost parameters. n must be a power of two; these are sensible
# interactive-login defaults that complete in a few milliseconds.
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Return a self-describing scrypt hash of `password`. A fresh
    random salt is generated per call, so two equal passwords produce
    different hashes."""
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of `password` against a stored hash produced
    by `hash_password`. Returns False (never raises) on any malformed
    or unrecognised hash so a corrupt row simply fails the login."""
    try:
        algorithm, n, r, p, salt_hex, hash_hex = stored.split("$")
        if algorithm != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(hash_hex) // 2,
        )
        return hmac.compare_digest(derived.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def authenticate(db: Session, *, username: str, password: str) -> User:
    """Resolve a username + password to a `User`. Raises
    `InvalidCredentialsError` for "no such user", "wrong password", AND
    "archived user" so all three are indistinguishable to a caller: an
    archived (soft-deleted) user can no longer log in, but we do not leak
    that the account exists."""
    user = db.query(User).filter(User.username == username).first()
    if (
        user is None
        or user.archived_at is not None
        or not verify_password(password, user.password_hash)
    ):
        raise InvalidCredentialsError("Invalid username or password.")
    return user


def create_session(db: Session, user: User, *, remember: bool = False) -> str:
    """Open a new session for `user` and return its opaque token. The
    token is what the caller stores in the session cookie.

    `remember` selects the lifetime policy: when True the session gets a
    hard absolute cap of `REMEMBER_LIFETIME` from now (`expires_at`);
    when False `expires_at` stays NULL (no server-side cap -- the caller
    issues a session cookie that dies on browser close)."""
    now = datetime.now(timezone.utc)
    session = AuthSession(
        token=secrets.token_urlsafe(32),
        user_id=user.id,
        created_at=now,
        expires_at=now + REMEMBER_LIFETIME if remember else None,
    )
    db.add(session)
    db.commit()
    return session.token


def get_active_session_user(db: Session, token: str) -> Optional[User]:
    """Return the `User` for a valid, non-expired session token, or
    `None`.

    Lifetime policy:
    - If the session is missing, returns None.
    - If it is a remembered session (`expires_at` set) and now is past
      that cap, the row is deleted and None is returned (expired on the
      server).
    - Otherwise (no cap, or cap not yet reached) the owning user is
      returned, unless that user has since been archived -- an archived
      user is treated as having no valid session (defense in depth: the
      archive path also deletes the user's sessions, but this guards any
      that slip through). There is no idle timeout and no per-request write.
    """
    session = db.query(AuthSession).filter(AuthSession.token == token).first()
    if session is None:
        return None

    expires_at = session.expires_at
    if expires_at is not None:
        # Postgres returns tz-aware datetimes; guard defensively in case
        # a naive value ever slips in so the comparison cannot crash.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            db.delete(session)
            db.commit()
            return None

    return (
        db.query(User)
        .filter(User.id == session.user_id, User.archived_at.is_(None))
        .first()
    )


def delete_session(db: Session, token: str) -> None:
    """Delete a session by token (logout). A no-op if it does not
    exist, so double-logout is harmless."""
    db.query(AuthSession).filter(AuthSession.token == token).delete()
    db.commit()
