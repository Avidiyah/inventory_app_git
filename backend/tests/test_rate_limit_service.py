"""Tests for the in-memory rate limit counters.

Layer: unit (no DB). `services.rate_limit` takes `now` as an argument
rather than reading a clock, so the whole sliding window is exercised
deterministically -- no sleeping, no flakiness.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.domain.rate_limit import MAX_REQUESTS, WINDOW_SECONDS
from app.services import rate_limit


@pytest.fixture(autouse=True)
def _clean_counters():
    # Module state is process global; without this a filled bucket would
    # leak into the next test.
    rate_limit.reset()
    yield
    rate_limit.reset()


def _fill(key, now, count=MAX_REQUESTS):
    for _ in range(count):
        assert rate_limit.check_and_record(key, now) is None


# --------------------------------------------------------------------------
# The cap
# --------------------------------------------------------------------------

def test_the_first_max_requests_are_allowed():
    _fill("s:abc", now=1000.0)


def test_the_next_request_is_refused():
    _fill("s:abc", now=1000.0)
    assert rate_limit.check_and_record("s:abc", 1000.0) == 1


def test_a_refused_request_is_not_counted():
    """The property that keeps a one-second limit from becoming an
    unbounded lockout: a client already looping must not be able to hold
    its own window open by continuing to hammer."""
    _fill("s:abc", now=1000.0)
    for _ in range(500):
        assert rate_limit.check_and_record("s:abc", 1000.0) == 1

    # The original 60 age out on schedule despite the 500 rejections in
    # between. Had rejections been recorded, this would still be refused.
    assert rate_limit.check_and_record("s:abc", 1000.0 + WINDOW_SECONDS + 0.001) is None


# --------------------------------------------------------------------------
# The window slides
# --------------------------------------------------------------------------

def test_the_budget_returns_after_the_window():
    _fill("s:abc", now=1000.0)
    assert rate_limit.check_and_record("s:abc", 1000.5) == 1
    assert rate_limit.check_and_record("s:abc", 1001.001) is None


def test_the_window_slides_rather_than_resetting_on_a_fixed_boundary():
    # 60 requests spread across the second, then one more just after the
    # first has aged out: allowed, because only that one freed up.
    for index in range(MAX_REQUESTS):
        assert rate_limit.check_and_record("s:abc", 1000.0 + index * 0.01) is None

    # 1000.0 has aged out at 1001.001, so there is room for exactly one.
    assert rate_limit.check_and_record("s:abc", 1001.001) is None
    # 1000.01 has not aged out yet, so the next is refused.
    assert rate_limit.check_and_record("s:abc", 1001.001) == 1


# --------------------------------------------------------------------------
# Callers are isolated -- this is the whole reason the cap is per caller
# --------------------------------------------------------------------------

def test_one_caller_cannot_spend_another_callers_budget():
    _fill("s:abc", now=1000.0)
    assert rate_limit.check_and_record("s:abc", 1000.0) == 1
    assert rate_limit.check_and_record("s:other", 1000.0) is None


# --------------------------------------------------------------------------
# Keying
# --------------------------------------------------------------------------

def test_a_session_token_is_never_used_as_the_key_verbatim():
    # X1 hashed session tokens in the database for this reason; a raw
    # token in a process-wide dict is the same live credential sitting
    # somewhere a repr or a debugger dump could surface it.
    key = rate_limit.caller_key("super-secret-token", "1.2.3.4")
    assert "super-secret-token" not in key
    assert key.startswith("s:")


def test_distinct_sessions_get_distinct_keys():
    assert rate_limit.caller_key("token-a", "1.2.3.4") != rate_limit.caller_key(
        "token-b", "1.2.3.4"
    )


def test_the_same_session_gets_the_same_key_from_a_different_address():
    # Keying on the session rather than the address means a phone moving
    # between wifi and cellular keeps one budget instead of gaining a
    # second one mid-request.
    assert rate_limit.caller_key("token-a", "1.2.3.4") == rate_limit.caller_key(
        "token-a", "5.6.7.8"
    )


def test_an_unauthenticated_caller_falls_back_to_the_address():
    key = rate_limit.caller_key(None, "1.2.3.4")
    assert key == "i:1.2.3.4"


def test_an_authenticated_caller_never_collides_with_an_address():
    # The prefixes exist so a session digest can never be confused with
    # an IP-shaped key.
    assert rate_limit.caller_key("token", "1.2.3.4") != rate_limit.caller_key(
        None, "1.2.3.4"
    )


# --------------------------------------------------------------------------
# The counters stay bounded
# --------------------------------------------------------------------------

def test_idle_keys_are_swept():
    _fill("s:abc", now=1000.0)
    assert rate_limit._buckets

    # Far enough ahead that the sweep interval has elapsed and the key
    # holds nothing inside the window.
    rate_limit.check_and_record("s:new", 1000.0 + rate_limit.SWEEP_INTERVAL_SECONDS + 1)
    assert "s:abc" not in rate_limit._buckets


def test_an_active_key_survives_a_sweep():
    _fill("s:abc", now=1000.0)
    later = 1000.0 + rate_limit.SWEEP_INTERVAL_SECONDS + 1
    # Active means "has a request inside the window", not "was seen recently".
    rate_limit.check_and_record("s:abc", later)
    rate_limit.check_and_record("s:other", later)
    assert "s:abc" in rate_limit._buckets


def test_a_bucket_never_grows_past_the_cap():
    # The memory bound: pruning happens before each append and an
    # over-limit request is never appended, so one key holds at most
    # MAX_REQUESTS floats no matter how hard it is hammered.
    for _ in range(1000):
        rate_limit.check_and_record("s:abc", 1000.0)
    assert len(rate_limit._buckets["s:abc"]) == MAX_REQUESTS
