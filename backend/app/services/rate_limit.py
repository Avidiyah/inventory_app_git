"""Request rate limit counters: in-memory, per caller.

Layer: services (state + orchestration, no FastAPI). Called only by the
`rate_limit` middleware in `app/main.py`. The policy itself -- the cap,
the window, which paths are exempt -- lives in `app.domain.rate_limit`;
this module only counts.

**In memory, deliberately, where the login throttle uses the database.**
`login_attempts` is DB-backed because a failed-login counter must
survive a restart to be worth anything: an attacker who could reset
their count by waiting out a spin-down would face no throttle at all.
This counter is the opposite -- its whole window is one second, so state
older than that second is worthless by definition, and a restart cannot
lose anything that still mattered. Paying a Postgres write per request
to persist it would cost more than the runaway client it exists to
catch, on an instance sized `basic-256mb`.

**Safe on one process, and this app runs one.** `entrypoint.sh` starts
uvicorn with no `--workers`, so there is a single event loop and
`check_and_record` -- which contains no `await` -- cannot interleave
with itself. If a second worker or a second instance is ever added, the
effective cap becomes 60/s *per process* and this module is one of the
things N3 has to revisit; that is recorded in the checklist rather than
guarded against here, because guarding for it now would mean the
Postgres write this design exists to avoid.

Callers are keyed by **session**, not by user id. The middleware runs
before route dependencies resolve, so `auth_deps.get_current_user` has
not run and no user id exists yet -- the session cookie is the only
identity available that early. The practical difference is that one
person signed in on a phone and a laptop gets two budgets, which is
correct for catching a runaway client: it is that *client* which is
malfunctioning, not the person.
"""

import hashlib
from collections import deque

from app.domain.rate_limit import (
    is_over_limit,
    retry_after_seconds,
    window_start,
)

# Idle keys are dropped no more than this often. Sweeping on a clock
# rather than on every call keeps the common path O(1) instead of O(keys)
# -- the same amortized-cleanup shape `services.login_throttle.sweep`
# uses, minus the database.
SWEEP_INTERVAL_SECONDS = 60.0

# key -> timestamps of requests still inside the window, oldest first.
# Bounded at MAX_REQUESTS entries per key: the window is pruned before
# each append, and an over-limit request is rejected without appending.
_buckets: dict[str, deque[float]] = {}
_last_sweep: float = 0.0


def caller_key(session_token: str | None, ip: str) -> str:
    """Bucket key for one caller.

    The session token is **hashed** rather than used directly. X1 made
    the same call for the `sessions` table: a raw session token is a
    live credential, and putting one in a process-wide dict would place
    it somewhere a stray repr or a debugger dump could surface it. A
    truncated digest is more than enough to keep distinct sessions
    distinct.

    Unauthenticated callers fall back to the client address. That
    inherits the caveat `services.login_throttle` documents for its
    optional per-IP layer -- if proxy headers were misconfigured, every
    such caller would share one bucket. The blast radius is small here:
    the only unauthenticated API route is `/auth/login`, and `/healthz`
    is exempt, so a shared bucket would be 60 logins/second between
    them.
    """
    if session_token:
        digest = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
        return f"s:{digest[:16]}"
    return f"i:{ip}"


def _sweep(now: float) -> None:
    """Drop keys with nothing left inside the window."""
    global _last_sweep
    if now - _last_sweep < SWEEP_INTERVAL_SECONDS:
        return
    _last_sweep = now
    cutoff = window_start(now)
    for key in [k for k, seen in _buckets.items() if not seen or seen[-1] <= cutoff]:
        del _buckets[key]


def check_and_record(key: str, now: float) -> int | None:
    """Count one request against `key`.

    Returns `None` when the request is allowed, or the whole number of
    seconds to wait when it is refused. A refused request is **not**
    recorded: counting rejections would let a client that is already
    looping hold its own window open indefinitely, turning a one-second
    limit into an unbounded lockout.
    """
    _sweep(now)

    seen = _buckets.get(key)
    if seen is None:
        seen = _buckets[key] = deque()

    cutoff = window_start(now)
    while seen and seen[0] <= cutoff:
        seen.popleft()

    if is_over_limit(len(seen)):
        return retry_after_seconds(seen[0], now)

    seen.append(now)
    return None


def reset() -> None:
    """Discard all counters. For tests -- the module state is process
    global, so a test that fills a bucket would otherwise leak into the
    next one."""
    global _last_sweep
    _buckets.clear()
    _last_sweep = 0.0
