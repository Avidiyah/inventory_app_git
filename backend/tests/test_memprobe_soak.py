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


# --- jumps subcommand -------------------------------------------------------

def test_jumps_subcommand_reads_a_file_and_exits_zero(tmp_path, capsys):
    log = tmp_path / "render.log"
    log.write_text("\n".join(_req(_ts(s), cg=180 + (20 if s >= 4 else 0), req=f"r{s}") for s in range(6)),
                   encoding="utf-8")
    assert memprobe.main(["jumps", str(log), "--step", "8", "--window", "2"]) == 0
    out = capsys.readouterr().out
    assert "jumps=1" in out and "#1" in out


def test_jumps_subcommand_exits_two_without_samples(tmp_path, capsys):
    log = tmp_path / "empty.log"
    log.write_text("INFO:     Application startup complete.\n", encoding="utf-8")
    assert memprobe.main(["jumps", str(log)]) == 2
    assert "no cg_mb lines" in capsys.readouterr().err


def test_jumps_subcommand_reads_the_container_when_no_file(monkeypatch, capsys):
    calls = []

    def fake_logs(container, since_epoch):
        calls.append((container, since_epoch))
        return _req(_ts(1))

    monkeypatch.setattr(memprobe, "read_container_logs", fake_logs)
    assert memprobe.main(["jumps", "--container", "other"]) == 0
    assert calls == [("other", None)]


def test_read_container_logs_omits_since_when_none(monkeypatch):
    seen = {}

    class Proc:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(memprobe.subprocess, "run", lambda argv, **kw: seen.setdefault("argv", argv) and Proc())
    memprobe.read_container_logs("c", None)
    assert seen["argv"] == ["docker", "logs", "c"]


# --- soak: pure parts -------------------------------------------------------

def _step(method, path, route=None):
    return Step(route or f"{method} {path}", method, path, None, None, None, "owner")


def test_reader_steps_keeps_only_single_get_steps_without_id_and_shuffles_deterministically():
    p = Plan(groups=[
        [_step("GET", "/items")],
        [_step("GET", "/work-orders/{work_order_id}")],
        [_step("POST", "/items/search")],                                    # not a GET
        [_step("POST", "/items/"), _step("DELETE", "/items/{id}")],           # a cycle
        [_step("GET", "/hub/report")],
        [_step("GET", "/x/{id}")],                                            # needs a created id
    ])
    a = soak.reader_steps(p, 1)
    assert {s.route for s in a} == {"GET /items", "GET /work-orders/{work_order_id}", "GET /hub/report"}
    assert a == soak.reader_steps(p, 1)  # same seed, same order


def test_render_trend_reads_each_pass_sample_by_request_id():
    samples = memprobe.parse_request_lines("\n".join([
        _req(_ts(0), cg=180, rss=120, req="h0"), _req(_ts(9), cg=190, rss=125, req="h1"),
        _req(_ts(20), cg=230, rss=140, req="h2"),
    ]), {"h0", "h1", "h2"})
    passes = [soak.Pass(9.0, 600, 0, "h1"), soak.Pass(20.5, 1200, 2, "h2"), soak.Pass(30.0, 1800, 2, "missing")]
    text = soak.render_trend(passes, samples, samples["h0"])
    assert "pass   elapsed   cg_mb  rss_mb   rise  requests  failed" in text
    assert "   1      0:09     190     125    +10       600       0" in text
    assert "   2      0:20     230     140    +50      1200       2" in text
    assert "   3      0:30       -       -      -      1800       2" in text


def test_series_csv_writes_request_lines_with_worker(tmp_path):
    lines = soak.parse_lines("\n".join([
        _req(_ts(1), path="/items", cg=180, cgd=0, req="a"),
        _req(_ts(2), path="/healthz", cg=181, cgd=1, req="b"),
        f"ts={_ts(3)} event=auth.login_ok",
    ]))
    out = tmp_path / "s.csv"
    soak.series_csv(lines, {"a": "reader1"}, str(out))
    rows = out.read_text(encoding="utf-8").splitlines()
    assert rows[0] == "ts,cg_mb,rss_mb,method,path,cg_delta_mb,worker"
    assert rows[1].endswith(",180,120,GET,/items,0,reader1")
    assert rows[2].endswith(",181,120,GET,/healthz,1,") and len(rows) == 3


# --- soak: threads ----------------------------------------------------------

def _fake_send(log):
    def send(opener, base, method, path, body, content_type="application/json"):
        log.append((opener, method, path))
        return memprobe.Sent(f"r{len(log)}", 200, None)
    return send


def test_reader_loop_sends_every_step_per_pass_and_records_a_healthz_per_pass(monkeypatch):
    log = []
    monkeypatch.setattr(memprobe, "_send", _fake_send(log))
    w, stop = soak.Worker("reader1"), threading.Event()
    steps = [_step("GET", "/items"), _step("GET", "/hub/report")]

    def one_pass_then_stop(seconds):   # gap sleep -> stop after the second request
        if len(log) >= 2:
            stop.set()

    monkeypatch.setattr(soak.time, "sleep", one_pass_then_stop)
    soak.reader_loop(w, "http://x", steps, {}, 0.0, soak.timedelta(0), stop, "opener", time.time())
    assert [p for _, _, p in log] == ["/items", "/hub/report", "/healthz"]
    assert w.requests() == 3 and len(w.passes) == 1 and w.passes[0].healthz_req == "r3"  # the pass healthz counts


