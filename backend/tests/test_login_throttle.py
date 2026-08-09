"""Pure tests for the login throttle policy (no database).

`domain.login_throttle` is deliberately I/O-free so the backoff curve
can be pinned exactly, including the two properties that make it safe:
a free window wide enough that ordinary mistyping is never punished, and
a ceiling so the delay cannot grow without bound.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import timedelta

import pytest

from app.domain.login_throttle import (
    BASE_DELAY,
    FREE_ATTEMPTS,
    MAX_DELAY,
    lock_duration,
    user_ip_key,
)


@pytest.mark.parametrize("count", [0, 1, 2, 3, 4, 5])
def test_free_window_is_never_delayed(count):
    assert count <= FREE_ATTEMPTS
    assert lock_duration(count) == timedelta(0)


def test_first_failure_past_the_window_uses_base_delay():
    assert lock_duration(FREE_ATTEMPTS + 1) == BASE_DELAY


def test_delay_doubles_each_further_failure():
    assert lock_duration(FREE_ATTEMPTS + 2) == BASE_DELAY * 2
    assert lock_duration(FREE_ATTEMPTS + 3) == BASE_DELAY * 4
    assert lock_duration(FREE_ATTEMPTS + 4) == BASE_DELAY * 8


def test_delay_is_clamped_at_max():
    # Far past the point where doubling would exceed the ceiling.
    assert lock_duration(FREE_ATTEMPTS + 20) == MAX_DELAY
    assert lock_duration(10_000) == MAX_DELAY


def test_delay_is_monotonic():
    previous = timedelta(0)
    for count in range(0, 40):
        current = lock_duration(count)
        assert current >= previous
        previous = current


def test_concrete_curve():
    """Documented schedule, so a change to the constants is visible in a
    failing test rather than silently altering floor behavior."""
    assert lock_duration(6) == timedelta(seconds=5)
    assert lock_duration(7) == timedelta(seconds=10)
    assert lock_duration(8) == timedelta(seconds=20)
    assert lock_duration(9) == timedelta(seconds=40)


def test_key_normalizes_username_case_and_whitespace():
    assert user_ip_key("  Alice ", "1.2.3.4") == user_ip_key("alice", "1.2.3.4")


def test_key_separates_users_on_one_ip():
    """The anti-DoS property: one user's failures must not throttle
    another user coming from the same address."""
    assert user_ip_key("alice", "1.2.3.4") != user_ip_key("bob", "1.2.3.4")


def test_key_separates_ips_for_one_user():
    """A remote attacker hammering a known username must not lock out
    that user at their own device."""
    assert user_ip_key("alice", "1.2.3.4") != user_ip_key("alice", "5.6.7.8")
