"""Request rate limit policy -- pure rules, no I/O.

Layer: domain. No FastAPI, no SQLAlchemy, no clock reads beyond what is
passed in, so the whole policy is unit-testable without a database or a
running app. `app.services.rate_limit` owns the counters and calls in
here for every decision.

The shape of the policy matters as much as the number:

**A per-caller cap, not a global one.** A single shared bucket would be
spent by ordinary traffic: the SPA's cold load is one HTML shell plus a
33-module ES graph, `styles.css`, and a 441 KB vendor bundle, which a
browser fires nearly at once. Two people refreshing together would trip
a global 60/s and one of them would be served a 429 for a JavaScript
module -- i.e. the blank page this app already has history with. Per
caller, that interference is impossible by construction.

**API routes only.** `/`, `/static/*` and `/healthz` are exempt, so no
amount of page loading can consume the budget that exists to catch a
runaway API client. `/healthz` is exempt for a second and separate
reason: `render.yaml` points `healthCheckPath` at it, so a 429 there
would fail a deploy rather than protect one.

**Enforced by rejection, never by sleeping.** The caller returns HTTP
429 with `Retry-After`. Sleeping inside the handler would hold a
FastAPI threadpool slot (default 40), turning the limiter itself into a
cheap resource-exhaustion lever. This is the same reasoning
`domain.login_throttle` records, and it applies here with more force:
this limiter sits on every API route rather than one.

**It targets accidents, not attackers.** Every caller past `/auth/login`
is a named, role-checked user with an audit trail, so the realistic
failure is a retry loop or a double-submit rather than an attack. 60/s
is far above anything the UI produces (a full page refresh is ~35
requests, and those are exempt anyway) and far below what a runaway
`fetch` loop produces, which is the gap the number is chosen to sit in.
"""

import math

# Requests allowed per caller per window. See the module docstring for
# why this is deliberately loose: it is a ceiling on malfunction, not a
# quota on use.
MAX_REQUESTS = 60

# The sliding window the cap applies over, in seconds.
WINDOW_SECONDS = 1.0

# Paths the limiter never counts. Matched as prefixes, except `/` which
# is matched exactly -- as a prefix it would exempt the entire app.
EXEMPT_PREFIXES = ("/static/",)
EXEMPT_EXACT = ("/", "/healthz")


def is_exempt(path: str) -> bool:
    """Whether `path` is outside the limiter entirely.

    Exempt traffic is not counted *and* not rejected, so a caller who is
    already over the limit can still load the SPA -- otherwise a client
    that ran away once would be unable to fetch the page that fixes it.
    """
    if path in EXEMPT_EXACT:
        return True
    return path.startswith(EXEMPT_PREFIXES)


def window_start(now: float) -> float:
    """The oldest timestamp still inside the window ending at `now`.

    Anything at or before this has aged out and no longer counts.
    """
    return now - WINDOW_SECONDS


def is_over_limit(count_in_window: int) -> bool:
    """Whether a request arriving now would exceed the cap.

    `count_in_window` is the number of *already recorded* requests still
    inside the window, so the incoming one is allowed while that count
    is below `MAX_REQUESTS` -- making exactly `MAX_REQUESTS` requests per
    window succeed rather than `MAX_REQUESTS - 1`.
    """
    return count_in_window >= MAX_REQUESTS


def retry_after_seconds(oldest_in_window: float, now: float) -> int:
    """Whole seconds until the window has room again.

    Rounded up, and never below 1: reporting 0 while still limited would
    invite an immediate retry that just fails again. Mirrors the same
    guard in `services.login_throttle._remaining_seconds`.
    """
    frees_at = oldest_in_window + WINDOW_SECONDS
    return max(1, math.ceil(frees_at - now))
