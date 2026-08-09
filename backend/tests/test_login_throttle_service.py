"""Database integration tests for the login throttle service.

Covers the counting/locking behavior and, most importantly, the
isolation properties that keep the throttle from becoming a
denial-of-service weapon against the crew. Skips if no DB is reachable.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.errors import LoginThrottledError
from app.domain.login_throttle import FREE_ATTEMPTS, user_ip_key
from app.models import LoginAttempt
from app.services import login_throttle

IP = "203.0.113.7"


def _user():
    """A distinct username per test -- counters are keyed on the string,
    and the fixture's rollback does not isolate concurrent runs."""
    return f"u-{uuid.uuid4().hex[:10]}"


def _row(db, username, ip=IP):
    return (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.scope == login_throttle.SCOPE_USER_IP,
            LoginAttempt.key == user_ip_key(username, ip),
        )
        .one()
    )


def test_free_window_does_not_lock(db):
    username = _user()
    for _ in range(FREE_ATTEMPTS):
        login_throttle.record_failure(db, username=username, ip=IP)
        # Must not raise anywhere inside the free window.
        login_throttle.check(db, username=username, ip=IP)

    assert _row(db, username).failure_count == FREE_ATTEMPTS
    assert _row(db, username).locked_until is None


def test_lock_engages_past_the_free_window(db):
    username = _user()
    for _ in range(FREE_ATTEMPTS + 1):
        login_throttle.record_failure(db, username=username, ip=IP)

    with pytest.raises(LoginThrottledError) as excinfo:
        login_throttle.check(db, username=username, ip=IP)
    assert excinfo.value.retry_after_seconds > 0


def test_success_clears_the_counter(db):
    username = _user()
    for _ in range(FREE_ATTEMPTS + 1):
        login_throttle.record_failure(db, username=username, ip=IP)

    login_throttle.clear(db, username=username, ip=IP)

    # No row, no lock -- the next failure starts from scratch.
    login_throttle.check(db, username=username, ip=IP)
    assert (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.scope == login_throttle.SCOPE_USER_IP,
            LoginAttempt.key == user_ip_key(username, IP),
        )
        .first()
        is None
    )


def test_lock_lapses_once_the_window_passes(db):
    username = _user()
    for _ in range(FREE_ATTEMPTS + 1):
        login_throttle.record_failure(db, username=username, ip=IP)

    # Backdate the lock rather than sleeping out the real delay.
    row = _row(db, username)
    row.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.flush()

    login_throttle.check(db, username=username, ip=IP)


def test_one_user_cannot_lock_out_another_on_the_same_ip(db):
    """The reason this is backoff keyed on (username, IP) rather than
    account lockout: an attacker who knows the crew's usernames must not
    be able to lock them all out."""
    victim = _user()
    attacker_target = _user()

    for _ in range(FREE_ATTEMPTS + 5):
        login_throttle.record_failure(db, username=attacker_target, ip=IP)

    with pytest.raises(LoginThrottledError):
        login_throttle.check(db, username=attacker_target, ip=IP)

    # The other account, same address, is unaffected.
    login_throttle.check(db, username=victim, ip=IP)


def test_same_user_from_another_ip_is_unaffected(db):
    """A remote attacker hammering a known username must not lock that
    user out at their own device."""
    username = _user()
    for _ in range(FREE_ATTEMPTS + 5):
        login_throttle.record_failure(db, username=username, ip="198.51.100.9")

    with pytest.raises(LoginThrottledError):
        login_throttle.check(db, username=username, ip="198.51.100.9")

    login_throttle.check(db, username=username, ip=IP)


def test_username_matching_is_case_insensitive(db):
    username = _user()
    for _ in range(FREE_ATTEMPTS + 1):
        login_throttle.record_failure(db, username=username.upper(), ip=IP)

    with pytest.raises(LoginThrottledError):
        login_throttle.check(db, username=username.lower(), ip=IP)


def test_per_ip_layer_is_off_by_default(db, monkeypatch):
    """Off unless explicitly enabled, because it is the layer that would
    throttle the whole crew as one client if proxy headers were wrong."""
    monkeypatch.delenv("LOGIN_THROTTLE_PER_IP", raising=False)
    assert login_throttle.per_ip_enabled() is False

    # Enough failures across many usernames to trip a per-IP window.
    for _ in range(login_throttle.PER_IP_FREE_ATTEMPTS + 5):
        login_throttle.record_failure(db, username=_user(), ip=IP)

    # A fresh username from that IP still gets through.
    login_throttle.check(db, username=_user(), ip=IP)


def test_per_ip_layer_locks_when_enabled(db, monkeypatch):
    monkeypatch.setenv("LOGIN_THROTTLE_PER_IP", "true")
    assert login_throttle.per_ip_enabled() is True

    ip = "198.51.100.44"
    for _ in range(login_throttle.PER_IP_FREE_ATTEMPTS + 1):
        login_throttle.record_failure(db, username=_user(), ip=ip)

    with pytest.raises(LoginThrottledError):
        login_throttle.check(db, username=_user(), ip=ip)


def test_sweep_drops_stale_counters(db):
    username = _user()
    login_throttle.record_failure(db, username=username, ip=IP)

    row = _row(db, username)
    row.last_failed_at = datetime.now(timezone.utc) - timedelta(days=2)
    db.flush()

    login_throttle.sweep(db)
    db.commit()

    assert (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.scope == login_throttle.SCOPE_USER_IP,
            LoginAttempt.key == user_ip_key(username, IP),
        )
        .first()
        is None
    )
