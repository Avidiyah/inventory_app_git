"""Tests for structured logging (`app/logging_config.py`) and its three
call sites.

Layer: unit (no DB, no HTTP client). Matches the "pure, call the handler
directly" style of `test_health_check.py` and `test_route_role_gates.py`
-- everything that would touch Postgres is monkeypatched, so these run
without a reachable database.

Most of these are regression guards rather than behavior tests, and the
two that matter most are the leak guards:

- `test_a_password_typed_into_the_username_field_is_not_logged` -- the
  entire reason `username_exists` exists. If failed logins ever start
  logging the submitted string verbatim, this is what catches it.
- `test_healthz_logs_the_driver_error_but_the_response_still_does_not` --
  B2 withholds the driver's error from an anonymous caller and N1 logs it
  server-side. Both halves have to stay true at once.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app import logging_config, main
from app.domain.errors import InvalidCredentialsError, LoginThrottledError
from app.logging_config import LogfmtFormatter, _fmt_value, request_context
from app.routers import auth as auth_router
from app.schemas.auth import LoginRequest


# --------------------------------------------------------------------------
# logfmt rendering
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value, expected",
    [
        ("plain", "plain"),
        ("with space", '"with space"'),
        ('has "quotes"', '"has \\"quotes\\""'),
        ("key=value", '"key=value"'),
        ("back\\slash", '"back\\\\slash"'),
        ("line\nbreak", '"line\\nbreak"'),
        ("tab\there", '"tab\\there"'),
        ("", '""'),
        (None, "-"),
        (42, "42"),
    ],
)
def test_fmt_value_quotes_only_what_would_break_the_framing(value, expected):
    assert _fmt_value(value) == expected


def _format(record: logging.LogRecord) -> str:
    return LogfmtFormatter().format(record)


def _record(message: str, **fields) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=message, args=(), exc_info=None,
    )
    if fields:
        record.fields = fields
    return record


def test_a_line_outside_a_request_still_renders_with_a_placeholder():
    line = _format(_record("startup.ready"))

    assert " level=INFO " in line
    assert " req=- " in line
    assert line.endswith("event=startup.ready")
    assert "user_id=" not in line


def test_fields_are_appended_after_the_event():
    line = _format(_record("request", method="GET", path="/items/", status=200))

    assert line.endswith("event=request method=GET path=/items/ status=200")


def test_the_timestamp_is_utc_to_the_millisecond():
    line = _format(_record("x"))
    timestamp = line.split(" ", 1)[0].removeprefix("ts=")

    # 2026-08-09T14:02:11.318Z
    assert timestamp.endswith("Z")
    assert len(timestamp) == len("2026-08-09T14:02:11.318Z")


# --------------------------------------------------------------------------
# Request context
# --------------------------------------------------------------------------

def test_a_bound_request_id_reaches_the_formatted_line():
    token = request_context.set(logging_config.new_request_context("a3f9c1d20e77"))
    try:
        line = _format(_record("request"))
    finally:
        request_context.reset(token)

    assert "req=a3f9c1d20e77" in line


def test_current_request_id_reads_the_active_scope_and_is_safe_without_one():
    assert logging_config.current_request_id() is None

    token = request_context.set(logging_config.new_request_context("current-request"))
    try:
        assert logging_config.current_request_id() == "current-request"
    finally:
        request_context.reset(token)


def test_current_request_id_treats_a_context_without_req_as_unbound():
    token = request_context.set({})
    try:
        assert logging_config.current_request_id() is None
    finally:
        request_context.reset(token)


def test_an_explicit_record_request_id_is_the_one_correlation_key():
    """Long-lived tasks carry causality as data, not request context.

    The formatter must replace the ambient value rather than append a second
    `req` field, or a delivery line becomes ambiguous to both humans and
    logfmt parsers.
    """
    token = request_context.set(logging_config.new_request_context("ambient-request"))
    try:
        record = _record(
            "realtime.delivered",
            connection_id="connection-1",
            user_id="user-1",
        )
        record.request_id = "originating-request"
        line = _format(record)
    finally:
        request_context.reset(token)

    assert "req=originating-request" in line
    assert "req=ambient-request" not in line
    assert "req=-" not in line
    assert line.count("req=") == 1


def test_bind_user_adds_the_id_to_an_active_scope():
    context = logging_config.new_request_context("a3f9c1d20e77")
    token = request_context.set(context)
    try:
        logging_config.bind_user(7)
        line = _format(_record("request"))
    finally:
        request_context.reset(token)

    assert "user_id=7" in line


def test_bind_user_mutates_in_place_rather_than_rebinding():
    # Not incidental. Starlette runs the downstream app in a separate
    # anyio task, which gets a *copy* of the context -- so a `.set()` in a
    # route dependency would never reach the middleware that logs the
    # completion line. Sharing one dict is what makes `user_id=` appear on
    # that line. If this ever becomes a `.set()`, the id silently vanishes
    # from the request line and nothing else fails.
    context = logging_config.new_request_context("a3f9c1d20e77")
    token = request_context.set(context)
    try:
        logging_config.bind_user(7)
        assert context["user"] == 7
        assert request_context.get() is context
    finally:
        request_context.reset(token)


def test_bind_user_outside_a_request_is_a_no_op():
    # Scripts and tests import this module without ever opening a request
    # scope; binding must not raise, and must not pollute the shared
    # module-level default dict for everything that follows.
    logging_config.bind_user(7)

    assert "user" not in request_context.get()


# --------------------------------------------------------------------------
# configure_logging
# --------------------------------------------------------------------------

def test_configure_logging_is_idempotent():
    # `app.main` already called it at import; a second call must not add a
    # second handler, or every line prints twice.
    before = len(logging.getLogger().handlers)

    logging_config.configure_logging()

    assert len(logging.getLogger().handlers) == before


def test_configure_logging_installs_exactly_one_logfmt_handler():
    formatters = [
        type(handler.formatter)
        for handler in logging.getLogger().handlers
        if isinstance(handler.formatter, LogfmtFormatter)
    ]

    assert formatters == [LogfmtFormatter]


# --------------------------------------------------------------------------
# /healthz -- the B2 follow-on
# --------------------------------------------------------------------------

LEAKY_DRIVER_ERROR = (
    'connection to server at "db.internal" (10.0.0.7), port 5432 failed: '
    'FATAL: password authentication failed for user "inventory" '
    'dbname=inventory'
)


def test_healthz_logs_the_driver_error_but_the_response_still_does_not(
    monkeypatch, caplog
):
    def unreachable():
        raise OperationalError("SELECT 1;", {}, Exception(LEAKY_DRIVER_ERROR))

    monkeypatch.setattr(main, "check_connection", unreachable)
    caplog.set_level(logging.ERROR)

    with pytest.raises(HTTPException) as exc:
        main.healthz()

    record = next(r for r in caplog.records if r.getMessage() == "healthz.db_unreachable")
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
    # Server-side: the detail is present, which is the point of the item.
    assert "db.internal" in caplog.text
    # Client-side: it still is not.
    assert "db.internal" not in str(exc.value.detail)


def test_healthz_success_logs_nothing(monkeypatch, caplog):
    monkeypatch.setattr(main, "check_connection", lambda: None)
    caplog.set_level(logging.DEBUG)

    main.healthz()

    # The platform polls this constantly; a line per poll would bury
    # everything else in the stream.
    assert [r for r in caplog.records if r.name == "app.main"] == []


# --------------------------------------------------------------------------
# Login events
# --------------------------------------------------------------------------

class _FakeClient:
    host = "10.0.0.7"


class _FakeRequest:
    client = _FakeClient()


def _attempt_login(monkeypatch, *, username, exists, password="hunter2"):
    """Drive `login()` to its failure path with the DB stubbed out."""
    monkeypatch.setattr(auth_router.login_throttle, "check", lambda *a, **k: None)
    monkeypatch.setattr(
        auth_router.login_throttle, "record_failure", lambda *a, **k: None
    )
    monkeypatch.setattr(
        auth_router.auth_service, "username_exists", lambda db, username: exists
    )

    def rejects(db, *, username, password):
        raise InvalidCredentialsError("Invalid username or password.")

    monkeypatch.setattr(auth_router.auth_service, "authenticate", rejects)

    payload = LoginRequest(username=username, password=password)
    with pytest.raises(HTTPException):
        auth_router.login(payload, _FakeRequest(), Response(), db=None)


def test_a_failed_login_against_a_real_account_logs_the_username(
    monkeypatch, caplog
):
    caplog.set_level(logging.WARNING)

    _attempt_login(monkeypatch, username="owner", exists=True)

    record = next(r for r in caplog.records if r.getMessage() == "auth.login_failed")
    assert record.fields["user"] == "owner"
    assert record.fields["ip"] == "10.0.0.7"


def test_a_password_typed_into_the_username_field_is_not_logged(
    monkeypatch, caplog
):
    # The failure this guards: a user types their password into the
    # username box. It matches no account, so it must never be echoed.
    secret = "correct-horse-battery-staple"
    caplog.set_level(logging.WARNING)

    _attempt_login(monkeypatch, username=secret, exists=False)

    record = next(r for r in caplog.records if r.getMessage() == "auth.login_failed")
    assert record.fields["user"] == auth_router.UNKNOWN_USER
    assert secret not in _format(record)
    assert secret not in caplog.text


def test_the_submitted_password_is_never_logged(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)

    _attempt_login(monkeypatch, username="owner", exists=True, password="s3cr3t-pw")

    assert "s3cr3t-pw" not in caplog.text


def test_a_throttled_login_is_logged_with_its_retry_window(monkeypatch, caplog):
    def throttled(*args, **kwargs):
        raise LoginThrottledError("Too many attempts.", retry_after_seconds=42)

    monkeypatch.setattr(auth_router.login_throttle, "check", throttled)
    monkeypatch.setattr(
        auth_router.auth_service, "username_exists", lambda db, username: True
    )
    caplog.set_level(logging.WARNING)

    payload = LoginRequest(username="owner", password="hunter2")
    with pytest.raises(HTTPException) as exc:
        auth_router.login(payload, _FakeRequest(), Response(), db=None)

    assert exc.value.status_code == 429
    record = next(r for r in caplog.records if r.getMessage() == "auth.login_throttled")
    assert record.fields["user"] == "owner"
    assert record.fields["retry_after"] == 42


# --------------------------------------------------------------------------
# memory sampling
# --------------------------------------------------------------------------

MB = 1024 * 1024


def _point_sampler_at(monkeypatch, tmp_path, *, statm=None, cgroup=()):
    """Redirect the sampler's file reads into tmp_path. `statm` is the
    whole /proc/self/statm line; `cgroup` is an ordered list of
    (filename, content) in fallback order, content None = file absent."""
    statm_path = tmp_path / "statm"
    if statm is not None:
        statm_path.write_text(statm)
    cgroup_paths = []
    for name, content in cgroup:
        path = tmp_path / name
        if content is not None:
            path.write_text(content)
        cgroup_paths.append(str(path))
    monkeypatch.setattr(logging_config, "_STATM_PATH", str(statm_path))
    monkeypatch.setattr(logging_config, "_CGROUP_PATHS", tuple(cgroup_paths))
    monkeypatch.setattr(logging_config, "_PAGE_SIZE", 4096)


def test_memory_sample_reads_rss_pages_and_cgroup_v2_bytes(monkeypatch, tmp_path):
    # statm: size resident shared text lib data dt -- resident is field 2.
    _point_sampler_at(
        monkeypatch, tmp_path,
        statm="9000 2560 100 1 0 200 0",
        cgroup=[("memory.current", str(300 * MB))],
    )

    assert logging_config.memory_sample() == {"rss_mb": 10, "cg_mb": 300}


def test_memory_sample_falls_back_to_cgroup_v1(monkeypatch, tmp_path):
    _point_sampler_at(
        monkeypatch, tmp_path,
        statm="9000 2560 100 1 0 200 0",
        cgroup=[("memory.current", None), ("memory.usage_in_bytes", str(123 * MB))],
    )

    assert logging_config.memory_sample()["cg_mb"] == 123


def test_memory_sample_is_absent_where_the_files_do_not_exist(monkeypatch, tmp_path):
    # Windows dev box: no /proc, no cgroup. Must not raise.
    _point_sampler_at(monkeypatch, tmp_path, statm=None, cgroup=[("memory.current", None)])

    assert logging_config.memory_sample() == {"rss_mb": None, "cg_mb": None}


def test_memory_sample_treats_garbage_as_absent(monkeypatch, tmp_path):
    _point_sampler_at(
        monkeypatch, tmp_path,
        statm="not numbers",
        cgroup=[("memory.current", "max\n")],
    )

    assert logging_config.memory_sample() == {"rss_mb": None, "cg_mb": None}


def _sampler_returning(monkeypatch, *samples):
    """Make `main.memory_sample` hand out the given dicts in order."""
    queue = iter(samples)
    monkeypatch.setattr(main, "memory_sample", lambda: next(queue))


def test_the_request_line_carries_memory_fields_and_the_cgroup_delta(monkeypatch, caplog):
    monkeypatch.setattr(main, "check_connection", lambda: None)
    _sampler_returning(
        monkeypatch,
        {"rss_mb": 80, "cg_mb": 300},
        {"rss_mb": 95, "cg_mb": 420},
    )
    caplog.set_level(logging.INFO)

    TestClient(main.app).get("/healthz")

    record = next(r for r in caplog.records if r.getMessage() == "request")
    assert record.fields["rss_mb"] == 95
    assert record.fields["cg_mb"] == 420
    assert record.fields["cg_delta_mb"] == 120
    # Logged as well: the cgroup file may be unreadable on some hosts, and
    # the RSS delta then remains as a sort key.
    assert record.fields["rss_delta_mb"] == 15


def test_the_request_line_survives_absent_memory_readings(monkeypatch, caplog):
    monkeypatch.setattr(main, "check_connection", lambda: None)
    _sampler_returning(
        monkeypatch,
        {"rss_mb": None, "cg_mb": None},
        {"rss_mb": None, "cg_mb": None},
    )
    caplog.set_level(logging.INFO)

    response = TestClient(main.app).get("/healthz")

    assert response.status_code == 200
    record = next(r for r in caplog.records if r.getMessage() == "request")
    assert record.fields["cg_delta_mb"] is None
    # The formatter renders None as the column placeholder, not "None".
    assert "cg_delta_mb=-" in LogfmtFormatter().format(record)


def test_the_error_line_carries_memory_fields(monkeypatch, caplog):
    def explode():
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "check_connection", explode)
    _sampler_returning(
        monkeypatch,
        {"rss_mb": 80, "cg_mb": 300},
        {"rss_mb": 80, "cg_mb": 480},
    )
    caplog.set_level(logging.ERROR)

    TestClient(main.app, raise_server_exceptions=False).get("/healthz")

    record = next(r for r in caplog.records if r.getMessage() == "request.error")
    assert record.fields["cg_delta_mb"] == 180
