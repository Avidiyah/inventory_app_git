"""Structured logging: formatter, request context, and root configuration.

Layer: infrastructure. This is the single place that knows how a log
line is shaped and where it goes. Everything else in the application
uses a plain `logging.getLogger(__name__)` and passes structured data
as `extra={"fields": {...}}` -- no logger is threaded through any
function signature.

Output is **logfmt** (`key=value`, space separated) on stdout, which the
deployment platform captures. Every line begins with the same four keys
so a stream can be scanned by eye or filtered with `grep req=<id>`:

    ts=2026-08-09T14:02:11.318Z level=ERROR req=a3f9c1d20e77 event=... k=v

Two things are deliberate and easy to get wrong if this is ever edited:

1. **The formatter reads the context variable directly** rather than
   stamping records through a `logging.Filter`. A filter attached to a
   handler is skipped by any other handler (pytest's `caplog`, for one),
   and a filter attached to a logger does *not* run for records that
   propagate up from child loggers. Reading at format time has neither
   hole.
2. **The context variable holds a mutable dict, which is mutated in
   place.** Starlette's `BaseHTTPMiddleware` runs the downstream app in a
   separate anyio task, and a task gets a *copy* of the context -- so a
   `ContextVar.set()` inside a route dependency is invisible to the
   middleware that spawned it. Both tasks do share the same dict object,
   so mutating it (see `bind_user`) is what lets the request-completion
   line know who the caller turned out to be.

Never logged, anywhere: passwords, session tokens (raw or hashed), the
`Cookie` header, request bodies, query strings, and the database URL.
"""

import logging
import os
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

# Verbosity is configuration, not code -- `render.yaml` pins it, matching
# how COOKIE_SECURE and SQL_ECHO are handled. An unrecognised value falls
# back to INFO rather than crashing the process at import: a typo in an
# env var should not take the service down.
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()

# Placeholder for a key with no value, so column positions stay stable
# for anything reading the stream by eye.
_ABSENT = "-"

# Per-request data stamped onto every line. The default is a module-level
# empty dict that is never mutated -- outside a request (startup, tests,
# scripts) there is simply nothing to add.
_EMPTY: dict[str, Any] = {}
request_context: ContextVar[dict[str, Any]] = ContextVar(
    "request_context", default=_EMPTY
)


def _fmt_value(value: Any) -> str:
    """Render one logfmt value, quoting and escaping when it would
    otherwise break the `key=value` framing.

    This is the one bug surface logfmt has that JSON does not, which is
    why it is a separate function with its own tests. A bare value is
    left alone; anything empty or containing a space, quote, `=`, or
    control whitespace is wrapped in double quotes with `\\`, `"`, and
    the whitespace characters escaped.
    """
    if value is None:
        return _ABSENT

    text = str(value)
    if text and not any(char in text for char in ' "=\\\n\r\t'):
        return text

    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


class LogfmtFormatter(logging.Formatter):
    """Render a record as a single logfmt line.

    The record's *message* is the event name -- `logger.info("auth.login_ok")`
    -- and structured data rides in `extra={"fields": {...}}`. Formatting
    the message this way rather than as prose is what makes the stream
    filterable: `grep event=auth.login_failed` is a complete query.

    An exception, when present, is appended as an indented traceback on
    following lines. That breaks one-line-per-record, which is the point:
    a traceback is unreadable escaped onto a single line, and the header
    line above it still carries the request id needed to correlate it.
    """

    def format(self, record: logging.LogRecord) -> str:
        context = request_context.get()

        pairs: list[tuple[str, Any]] = [
            ("ts", self._timestamp(record)),
            ("level", record.levelname),
            ("req", context.get("req", _ABSENT)),
        ]

        user = context.get("user")
        if user is not None:
            pairs.append(("user_id", user))

        pairs.append(("event", record.getMessage()))

        fields = getattr(record, "fields", None)
        if fields:
            pairs.extend(fields.items())

        line = " ".join(f"{key}={_fmt_value(value)}" for key, value in pairs)

        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"

        return line

    @staticmethod
    def _timestamp(record: logging.LogRecord) -> str:
        """UTC ISO-8601 to milliseconds. Explicitly UTC rather than local
        time: the container, the platform's log viewer, and whoever reads
        it are rarely in the same zone."""
        moment = datetime.fromtimestamp(record.created, timezone.utc)
        return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


_configured = False


def configure_logging() -> None:
    """Attach the logfmt handler to the root logger. Idempotent.

    Called once from `app.main` at import. The guard matters because
    `app.main` is imported by the test suite as well as by uvicorn, and a
    second handler would double every line.

    Existing root handlers are deliberately **left in place** rather than
    cleared: under pytest, `caplog` installs its own, and clearing would
    silently break log capture in every test that uses it.

    Uvicorn's own loggers (`uvicorn.error`, `uvicorn.access`) are
    untouched. Uvicorn configures them with `propagate=False` and its own
    handlers, so they neither route through this formatter nor duplicate
    into it -- its access log stays on, alongside the richer
    `event=request` line this app emits.
    """
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(LogfmtFormatter())

    root = logging.getLogger()
    root.addHandler(handler)

    level = logging.getLevelName(LOG_LEVEL)
    root.setLevel(level if isinstance(level, int) else logging.INFO)

    _configured = True


def new_request_context(request_id: str) -> dict[str, Any]:
    """Build a fresh context dict for one request.

    Deliberately does not install it: the caller (the middleware in
    `app.main`) needs the token from `request_context.set` so it can
    reset the variable in a `finally`, and it needs the dict itself so it
    can read back whatever a downstream dependency added.
    """
    return {"req": request_id}


def bind_user(user_id: Any) -> None:
    """Record the authenticated user on the current request scope.

    Mutates the dict in place rather than calling `request_context.set`.
    See the module docstring: a `set` here happens in the route's task and
    would never reach the middleware that logs the completion line.

    A no-op outside a request scope, so importing this into a script or a
    test cannot raise.
    """
    context = request_context.get()
    if context is not _EMPTY:
        context["user"] = user_id