def test_writer_loop_relogs_technician_per_group_and_stops_between_groups(monkeypatch):
    log, logins = [], []
    monkeypatch.setattr(memprobe, "_send", _fake_send(log))
    monkeypatch.setattr(soak.time, "sleep", lambda s: None)
    w, stop = soak.Worker("writer"), threading.Event()
    tech = Step("POST /attendance/punch-in", "POST", "/attendance/punch-in", None, None, None, "technician")
    groups = [[_step("GET", "/items")], [tech]]

    def login(user):
        logins.append(user)
        if user == "technician":
            stop.set()   # set during the second group's login: the loop ends after that group
        return f"{user}-opener"

    soak.writer_loop(w, "http://x", groups, {}, 1, 0.0, soak.timedelta(0), stop, login, time.time())
    assert logins == ["owner", "technician"]
    assert [m for _, m, _ in log] == ["GET", "POST", "GET"] and w.requests() == 3  # two steps + pass healthz
    assert len(w.passes) == 1


def test_reader_error_sets_stop_and_records_message(monkeypatch):
    def boom(*a, **k):
        raise OSError("connection dropped")

    monkeypatch.setattr(memprobe, "_send", boom)
    w, stop = soak.Worker("reader1"), threading.Event()
    soak.reader_loop(w, "http://x", [_step("GET", "/items")], {}, 0.0, soak.timedelta(0), stop, "o", time.time())
    assert stop.is_set() and "connection dropped" in w.error


def test_sampler_loop_polls_until_stopped(monkeypatch):
    log = []
    monkeypatch.setattr(memprobe, "_send", _fake_send(log))
    w, stop = soak.Worker("sampler"), threading.Event()
    threading.Timer(0.05, stop.set).start()
    soak.sampler_loop(w, "http://x", "o", 0.01, stop)
    assert 1 <= len(log) <= 20 and all(p == "/healthz" for _, _, p in log)  # Windows timers are coarse


def test_wait_returns_on_keyboard_interrupt_and_sets_stop(monkeypatch):
    stop = threading.Event()
    t = threading.Thread(target=stop.wait)
    t.start()

    def interrupt(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(soak.time, "sleep", interrupt)
    soak.wait([t], time.time() + 60, stop)
    t.join(1)
    assert stop.is_set() and not t.is_alive()


def test_wait_returns_at_deadline(monkeypatch):
    stop = threading.Event()
    t = threading.Thread(target=stop.wait)
    t.start()
    soak.wait([t], time.time() - 1, stop)
    t.join(1)
    assert stop.is_set() and not t.is_alive()


def test_soak_subcommand_defaults(monkeypatch):
    seen = {}
    monkeypatch.setattr(soak, "run_soak", lambda args: seen.update(vars(args)) or 0)
    assert memprobe.main(["soak"]) == 0
    assert (seen["n"], seen["gap"], seen["minutes"], seen["workers"], seen["sample"]) == (5, 0.1, 60.0, 3, 5.0)


def test_writer_loop_continues_seq_across_passes(monkeypatch):
    # An archived row keeps its barcode, so a {seq} that restarts every pass
    # makes the second pass's create a 409.
    bodies = []

    def send(opener, base, method, path, body, content_type="application/json"):
        bodies.append(body)
        if len(bodies) >= 4:
            stop.set()
        return memprobe.Sent(f"r{len(bodies)}", 200, None)

    monkeypatch.setattr(memprobe, "_send", send)
    monkeypatch.setattr(soak.time, "sleep", lambda s: None)
    w, stop = soak.Worker("writer"), threading.Event()
    create = Step("POST /items/", "POST", "/items/", '{"barcode": "I{seq}"}', None, None, "owner")
    soak.writer_loop(w, "http://x", [[create]], {}, 2, 0.0, soak.timedelta(0), stop, lambda u: "o", time.time())
    assert [b for b in bodies if b] == ['{"barcode": "I0"}', '{"barcode": "I1"}', '{"barcode": "I2"}', '{"barcode": "I3"}']


def test_unexpected_worker_exception_also_sets_stop_and_records_it(monkeypatch):
    # Anything that escapes a worker must abort the run, not just a dropped
    # connection: a thread dying with a traceback while the run exits 0 hides
    # a two-hour result.
    def boom(*a, **k):
        raise ValueError("bad body")

    monkeypatch.setattr(memprobe, "_send", boom)
    w, stop = soak.Worker("reader1"), threading.Event()
    soak.reader_loop(w, "http://x", [_step("GET", "/items")], {}, 0.0, soak.timedelta(0), stop, "o", time.time())
    assert stop.is_set() and "ValueError: bad body" in w.error
