"""Login throttle persistence: failed-attempt counters and locks.

Layer: services (persistence + orchestration, no FastAPI). Called only
by `app/routers/auth.py`, around `services.auth.authenticate`. The
policy itself -- how long a lock lasts, how the key is built -- lives in
`app.domain.login_throttle`; this module only stores and retrieves.

Two layers share one `login_attempts` table, discriminated by `scope`:

- **`user_ip`** -- always on. Keyed on the submitted username plus the
  client IP. This is the layer that stops credential brute-forcing, and
  it is safe unconditionally: even if every request appears to come from
  one address (misconfigured proxy headers), distinct usernames still
  get distinct counters, so no user can lock out another.

- **`ip`** -- opt-in via `LOGIN_THROTTLE_PER_IP`, default **off**. A
  wider net against username enumeration from a single source. It is
  off by default precisely because it is *not* safe under misconfigured
  proxy headers: if the app sees only Render's proxy IP, this layer
  would throttle the entire crew as one client. Turn it on only after
  confirming distinct client IPs reach the app (see `entrypoint.sh`,
  which passes `--proxy-headers`).
"""

import os
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.errors import LoginThrottledError
from app.domain.login_throttle import (
    ATTEMPT_TTL,
    FREE_ATTEMPTS,
    lock_duration,
    user_ip_key,
)
from app.models import LoginAttempt

SCOPE_USER_IP = "user_ip"
SCOPE_IP = "ip"

# Failures tolerated per IP across *all* usernames before the optional
# wider layer engages. Deliberately far looser than the per-user window,
# since a shared NAT can legitimately produce several users' typos.
PER_IP_FREE_ATTEMPTS = 50


def per_ip_enabled() -> bool:
    """Whether the IP-wide layer is active. Read per call rather than at
    import so tests and a redeploy can flip it without reimporting."""
    return os.getenv("LOGIN_THROTTLE_PER_IP", "false").strip().lower() == "true"


def _as_utc(value: datetime) -> datetime:
    """Postgres hands back tz-aware values; normalize defensively so a
    naive one can never crash a comparison (mirrors the guard in
    `services.auth.get_active_session_user`)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _row(db: Session, scope: str, key: str) -> LoginAttempt | None:
    return (
        db.query(LoginAttempt)
        .filter(LoginAttempt.scope == scope, LoginAttempt.key == key)
        .first()
    )


def _remaining_seconds(row: LoginAttempt | None, now: datetime) -> int:
    """Seconds left on `row`'s lock, or 0 if absent/unlocked/lapsed."""
    if row is None or row.locked_until is None:
        return 0
    locked_until = _as_utc(row.locked_until)
    if locked_until <= now:
        return 0
    # Round up: reporting 0 while still locked would invite an immediate
    # retry that just fails again.
    return max(1, int((locked_until - now).total_seconds() + 0.999))


def sweep(db: Session) -> int:
    """Delete counters older than `ATTEMPT_TTL`. Called from
    `record_failure` for the same reason `services.auth` sweeps sessions
    on login: it bounds the table without a scheduler."""
    return (
        db.query(LoginAttempt)
        .filter(LoginAttempt.last_failed_at <= datetime.now(timezone.utc) - ATTEMPT_TTL)
        .delete(synchronize_session=False)
    )


def check(db: Session, *, username: str, ip: str) -> None:
    """Raise `LoginThrottledError` if this caller is currently locked
    out. Runs *before* credentials are examined, so it reveals nothing
    about whether the account exists."""
    now = datetime.now(timezone.utc)

    candidates = [_row(db, SCOPE_USER_IP, user_ip_key(username, ip))]
    if per_ip_enabled():
        candidates.append(_row(db, SCOPE_IP, ip))

    remaining = max((_remaining_seconds(row, now) for row in candidates), default=0)
    if remaining > 0:
        raise LoginThrottledError(
            f"Too many sign-in attempts. Try again in {remaining} seconds.",
            retry_after_seconds=remaining,
        )


def _bump(db: Session, scope: str, key: str, *, free_attempts: int, now: datetime) -> None:
    """Increment one counter and recompute its lock window."""
    row = _row(db, scope, key)
    if row is None:
        row = LoginAttempt(
            scope=scope,
            key=key,
            failure_count=0,
            first_failed_at=now,
            last_failed_at=now,
        )
        db.add(row)
        try:
            # Flush now so a concurrent insert of the same (scope, key)
            # surfaces here as an IntegrityError rather than poisoning
            # the caller's commit.
            db.flush()
        except IntegrityError:
            db.rollback()
            row = _row(db, scope, key)
            if row is None:  # pragma: no cover - the row must exist post-conflict
                return

    row.failure_count = (row.failure_count or 0) + 1
    row.last_failed_at = now

    # A layer with a wider free window reuses the same curve, shifted:
    # subtracting the extra headroom maps its first biting failure onto
    # the domain's first biting failure, so both layers share one policy
    # instead of duplicating the schedule.
    effective = row.failure_count - (free_attempts - FREE_ATTEMPTS)
    duration = lock_duration(effective)
    row.locked_until = now + duration if duration else None


def record_failure(db: Session, *, username: str, ip: str) -> None:
    """Count one failed login against both active layers and commit."""
    now = datetime.now(timezone.utc)

    _bump(
        db,
        SCOPE_USER_IP,
        user_ip_key(username, ip),
        free_attempts=FREE_ATTEMPTS,
        now=now,
    )
    if per_ip_enabled():
        _bump(db, SCOPE_IP, ip, free_attempts=PER_IP_FREE_ATTEMPTS, now=now)

    sweep(db)
    db.commit()


def clear(db: Session, *, username: str, ip: str) -> None:
    """Reset this caller's per-user counter after a successful login.

    The IP-wide counter is deliberately left alone: one success among
    many failures from the same source is exactly what a successful
    enumeration sweep looks like, so it should not wipe that evidence.
    It lapses on its own via `sweep`."""
    db.query(LoginAttempt).filter(
        LoginAttempt.scope == SCOPE_USER_IP,
        LoginAttempt.key == user_ip_key(username, ip),
    ).delete(synchronize_session=False)
    db.commit()
