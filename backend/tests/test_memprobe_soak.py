"""Host-side tests for scripts/memprobe_soak.py: parsing, jump finding,
rendering, reader-step selection and the thread loops against a fake
sender. No HTTP, no Docker, no database."""

import os
import sys
import threading
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import memprobe
from scripts import memprobe_soak as soak
from scripts.memprobe_routes import Plan, Step


def _req(ts, path="/healthz", cg=180, cgd=0, method="GET", req="r1", status=200, ms=3, rss=120):
    return (f"ts={ts} level=INFO req={req} event=request method={method} path={path} "
            f"status={status} ms={ms} rss_mb={rss} cg_mb={cg} cg_delta_mb={cgd} rss_delta_mb=0")


def _ts(seconds):
    return datetime(2026, 10, 14, 9, 0, seconds, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


# --- parser -----------------------------------------------------------------

def test_parse_lines_ignores_prefixes_and_lines_without_ts_or_event():
    text = "\n".join([
        "Oct 14 09:00:01 AM  " + _req(_ts(1)),                      # Render export prefix
        "2026-10-14T09:00:02.000Z " + _req(_ts(2)),                  # docker --timestamps prefix
        "INFO:     Application startup complete.",                   # uvicorn, no ts
        "ts=2026-10-14T09:00:03.000Z level=INFO msg=nothing",        # no event
        "ts=garbage event=request path=/x cg_mb=1",                  # unparsable ts
    ])
    lines = soak.parse_lines(text)
    assert [l.fields["path"] for l in lines] == ["/healthz", "/healthz"]
    assert lines[0].ts == datetime(2026, 10, 14, 9, 0, 1, tzinfo=timezone.utc)
    assert lines[0].event == "request"


def test_parse_lines_keeps_tokens_after_a_quoted_value():
    line = ('ts=2026-10-14T09:00:01.000Z level=ERROR event=realtime.wakeup_failed '
            'error="connection reset by peer" detail="a \\"quoted\\" bit" cg_mb=200')
    (parsed,) = soak.parse_lines(line)
    assert parsed.fields["error"] == "connection reset by peer"
    assert parsed.fields["detail"] == 'a "quoted" bit'
    assert parsed.fields["cg_mb"] == "200"


def test_parse_lines_sorts_by_ts():
    text = "\n".join([_req(_ts(5), req="b"), _req(_ts(2), req="a"), _req(_ts(5), req="c")])
    assert [l.fields["req"] for l in soak.parse_lines(text)] == ["a", "b", "c"]


def test_route_of_names_requests_by_method_and_path_and_others_by_event():
    req, other = soak.parse_lines("\n".join([
        _req(_ts(1), path="/items", method="POST"),
        f"ts={_ts(2)} event=realtime.dispatch_stop_failed",
    ]))
    assert soak.route_of(req) == "POST /items"
    assert soak.route_of(other) == "realtime.dispatch_stop_failed"
