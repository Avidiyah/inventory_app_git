"""Authentication service: password hashing and session lifecycle.

Layer: services (persistence + orchestration, no FastAPI). Called by
`app/routers/auth.py` and the user router (for hashing on create/reset),
and by the bootstrap script.

Password hashing uses the standard library's `hashlib.scrypt` -- a
memory-hard KDF -- so the project needs no third-party hashing
dependency. Hashes are stored self-describing as
`scrypt$n$r$p$salt_hex$hash_hex`, which keeps the cost parameters with
each hash and lets them be tuned later without breaking existing rows.

Sessions are server-side rows (`AuthSession`), and the row stores only
the **SHA-256 hash** of the cookie token -- see `_hash_token`. The raw
token is generated in `create_session`, handed straight to the caller
for the cookie, and never persisted, so reading the `sessions` table
yields nothing that can be replayed as a credential.

`get_active_session_user` is the single place that enforces the lifetime
policy: it is called on every authenticated request and
expires-and-deletes any session past its absolute `expires_at` cap.
Every session now carries such a cap -- `expires_at` is never NULL -- so
"remember this device" no longer changes the server-side lifetime, only
whether the browser keeps the cookie across a restart. There is still no
idle timeout and no per-request write (see migration `c7e9a1b3d5f8`,
which deliberately removed the old sliding window).
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

# Absolute session caps, measured from login -- not sliding/idle
# windows. Both are 12h today: the product rule is "no session outlives
# a shift", and whether the user ticked "remember this device" changes
# only the cookie's persistence, not the server-side lifetime. They are
# kept as two constants so the two policies can diverge later without
# hunting call sites.
REMEMBER_LIFETIME = timedelta(hours=12)
SESSION_LIFETIME = timedelta(hours=12)

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


def username_exists(db: Session, username: str) -> bool:
    """Whether an account with this username exists, archived or not.

    Exists for logging, and only for logging. `authenticate` above is
    deliberately unable to tell a caller whether an account exists -- but
    that is a property of the **HTTP response**, which this does not
    touch. The router calls this on the failure path so a failed login can
    be logged against a real username instead of `unknown`.

    Why that matters: logging whatever string was submitted would mean
    that a user who types their password into the username field puts
    their password in the logs, in plaintext, permanently. A password
    will never match an account, so gating the log on existence closes
    that structurally rather than by discipline. The cost, accepted
    knowingly: a probe against a username that does not exist is logged
    as `unknown`, so the log shows the attempt and the IP but not which
    nonexistent names were tried.
    """
    return db.query(User.id).filter(User.username == username).first() is not None


def hash_session_token(token: str) -> str:
    """Return the lowercase hex SHA-256 of a session token -- the only
    form ever written to the database, and the only form a long-lived
    real-time connection is allowed to remember.

    Plain SHA-256 (not scrypt) is correct here: the input is 256 bits of
    CSPRNG output, so there is no guessable keyspace for a slow KDF to
    defend, and this runs on every authenticated request."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# Retained so existing internal callers read unchanged.
_hash_token = hash_session_token


def sweep_expired_sessions(db: Session) -> int:
    """Delete every session past its cap and return how many went.

    Called from `create_session`, which is deliberate rather than lazy:
    rows can only accumulate at the rate of logins, so cleaning up on
    login bounds the table without a background task or a scheduler --
    and therefore without inheriting the multi-instance coordination
    problem noted in the API hardening checklist (N3)."""
    removed = (
        db.query(AuthSession)
        .filter(AuthSession.expires_at <= datetime.now(timezone.utc))
        .delete(synchronize_session=False)
    )
    db.commit()
    return removed


def revoke_user_sessions(db: Session, user_id) -> int:
    """Delete every session belonging to `user_id` and return the count.
    Does not commit -- the caller folds this into its own transaction so
    the revocation and the change that motivated it land together.

    Shared by the three places that must not leave a live session behind
    a credential or authority change: `services.users.archive_user`,
    `update_role`, and `reset_password`."""
    return (
        db.query(AuthSession)
        .filter(AuthSession.user_id == user_id)
        .delete(synchronize_session=False)
    )


def create_session(db: Session, user: User, *, remember: bool = False) -> str:
    """Open a new session for `user` and return its opaque token -- the
    value the caller puts in the session cookie. Only the token's hash
    is stored, so this return value is the one and only time the raw
    token exists server-side.

    Every session gets a hard absolute cap: `REMEMBER_LIFETIME` when the
    user asked to be remembered, `SESSION_LIFETIME` otherwise (both 12h
    today). `remember` no longer affects server-side validity at all --
    the router uses it to decide whether the cookie is persistent."""
    sweep_expired_sessions(db)

    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    session = AuthSession(
        token_hash=_hash_token(token),
        user_id=user.id,
        created_at=now,
        expires_at=now + (REMEMBER_LIFETIME if remember else SESSION_LIFETIME),
    )
    db.add(session)
    db.commit()
    return token


def get_active_session_user(db: Session, token: str) -> Optional[User]:
    """Return the `User` for a valid, non-expired session token, or
    `None`. `token` is the raw cookie value; it is hashed here to find
    the row.

    Lifetime policy:
    - If no session matches the hash, returns None.
    - If the session is past its `expires_at` cap, the row is deleted and
      None is returned (expired on the server). Every session has a cap.
    - Otherwise the owning user is returned, unless that user has since
      been archived -- an archived user is treated as having no valid
      session (defense in depth: the archive path also deletes the user's
      sessions, but this guards any that slip through). There is no idle
      timeout and no per-request write.
    """
    return _resolve_active_session(db, hash_session_token(token))


def get_active_session_user_by_hash(db: Session, token_hash: str) -> Optional[User]:
    """`get_active_session_user`, keyed by an already-hashed token.

    Exists for the real-time layer. A socket is authenticated once at
    handshake and has no next request, so it re-resolves its session on a
    timer to stay bound to revocation, role change, and the 12-hour cap
    (design D1). It stores the **hash** rather than the raw token: a raw
    token is a live credential, and a connection registry is exactly the
    process-wide structure `services.rate_limit.caller_key` hashes to stay
    out of.

    Identical policy to the raw-token resolver, and deliberately a thin
    wrapper over one shared implementation so the two cannot drift.
    """
    return _resolve_active_session(db, token_hash)


def _resolve_active_session(db: Session, token_hash: str) -> Optional[User]:
    """Shared body of the two resolvers above. See `get_active_session_user`
    for the lifetime policy this implements."""
    session = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == token_hash)
        .first()
    )
    if session is None:
        return None

    expires_at = session.expires_at
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
    """Delete a session by its raw cookie token (logout). A no-op if it
    does not exist, so double-logout is harmless."""
    db.query(AuthSession).filter(
        AuthSession.token_hash == _hash_token(token)
    ).delete(synchronize_session=False)
    db.commit()
