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


# --- jump finder ------------------------------------------------------------

def _staircase():
    # 10 healthz samples a second apart; +20 MB at t=4 carried by a POST,
    # +30 MB at t=8 observed by a healthz (background work), a realtime
    # event at t=7 sits in the second window.
    rows = []
    for s in range(10):
        cg = 180 + (20 if s >= 4 else 0) + (30 if s >= 8 else 0)
        if s == 4:
            rows.append(_req(_ts(s), path="/items/dispense-exports", method="POST", cg=cg, cgd=20, req=f"r{s}"))
        else:
            rows.append(_req(_ts(s), cg=cg, req=f"r{s}"))
    rows.append(f"ts={_ts(7)} level=WARNING event=realtime.wakeup_failed")
    return soak.parse_lines("\n".join(rows))


def test_find_jumps_finds_both_steps_and_names_carriers():
    report = soak.find_jumps(_staircase(), step=8, window=3)
    assert report.samples == 10 and (report.first, report.last) == (180, 230)
    assert [(j.before, j.after) for j in report.jumps] == [(180, 200), (200, 230)]
    first, second = report.jumps
    assert soak.route_of(first.carrier) == "POST /items/dispense-exports"
    assert first.carrier.fields["cg_delta_mb"] == "20"          # allocating
    assert soak.route_of(second.carrier) == "GET /healthz"
    assert second.carrier.fields["cg_delta_mb"] == "0"          # observing
    assert [l.fields["req"] for l in first.window] == ["r1", "r2", "r3"]   # 3 s before, carrier excluded
    assert "realtime.wakeup_failed" in {soak.route_of(l) for l in second.window}


def test_find_jumps_gradual_rise_reports_rise_above_jump_sum():
    lines = soak.parse_lines("\n".join(_req(_ts(s), cg=180 + 3 * s, req=f"r{s}") for s in range(10)))
    report = soak.find_jumps(lines, step=8)
    assert report.jumps == [] and report.jump_sum == 0 and report.rise == 27


def test_find_jumps_with_no_samples():
    report = soak.find_jumps(soak.parse_lines(f"ts={_ts(1)} event=auth.login_ok"))
    assert report.samples == 0 and report.rise == 0 and report.jumps == []


def test_tally_counts_windows_not_occurrences():
    report = soak.find_jumps(_staircase(), step=8, window=3)
    counts = dict(soak.tally(report.jumps))
    assert counts["GET /healthz"] == 2                 # present in both windows
    assert counts["realtime.wakeup_failed"] == 1
    assert soak.tally(report.jumps)[0] == ("GET /healthz", 2)


def test_render_jumps_shows_summary_carriers_windows_and_tally():
    text = soak.render_jumps(soak.find_jumps(_staircase(), step=8, window=3))
    assert "levels  180->230 MB  rise +50   jumps=2  jump sum=50  (step>=8)" in text
    assert "#1" in text and "180->200 (+20)" in text and "carrier POST /items/dispense-exports cg_delta_mb=20" in text
    assert "-1.0s" in text and "realtime.wakeup_failed" in text
    assert text.rstrip().endswith("1  realtime.wakeup_failed")
