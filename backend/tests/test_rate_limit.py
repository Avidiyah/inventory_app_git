"""Pure tests for the request rate limit policy (no database).

`domain.rate_limit` is deliberately I/O-free so the cap, the window and
the exemption list can be pinned exactly -- including the two properties
that keep the limiter from becoming the outage it exists to prevent: the
SPA's own asset traffic is outside it, and so is the deploy health check.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.domain import rate_limit
from app.domain.rate_limit import (
    MAX_REQUESTS,
    WINDOW_SECONDS,
    is_exempt,
    is_over_limit,
    retry_after_seconds,
    window_start,
)


# --------------------------------------------------------------------------
# The cap
# --------------------------------------------------------------------------

def test_the_cap_is_sixty_per_second():
    assert MAX_REQUESTS == 60
    assert WINDOW_SECONDS == 1.0


@pytest.mark.parametrize("count", [0, 1, MAX_REQUESTS - 2, MAX_REQUESTS - 1])
def test_below_the_cap_is_allowed(count):
    assert not is_over_limit(count)


def test_exactly_max_requests_succeed_before_one_is_refused():
    # The boundary that decides whether the app allows 60 or 59: the
    # count passed in is of *already recorded* requests, so the 60th
    # arrival sees 59 and is allowed, and the 61st sees 60 and is not.
    assert not is_over_limit(MAX_REQUESTS - 1)
    assert is_over_limit(MAX_REQUESTS)


def test_over_the_cap_stays_over():
    assert is_over_limit(MAX_REQUESTS + 100)


# --------------------------------------------------------------------------
# The window
# --------------------------------------------------------------------------

def test_window_start_is_one_second_back():
    assert window_start(1000.0) == 999.0


def test_retry_after_is_never_zero():
    # A request that has only just entered the window frees up in a
    # fraction of a second; reporting 0 would invite an immediate retry
    # that just fails again.
    assert retry_after_seconds(oldest_in_window=999.99, now=1000.0) == 1


def test_retry_after_rounds_up():
    assert retry_after_seconds(oldest_in_window=999.5, now=1000.0) == 1


# --------------------------------------------------------------------------
# Exemptions -- the properties that keep this from breaking the app
# --------------------------------------------------------------------------

def test_the_spa_shell_is_exempt():
    assert is_exempt("/")


def test_every_static_asset_is_exempt():
    # A cold load pulls the 33-module ES graph, styles.css and the
    # 441 KB vendor bundle nearly at once. Counting those would let two
    # page loads exhaust a 60/s budget and serve a 429 for a JavaScript
    # module, which renders as a blank page.
    assert is_exempt("/static/styles.css")
    assert is_exempt("/static/main.js")
    assert is_exempt("/static/vendor/zxing-browser-0.2.0.umd.min.js")


def test_the_health_check_is_exempt():
    # render.yaml points healthCheckPath at /healthz, so a 429 here
    # would fail a deploy rather than protect one.
    assert is_exempt("/healthz")


def test_the_shell_is_matched_exactly_rather_than_as_a_prefix():
    # "/" as a prefix would exempt the entire application.
    assert not is_exempt("/items/")
    assert not is_exempt("/work-orders/")


@pytest.mark.parametrize(
    "path",
    ["/items/", "/work-orders/", "/transactions/", "/auth/login", "/tools/"],
)
def test_api_routes_are_not_exempt(path):
    assert not is_exempt(path)


def test_a_path_merely_starting_with_static_is_not_exempt():
    # The prefix carries its trailing slash on purpose: a future route
    # named e.g. /static-report must not inherit the asset exemption.
    assert not is_exempt("/static-report")


# --- parameterized reuse (real-time inbound frame limiting) -------------
#
# The socket's inbound limiter is a second *policy* over the same *rule*.
# These cases pin the parameterized form so the two policies can never
# drift apart -- in particular the off-by-one, which is the reason the
# design forbids forking this module.


def test_window_start_accepts_a_custom_window():
    assert rate_limit.window_start(100.0, window_seconds=60.0) == 40.0


def test_window_start_defaults_to_the_http_window():
    assert rate_limit.window_start(100.0) == 100.0 - rate_limit.WINDOW_SECONDS


def test_is_over_limit_accepts_a_custom_cap():
    assert rate_limit.is_over_limit(19, max_requests=20) is False
    assert rate_limit.is_over_limit(20, max_requests=20) is True


def test_custom_cap_preserves_the_off_by_one():
    """Exactly `max_requests` must succeed, not `max_requests - 1`.

    This is the specific bug a forked copy would risk reintroducing.
    """
    allowed = sum(
        1 for count in range(10) if not rate_limit.is_over_limit(count, max_requests=10)
    )
    assert allowed == 10


def test_retry_after_accepts_a_custom_window():
    assert rate_limit.retry_after_seconds(100.0, 130.0, window_seconds=60.0) == 30


def test_retry_after_never_reports_zero_with_a_custom_window():
    assert rate_limit.retry_after_seconds(100.0, 160.0, window_seconds=60.0) == 1
