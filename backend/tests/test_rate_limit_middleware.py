"""Tests for the rate limit middleware as it is actually wired.

Layer: unit (no DB, no HTTP client). Drives the ASGI stack directly --
the pattern N1 established for middleware, and the one that respects the
project's "do not start the dev server" rule while still proving the real
composition rather than a helper in isolation.

`/does-not-exist` is used as the representative API path throughout: it
is not exempt, so it is counted, and it routes to a 404 without touching
the database. That isolates the limiter from every other concern -- a
test that needed a real route would be testing auth and Postgres too.

The clock is stubbed rather than slept on. `main` calls `time.monotonic`
through its own module reference, so replacing `main.time` pins the
window deterministically instead of racing a real second.
"""

import asyncio
import os
import sys
import time as real_time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app import main
from app.domain.rate_limit import MAX_REQUESTS
from app.services import rate_limit

FROZEN = 1000.0


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch):
    rate_limit.reset()
    # perf_counter is passed through: log_request uses it for `ms=` and
    # has nothing to do with the window under test.
    monkeypatch.setattr(
        main,
        "time",
        SimpleNamespace(monotonic=lambda: FROZEN, perf_counter=real_time.perf_counter),
    )
    yield
    rate_limit.reset()


def call(path, cookie=None, ip="1.2.3.4"):
    """One GET through the whole middleware stack. Returns
    (status, headers)."""
    headers = [(b"host", b"test")]
    if cookie is not None:
        headers.append((b"cookie", f"session={cookie}".encode()))

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "path": path, "raw_path": path.encode(),
        "query_string": b"", "root_path": "", "scheme": "http",
        "headers": headers, "client": (ip, 1234), "server": ("test", 80),
    }
    captured = {}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
            captured["headers"] = {
                k.decode().lower(): v.decode() for k, v in message["headers"]
            }

    asyncio.run(main.app(scope, receive, send))
    return captured["status"], captured["headers"]


def _exhaust(cookie="token-a"):
    for _ in range(MAX_REQUESTS):
        status, _ = call("/does-not-exist", cookie=cookie)
        assert status != 429


# --------------------------------------------------------------------------
# The cap, end to end
# --------------------------------------------------------------------------

def test_an_api_route_is_refused_past_the_cap():
    _exhaust()
    status, _ = call("/does-not-exist", cookie="token-a")
    assert status == 429


def test_the_refusal_carries_retry_after():
    _exhaust()
    _, headers = call("/does-not-exist", cookie="token-a")
    assert headers["retry-after"] == "1"


# --------------------------------------------------------------------------
# Exempt paths -- measured behaviour, not just the policy function
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path", ["/", "/healthz", "/static/styles.css", "/static/main.js"]
)
def test_exempt_paths_never_count_toward_the_cap(path):
    # 200 requests -- more than three times the cap -- must not arm the
    # limiter, or a page refresh could lock a user out of the API.
    for _ in range(200):
        call(path, cookie="token-a")
    status, _ = call("/does-not-exist", cookie="token-a")
    assert status != 429


def test_an_over_limit_caller_can_still_load_the_spa():
    """The property that keeps a runaway client recoverable: whatever
    else is refused, the page that fixes it still loads."""
    _exhaust()
    assert call("/does-not-exist", cookie="token-a")[0] == 429

    assert call("/", cookie="token-a")[0] == 200
    assert call("/static/styles.css", cookie="token-a")[0] == 200


def test_an_over_limit_caller_does_not_break_the_deploy_health_check():
    # render.yaml points healthCheckPath at /healthz. If the limiter
    # could refuse it, a busy caller could fail an unrelated deploy.
    _exhaust()
    assert call("/does-not-exist", cookie="token-a")[0] == 429
    assert call("/healthz", cookie="token-a")[0] != 429


# --------------------------------------------------------------------------
# Callers are isolated
# --------------------------------------------------------------------------

def test_one_session_cannot_lock_out_another():
    _exhaust(cookie="token-a")
    assert call("/does-not-exist", cookie="token-a")[0] == 429
    assert call("/does-not-exist", cookie="token-b")[0] != 429


def test_one_session_cannot_lock_out_an_anonymous_caller():
    _exhaust(cookie="token-a")
    assert call("/does-not-exist", cookie="token-a")[0] == 429
    assert call("/does-not-exist", cookie=None)[0] != 429


def test_the_same_session_is_limited_across_addresses():
    # Keyed on the session, so moving networks does not grant a second
    # budget mid-loop.
    for _ in range(MAX_REQUESTS):
        assert call("/does-not-exist", cookie="token-a", ip="1.2.3.4")[0] != 429
    assert call("/does-not-exist", cookie="token-a", ip="5.6.7.8")[0] == 429


# --------------------------------------------------------------------------
# Middleware ordering -- the reason this file exists rather than only the
# service test. Both assertions fail if the registration order is changed.
# --------------------------------------------------------------------------

def test_a_refusal_still_carries_the_security_headers():
    # Proves add_security_headers wraps the limiter. A 429 served without
    # the CSP would be the one response in the app missing it.
    _exhaust()
    _, headers = call("/does-not-exist", cookie="token-a")
    assert headers["content-security-policy"] == main.CONTENT_SECURITY_POLICY
    assert headers["x-frame-options"] == "DENY"


def test_a_refusal_still_carries_a_request_id():
    # Proves log_request wraps the limiter, which is what puts refusals
    # in the log stream. A limiter whose rejections were invisible would
    # be the hardest thing in the app to diagnose.
    _exhaust()
    _, headers = call("/does-not-exist", cookie="token-a")
    assert len(headers["x-request-id"]) == 12
