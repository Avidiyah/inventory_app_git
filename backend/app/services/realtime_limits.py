"""Process-local counters for the real-time WebSocket boundary.

Layer: services (state + orchestration, no FastAPI). The thresholds live in
``app.domain.realtime`` and the sliding-window rules live in
``app.domain.rate_limit``; this module owns only the mutable counters.

The handshake budget is deliberately separate from the HTTP request budget.
Socket churn must not consume the requests an inventory write needs, and the
HTTP limit's 60-per-second calibration is far too loose for connection setup.

State is safe without a lock under the repository's single-worker deployment:
both entry points are synchronous and run on the one application event loop, so
neither can interleave halfway through a counter update. N3 remains the trigger
for revisiting this when a second worker or instance is introduced.
"""

from collections import deque
from typing import TYPE_CHECKING

from app.domain import realtime as policy
from app.domain.rate_limit import (
    is_over_limit,
    retry_after_seconds,
    window_start,
)

if TYPE_CHECKING:
    from app.services.realtime import Connection


# Sweep no more than once per handshake window. The common path stays O(1),
# while the next attempt after an idle period removes every expired caller.
SWEEP_INTERVAL_SECONDS = policy.HANDSHAKE_WINDOW_SECONDS

# Caller key -> accepted attempt timestamps still inside the window.
# Each deque is bounded at HANDSHAKE_MAX_ATTEMPTS because rejected attempts are
# not appended.
_handshake_buckets: dict[str, deque[float]] = {}
_last_handshake_sweep = 0.0


def _sweep_handshakes(now: float) -> None:
    """Discard caller buckets with no attempt left in the active window."""
    global _last_handshake_sweep
    if now - _last_handshake_sweep < SWEEP_INTERVAL_SECONDS:
        return

    _last_handshake_sweep = now
    cutoff = window_start(now, policy.HANDSHAKE_WINDOW_SECONDS)
    for key in [
        key
        for key, seen in _handshake_buckets.items()
        if not seen or seen[-1] <= cutoff
    ]:
        del _handshake_buckets[key]


def check_handshake_and_record(key: str, now: float) -> int | None:
    """Count one same-origin handshake attempt.

    Return ``None`` while the attempt may proceed, or whole ``Retry-After``
    seconds when it must be refused. A refusal is not recorded: otherwise a
    reconnect loop could extend its own one-minute lockout indefinitely.
    """
    _sweep_handshakes(now)

    seen = _handshake_buckets.get(key)
    if seen is None:
        seen = _handshake_buckets[key] = deque()

    cutoff = window_start(now, policy.HANDSHAKE_WINDOW_SECONDS)
    while seen and seen[0] <= cutoff:
        seen.popleft()

    if is_over_limit(len(seen), policy.HANDSHAKE_MAX_ATTEMPTS):
        return retry_after_seconds(
            seen[0],
            now,
            policy.HANDSHAKE_WINDOW_SECONDS,
        )

    seen.append(now)
    return None


def inbound_frame_allowed(connection: "Connection", now: float) -> bool:
    """Count one acceptable-size application frame for ``connection``.

    The deque lives on the connection, so it disappears automatically when
    the endpoint deregisters that connection. A rejected frame is not appended;
    the endpoint closes immediately, but keeping the state bounded makes this
    function safe and honest even when exercised directly in tests.
    """
    seen = connection.inbound_frames
    cutoff = window_start(now, policy.INBOUND_WINDOW_SECONDS)
    while seen and seen[0] <= cutoff:
        seen.popleft()

    if is_over_limit(len(seen), policy.INBOUND_MAX_FRAMES):
        return False

    seen.append(now)
    return True


def reset() -> None:
    """Discard handshake counters. Test-only process-global cleanup."""
    global _last_handshake_sweep
    _handshake_buckets.clear()
    _last_handshake_sweep = 0.0
