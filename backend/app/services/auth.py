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
is the single place that enforces the idle timeout: it is called on
every authenticated request, expires-and-deletes a stale session, and
otherwise slides `last_active_at` forward.
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

# Idle window: a session not touched within this period is expired on
# the next request. Set to 10 minutes so live barcode capture (where
# the user can spend a long time aiming the phone without firing any
# network request) does not get logged out mid-scan.
SESSION_IDLE_TIMEOUT = timedelta(minutes=10)

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
    `InvalidCredentialsError` for both "no such user" and "wrong
    password" so the two cases are indistinguishable to a caller."""
    user = db.query(User).filter(User.username == username).first()
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("Invalid username or password.")
    return user


def create_session(db: Session, user: User) -> str:
    """Open a new session for `user` and return its opaque token. The
    token is what the caller stores in the session cookie."""
    now = datetime.now(timezone.utc)
    session = AuthSession(
        token=secrets.token_urlsafe(32),
        user_id=user.id,
        created_at=now,
        last_active_at=now,
    )
    db.add(session)
    db.commit()
    return session.token


def get_active_session_user(db: Session, token: str) -> Optional[User]:
    """Return the `User` for a valid, non-expired session token, or
    `None`.

    Side effects (the heart of the timeout policy):
    - If the session is missing, returns None.
    - If it has been idle longer than `SESSION_IDLE_TIMEOUT`, the row is
      deleted and None is returned (expired on the server).
    - Otherwise `last_active_at` is bumped to now (sliding window) and
      the owning user is returned.
    """
    session = db.query(AuthSession).filter(AuthSession.token == token).first()
    if session is None:
        return None

    now = datetime.now(timezone.utc)
    last_active = session.last_active_at
    # Postgres returns tz-aware datetimes; guard defensively in case a
    # naive value ever slips in so the subtraction below cannot crash.
    if last_active.tzinfo is None:
        last_active = last_active.replace(tzinfo=timezone.utc)

    if now - last_active > SESSION_IDLE_TIMEOUT:
        db.delete(session)
        db.commit()
        return None

    session.last_active_at = now
    db.commit()
    return db.query(User).filter(User.id == session.user_id).first()


def delete_session(db: Session, token: str) -> None:
    """Delete a session by token (logout). A no-op if it does not
    exist, so double-logout is harmless."""
    db.query(AuthSession).filter(AuthSession.token == token).delete()
    db.commit()
