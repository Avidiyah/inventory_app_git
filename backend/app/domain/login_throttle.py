"""Login throttle policy -- pure rules, no I/O.

Layer: domain. No FastAPI, no SQLAlchemy, no clock reads beyond what is
passed in, so the whole policy is unit-testable without a database.
`app.services.login_throttle` owns the persistence and calls in here for
every decision about how long a lock should last.

The shape of the policy matters as much as the numbers:

**Exponential backoff, not account lockout.** A hard "N failures locks
the account" rule is a denial-of-service weapon -- anyone who knows the
crew's usernames could lock every one of them out at the start of a
shift. Backoff instead degrades an attacker's throughput toward zero
while a real user who mistypes a password barely notices.

**Keyed on (username, IP), not username alone.** Same reason: a
throttle that keys on the username only lets an attacker anywhere lock
out a legitimate user. Including the IP means a remote attacker's
failures cannot delay the person standing in the warehouse.

**Enforced by rejection, never by sleeping.** The caller returns HTTP
429 with `Retry-After`. Sleeping inside the handler would hold a
FastAPI threadpool slot (default 40), turning the throttle itself into
a cheap resource-exhaustion lever.
"""

from datetime import timedelta

# Attempts 1..FREE_ATTEMPTS are never delayed. Set above the number of
# times a real person plausibly fat-fingers a password in a row.
FREE_ATTEMPTS = 5

# Delay applied to the first failure past the free window; each further
# failure doubles it, up to MAX_DELAY.
BASE_DELAY = timedelta(seconds=5)
MAX_DELAY = timedelta(minutes=15)

# Counters older than this are swept. Long enough that a slow-drip
# attacker cannot reset their count by pausing for a coffee, short
# enough that the table stays transient rather than becoming a log.
ATTEMPT_TTL = timedelta(hours=24)


def lock_duration(failure_count: int) -> timedelta:
    """How long to refuse further attempts after `failure_count`
    consecutive failures.

    Zero while at or below `FREE_ATTEMPTS`, then doubling from
    `BASE_DELAY` and clamped at `MAX_DELAY`:

        6th -> 5s, 7th -> 10s, 8th -> 20s, 9th -> 40s, ... -> 15m

    Which leaves a sustained attacker at roughly four guesses an hour
    against a given (username, IP) pair.
    """
    if failure_count <= FREE_ATTEMPTS:
        return timedelta(0)

    # 6th failure is the 1st past the free window -> BASE_DELAY * 2**0.
    steps = failure_count - FREE_ATTEMPTS - 1
    # Cap the exponent before multiplying so a very large counter cannot
    # build an absurd intermediate timedelta (or overflow it).
    if steps >= 32:
        return MAX_DELAY
    delay = BASE_DELAY * (2 ** steps)
    return min(delay, MAX_DELAY)


def user_ip_key(username: str, ip: str) -> str:
    """Counter key for the per-(username, IP) layer.

    Uses the **submitted** username, case-folded and trimmed -- never a
    resolved user id. `services.auth.authenticate` deliberately makes
    "no such user" and "wrong password" indistinguishable; keying on a
    resolved id would leak account existence back out through which
    attempts get throttled.
    """
    return f"{username.strip().casefold()}|{ip}"
