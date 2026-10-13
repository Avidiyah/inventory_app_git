# Memory Soak (Phase 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `memprobe.py jumps` reads any log text and prints what preceded every cgroup step; `memprobe.py soak` runs mixed concurrent traffic for a duration and ends with a trend table, that jumps report, and a sample-series CSV.

**Architecture:** A new `scripts/memprobe_soak.py` holds the pure half (tolerant logfmt parser, jump finder, tally, renderers, CSV, reader-step selection) and the soak orchestration (writer/reader/sampler threads, `run_soak`, `run_jumps`). `memprobe.py` gains two thin subparsers and nothing else. The soak module imports `memprobe` at module level (it is stdlib-only at import); `memprobe.main` imports the soak module lazily, so there is no cycle.

**Tech Stack:** Python 3.12 stdlib (`re`, `threading`, `random`, `csv`, `datetime`); `scripts.memprobe` helpers (`_send`, `_opener`, `_login`, `_clock_skew`, `_payload`, `run_group`, `read_container_logs`, `parse_request_lines`); `scripts.memprobe_routes` (`CATALOGUE`, `enumerate_routes`, `plan`, `Step`); `tests.e2e._seed`; pytest.

**Spec:** `docs/superpowers/specs/2026-10-13-memory-soak-p3-design.md` — read it first; the plan does not restate it.

## Global Constraints

- Phase 1 and 2 constraints hold: stdlib only; `.env` read only through `app.database`; `E2E-` rows only; no push (`main` deploys); targeted tests only before commit.
- `scripts/memprobe.py` ≤ 500 lines (409 today); `scripts/memprobe_soak.py` ≤ 500 lines; `tests/test_memprobe_soak.py` is new, `tests/test_memprobe.py` untouched.
- `memprobe_soak.py` never imports `app.*` at module level.
- Exit codes: `jumps` 0, or 2 with no `cg_mb` line. `soak` 0 clean · 1 any failed route · 2 container/Docker/login/worker connection lost.
- Correlation is by request id wherever the harness sent the request (pass-end `/healthz`, start/end baselines). Time order is used only inside the log text itself.
- Tests run from `backend/` with `.\venv\Scripts\python.exe -m pytest`; no test opens HTTP, Docker or the database.

## Review Focus

1. A log value quoted with spaces (`error="connection reset"`) must not swallow the tokens after it. Task 1, `test_parse_lines_keeps_tokens_after_a_quoted_value`.
2. Two log excerpts pasted out of order, or docker's stdout/stderr interleaving, must still produce one chronological series. Task 1, `test_parse_lines_sorts_by_ts`.
3. A gradual rise with no single interval ≥ `--step` yields zero jumps, and the summary's total rise exceeds the jump sum so the reader lowers the threshold. Task 2, `test_find_jumps_gradual_rise_reports_rise_above_jump_sum`.
4. A worker whose connection drops must stop every other worker, be reported, and exit 2, with the seed torn down. Task 5, `test_reader_error_sets_stop_and_records_message`.
5. Ctrl-C during a two-hour run must still produce the full report. Task 5, `test_wait_returns_on_keyboard_interrupt_and_sets_stop`; acceptance step 3 proves it end to end.

---

### Task 1: Tolerant logfmt parser

**Files:**
- Create: `backend/scripts/memprobe_soak.py`
- Test: `backend/tests/test_memprobe_soak.py`

**Interfaces:**
- Produces: `Line(ts: datetime, event: str, fields: dict[str, str])` (frozen dataclass) and `parse_lines(text: str) -> list[Line]`, sorted by `ts` (stable). Values are unquoted and unescaped. A line without `ts=` or `event=` is dropped. `REQUEST_EVENTS = ("request", "request.error")` and `route_of(line) -> str` (`"GET /items"` for request lines, else the event name).

- [ ] **Step 1: Write the failing tests**

```python
"""Host-side tests for scripts/memprobe_soak.py: parsing, jump finding,
rendering, reader-step selection and the thread loops against a fake
sender. No HTTP, no Docker, no database."""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import memprobe
from scripts import memprobe_soak as soak


def _req(ts, path="/healthz", cg=180, cgd=0, method="GET", req="r1", status=200, ms=3, rss=120):
    return (f"ts={ts} level=INFO req={req} event=request method={method} path={path} "
            f"status={status} ms={ms} rss_mb={rss} cg_mb={cg} cg_delta_mb={cgd} rss_delta_mb=0")


def _ts(seconds):
    return datetime(2026, 10, 14, 9, 0, seconds, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_memprobe_soak.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'scripts.memprobe_soak'`

- [ ] **Step 3: Create the module with the parser**

```python
"""Phase 3 of the endpoint memory suite: a jump finder over any log text and
a mixed concurrent soak against the inventory-local container.

    python scripts/memprobe.py jumps render-export.log --step 8 --window 30
    python scripts/memprobe.py jumps --container inventory-local
    python scripts/memprobe.py soak --minutes 120 --workers 3 --out soak.csv

Spec: docs/superpowers/specs/2026-10-13-memory-soak-p3-design.md.
"""

from __future__ import annotations

import csv
import random
import re
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from scripts import memprobe as mp

REQUEST_EVENTS = ("request", "request.error")

# key=value where the value is either a double-quoted string with backslash
# escapes (app.logging_config._fmt_value) or a bare run of non-space chars.
# Anything on the line that is not key=value (a Render or docker prefix) is
# simply never matched.
_TOKEN = re.compile(r'([A-Za-z_][\w.]*)=("(?:[^"\\]|\\.)*"|[^\s"]*)')
_UNESCAPE = {"\\\\": "\\", '\\"': '"', "\\n": "\n", "\\r": "\r", "\\t": "\t"}


@dataclass(frozen=True)
class Line:
    ts: datetime
    event: str
    fields: dict[str, str]


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return re.sub(r"\\.", lambda m: _UNESCAPE.get(m.group(0), m.group(0)[1]), value[1:-1])
    return value


def parse_lines(text: str) -> list[Line]:
    """Every logfmt line carrying `ts=` and `event=`, chronological. Tolerates
    a prefix before the first key=value (Render export, docker --timestamps)."""
    out = []
    for raw in text.splitlines():
        fields = {k: _unquote(v) for k, v in _TOKEN.findall(raw)}
        ts, event = fields.get("ts"), fields.get("event")
        if not ts or not event:
            continue
        try:
            when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        out.append(Line(when, event, fields))
    out.sort(key=lambda l: l.ts)  # stable: docker interleaves stdout/stderr
    return out


def route_of(line: Line) -> str:
    if line.event in REQUEST_EVENTS:
        return f"{line.fields.get('method', '?')} {line.fields.get('path', '?')}"
    return line.event
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_memprobe_soak.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/memprobe_soak.py backend/tests/test_memprobe_soak.py
git commit -m "feat(memprobe): tolerant logfmt line parser for the jump finder"
```

---

### Task 2: Jump finder, tally and report

**Files:**
- Modify: `backend/scripts/memprobe_soak.py`
- Test: `backend/tests/test_memprobe_soak.py`

**Interfaces:**
- Consumes: `Line`, `parse_lines`, `route_of` (Task 1); `memprobe._int_or_none`.
- Produces:
  - `Jump(at: datetime, before: int, after: int, carrier: Line, window: list[Line])`
  - `JumpReport(samples: int, first: Optional[int], last: Optional[int], span: tuple[Optional[datetime], Optional[datetime]], step: int, jumps: list[Jump])` with property `rise` (`last - first`, or 0) and `jump_sum`.
  - `find_jumps(lines: list[Line], step: int = 8, window: float = 30.0) -> JumpReport`
  - `tally(jumps: list[Jump]) -> list[tuple[str, int]]` sorted by count desc then name.
  - `render_jumps(report: JumpReport) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_memprobe_soak.py -v -k "jumps or tally"`
Expected: FAIL, `AttributeError: module 'scripts.memprobe_soak' has no attribute 'find_jumps'`

- [ ] **Step 3: Implement**

Append to `memprobe_soak.py`:

```python
# --- jump finder ------------------------------------------------------------

@dataclass
class Jump:
    at: datetime
    before: int
    after: int
    carrier: Line
    window: list[Line]


@dataclass
class JumpReport:
    samples: int
    first: Optional[int]
    last: Optional[int]
    span: tuple[Optional[datetime], Optional[datetime]]
    step: int
    jumps: list[Jump] = field(default_factory=list)

    @property
    def rise(self) -> int:
        return 0 if self.first is None or self.last is None else self.last - self.first

    @property
    def jump_sum(self) -> int:
        return sum(j.after - j.before for j in self.jumps)


def _cg(line: Line) -> Optional[int]:
    return mp._int_or_none(line.fields.get("cg_mb"))


def find_jumps(lines: list[Line], step: int = 8, window: float = 30.0) -> JumpReport:
    """A jump is a rise of at least `step` MB between consecutive samples
    (lines carrying cg_mb). The sample showing the new level is the carrier;
    the window is every line in the `window` seconds before it."""
    samples = [l for l in lines if _cg(l) is not None]
    report = JumpReport(len(samples), _cg(samples[0]) if samples else None, _cg(samples[-1]) if samples else None,
                        (samples[0].ts, samples[-1].ts) if samples else (None, None), step)
    span = timedelta(seconds=window)
    for prev, cur in zip(samples, samples[1:]):
        a, b = _cg(prev), _cg(cur)
        if b - a >= step:
            # ponytail: full rescan per jump; bisect on ts if logs reach millions of lines
            report.jumps.append(Jump(cur.ts, a, b, cur, [l for l in lines if cur.ts - span <= l.ts < cur.ts]))
    return report


def tally(jumps: list[Jump]) -> list[tuple[str, int]]:
    """Routes and events by the number of jump windows they appear in."""
    counts: Counter = Counter()
    for j in jumps:
        counts.update({route_of(l) for l in j.window})
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _iso(ts: Optional[datetime]) -> str:
    return "-" if ts is None else ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _window_line(l: Line, at: datetime) -> str:
    offset = f"{(l.ts - at).total_seconds():+.1f}s"
    if l.event in REQUEST_EVENTS:
        f = l.fields
        return (f"   {offset:>8}  {l.event:<12} {f.get('method', '?'):<6} {f.get('path', '?'):<40} "
                f"{f.get('status', '-'):>4} {f.get('ms', '-'):>6}ms  d{f.get('cg_delta_mb', '-')}")
    rest = " ".join(f"{k}={v}" for k, v in l.fields.items() if k not in ("ts", "level", "event"))
    return f"   {offset:>8}  {l.event:<12} {rest}"


def render_jumps(report: JumpReport) -> str:
    rows = [
        f"jumps   samples={report.samples:,}  span={_iso(report.span[0])}->{_iso(report.span[1])}",
        f"levels  {mp._fmt(report.first)}->{mp._fmt(report.last)} MB  rise {report.rise:+d}   "
        f"jumps={len(report.jumps)}  jump sum={report.jump_sum}  (step>={report.step})",
    ]
    for i, j in enumerate(report.jumps, 1):
        rows += ["", f"#{i}  {_iso(j.at)}  {j.before}->{j.after} ({j.after - j.before:+d})  "
                     f"carrier {route_of(j.carrier)} cg_delta_mb={j.carrier.fields.get('cg_delta_mb', '-')}"]
        rows += [_window_line(l, j.at) for l in j.window]
    if report.jumps:
        rows += ["", f"tally  (of {len(report.jumps)} windows)"]
        rows += [f"{n:>4}  {name}" for name, n in tally(report.jumps)]
    return "\n".join(rows)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_memprobe_soak.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/memprobe_soak.py backend/tests/test_memprobe_soak.py
git commit -m "feat(memprobe): jump finder, window tally and report"
```

---

### Task 3: `jumps` subcommand

**Files:**
- Modify: `backend/scripts/memprobe_soak.py`
- Modify: `backend/scripts/memprobe.py:239-248` (`read_container_logs`), `:353-361` (`main`)
- Test: `backend/tests/test_memprobe_soak.py`

**Interfaces:**
- Consumes: `find_jumps`, `render_jumps` (Task 2); `memprobe.read_container_logs`.
- Produces: `run_jumps(args) -> int` with `args.file: Optional[str]`, `args.step: int`, `args.window: float`, `args.container: str`. `memprobe.read_container_logs(container, since_epoch: Optional[float])` omits `--since` when `None`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_memprobe_soak.py -v -k "subcommand or since"`
Expected: FAIL (`jumps` parsed as a method; `read_container_logs` raises on `None`)

- [ ] **Step 3: Implement**

In `memprobe.py`, make `--since` optional:

```python
def read_container_logs(container: str, since_epoch: Optional[float]) -> str:
    argv = ["docker", "logs"]
    if since_epoch is not None:
        argv += ["--since", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since_epoch - 1))]
    proc = subprocess.run(argv + [container], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"docker logs failed: {proc.stderr.strip()}")
    return proc.stdout + proc.stderr  # uvicorn writes to stderr
```

In `memprobe.main`, before the `sweep` branch:

```python
    if argv[:1] == ["jumps"]:
        from scripts.memprobe_soak import run_jumps
        ap = argparse.ArgumentParser(prog="memprobe.py jumps", description=run_jumps.__doc__)
        ap.add_argument("file", nargs="?", help="log text; '-' for stdin; omit to read --container")
        ap.add_argument("--step", type=int, default=8)
        ap.add_argument("--window", type=float, default=30.0)
        ap.add_argument("--container", default="inventory-local")
        return run_jumps(ap.parse_args(argv[1:]))
```

Append to `memprobe_soak.py`:

```python
# --- jumps subcommand -------------------------------------------------------

def run_jumps(args) -> int:
    """Find every cgroup step in a log (file, stdin or the container) and print
    the window before each. Exit 0; 2 when nothing carried cg_mb."""
    if args.file == "-":
        source, text = "stdin", sys.stdin.read()
    elif args.file:
        with open(args.file, encoding="utf-8", errors="replace") as fh:
            source, text = args.file, fh.read()
    else:
        source, text = args.container, mp.read_container_logs(args.container, None)
    report = find_jumps(parse_lines(text), args.step, args.window)
    if report.samples == 0:
        print(f"no cg_mb lines in {source}", file=sys.stderr)
        return 2
    print(render_jumps(report))
    return 0
```

Update the module docstring of `memprobe.py` with the two new usage lines (`jumps FILE`, `soak --minutes 120`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_memprobe_soak.py tests/test_memprobe.py -v`
Expected: all pass (Phase 1/2 tests unaffected: `run_sweep` and the single-route path still pass `start`).

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/memprobe.py backend/scripts/memprobe_soak.py backend/tests/test_memprobe_soak.py
git commit -m "feat(memprobe): jumps subcommand over a file, stdin or the container"
```

---

### Task 4: Reader steps, trend table, series CSV

**Files:**
- Modify: `backend/scripts/memprobe_soak.py`
- Test: `backend/tests/test_memprobe_soak.py`

**Interfaces:**
- Consumes: `memprobe_routes.Plan`, `Step`; `memprobe.Sent`, `Sample`, `_fmt`.
- Produces:
  - `reader_steps(plan: Plan, seed: int) -> list[Step]`: single-step groups whose method is GET and whose path has no `{id}`, shuffled with `random.Random(seed)`.
  - `Pass(elapsed: float, requests: int, failed: int, healthz_req: Optional[str])`.
  - `Worker(name: str, sent: dict[str, list[Sent]] = {}, passes: list[Pass] = [], error: Optional[str] = None)`.
  - `render_trend(passes: list[Pass], samples: dict[str, Sample], start: Optional[Sample]) -> str`.
  - `series_csv(lines: list[Line], owner_of: dict[str, str], path: str) -> None` with columns `ts, cg_mb, rss_mb, method, path, cg_delta_mb, worker`.

- [ ] **Step 1: Write the failing tests**

```python
from scripts.memprobe_routes import Plan, Step


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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_memprobe_soak.py -v -k "reader_steps or trend or csv"`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement**

Append to `memprobe_soak.py`:

```python
# --- soak: pure parts -------------------------------------------------------

@dataclass
class Pass:
    elapsed: float
    requests: int
    failed: int
    healthz_req: Optional[str]


@dataclass
class Worker:
    name: str
    sent: dict[str, list] = field(default_factory=dict)  # route -> list[memprobe.Sent]
    passes: list[Pass] = field(default_factory=list)
    error: Optional[str] = None

    def requests(self) -> int:
        return sum(len(v) for v in self.sent.values())

    def failed(self) -> int:
        return sum(1 for v in self.sent.values() for s in v if not (200 <= s.status < 300))


def reader_steps(plan, seed: int) -> list:
    """The read-only half of the plan: single-step GET groups whose path needs
    no created id. Shuffled per reader so two readers never walk in step."""
    steps = [g[0] for g in plan.groups if len(g) == 1 and g[0].method == "GET" and "{id}" not in g[0].path]
    random.Random(seed).shuffle(steps)
    return steps


def _clock(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def render_trend(passes: list[Pass], samples: dict, start) -> str:
    rows = ["pass   elapsed   cg_mb  rss_mb   rise  requests  failed"]
    base = start.cg_mb if start else None
    for i, p in enumerate(passes, 1):
        s = samples.get(p.healthz_req) if p.healthz_req else None
        cg = s.cg_mb if s else None
        rise = None if cg is None or base is None else cg - base
        rows.append(f"{i:>4}  {_clock(p.elapsed):>8}  {mp._fmt(cg):>6}  {mp._fmt(s.rss_mb if s else None):>6}  "
                    f"{('-' if rise is None else f'{rise:+d}'):>5}  {p.requests:>8}  {p.failed:>6}")
    return "\n".join(rows)


SERIES_COLUMNS = ("ts", "cg_mb", "rss_mb", "method", "path", "cg_delta_mb", "worker")


def series_csv(lines: list[Line], owner_of: dict[str, str], path: str) -> None:
    """Every request line of the run, Excel-ready, tagged with the worker
    whose request id it carries (blank for traffic the harness did not send)."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(SERIES_COLUMNS)
        for l in lines:
            if l.event in REQUEST_EVENTS:
                f = l.fields
                w.writerow([_iso(l.ts), f.get("cg_mb", ""), f.get("rss_mb", ""), f.get("method", ""),
                            f.get("path", ""), f.get("cg_delta_mb", ""), owner_of.get(f.get("req", ""), "")])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_memprobe_soak.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/memprobe_soak.py backend/tests/test_memprobe_soak.py
git commit -m "feat(memprobe): reader step selection, trend table and sample-series CSV"
```

---

### Task 5: Soak threads, orchestration and subcommand

**Files:**
- Modify: `backend/scripts/memprobe_soak.py`
- Modify: `backend/scripts/memprobe.py` (`main`, after the `jumps` branch)
- Test: `backend/tests/test_memprobe_soak.py`

**Interfaces:**
- Consumes: Task 4 types; `memprobe._send`, `_opener`, `_login`, `_clock_skew`, `_payload`, `run_group`, `parse_request_lines`, `read_container_logs`; `memprobe_routes.CATALOGUE`, `enumerate_routes`, `plan`.
- Produces:
  - `writer_loop(w: Worker, base, groups, tokens, n, gap, skew, stop: threading.Event, login: Callable[[str], object], started: float) -> None` — `login(user)` returns a fresh logged-in opener for `"owner"` or `"technician"`.
  - `reader_loop(w, base, steps, tokens, gap, skew, stop, opener, started) -> None`.
  - `sampler_loop(w, base, opener, every, stop) -> None`.
  - `wait(threads, deadline, stop) -> None` — returns at the deadline, when every worker thread has ended, or on `KeyboardInterrupt`; sets `stop` in every case.
  - `run_soak(args) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
import threading


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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_memprobe_soak.py -v -k "loop or wait or soak_subcommand"`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement the loops and `wait`**

Append to `memprobe_soak.py`:

```python
# --- soak: threads ----------------------------------------------------------

def _end_pass(w: Worker, base: str, opener, started: float) -> None:
    """One /healthz per pass, kept by request id so the trend table reads
    the container's figure for this moment and no other."""
    h = mp._send(opener, base, "GET", "/healthz", None)
    w.sent.setdefault("GET /healthz", []).append(h)
    w.passes.append(Pass(time.time() - started, w.requests(), w.failed(), h.req))


def writer_loop(w: Worker, base: str, groups, tokens, n: int, gap: float, skew: timedelta,
                stop: threading.Event, login: Callable[[str], object], started: float) -> None:
    """The Phase 2 sweep in rotation until `stop`. Checks the flag between
    groups (a group is at most 2n requests)."""
    try:
        openers = {"owner": login("owner")}
        while not stop.is_set():
            for group in groups:
                if stop.is_set():
                    break
                if any(s.as_user == "technician" for s in group):
                    openers["technician"] = login("technician")  # archive revokes the old session
                for route, sent in mp.run_group(openers, base, group, tokens, n, gap, skew=skew).items():
                    w.sent.setdefault(route, []).extend(sent)
            _end_pass(w, base, openers["owner"], started)
    except (RuntimeError, OSError) as exc:
        w.error = str(exc)
        stop.set()


def reader_loop(w: Worker, base: str, steps, tokens, gap: float, skew: timedelta,
                stop: threading.Event, opener, started: float) -> None:
    """GET-only traffic until `stop`, checked between requests."""
    try:
        while not stop.is_set():
            for step in steps:
                if stop.is_set():
                    break
                path, body, ctype = mp._payload(step, tokens, 0, datetime.now(timezone.utc) + skew, None)
                w.sent.setdefault(step.route, []).append(mp._send(opener, base, step.method, path, body, ctype))
                time.sleep(gap)
            _end_pass(w, base, opener, started)
    except (RuntimeError, OSError) as exc:
        w.error = str(exc)
        stop.set()


def sampler_loop(w: Worker, base: str, opener, every: float, stop: threading.Event) -> None:
    """A /healthz every `every` seconds so the series never starves behind a
    slow route. /healthz is exempt from the limiter."""
    try:
        while not stop.wait(every):
            w.sent.setdefault("GET /healthz", []).append(mp._send(opener, base, "GET", "/healthz", None))
    except (RuntimeError, OSError) as exc:
        w.error = str(exc)
        stop.set()


def wait(threads: list[threading.Thread], deadline: float, stop: threading.Event) -> None:
    """Block until the deadline, every thread has ended, or Ctrl-C. Sets
    `stop` on every exit so the caller can join."""
    try:
        while time.time() < deadline and any(t.is_alive() for t in threads) and not stop.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("stopping: Ctrl-C", file=sys.stderr)
    stop.set()
```

- [ ] **Step 4: Implement `run_soak`**

Append to `memprobe_soak.py`:

```python
# --- soak: orchestration ----------------------------------------------------

def _failed_routes(workers: list[Worker], catalogue) -> tuple[list[str], list[str]]:
    """(failed, expected) lines. The writer follows the sweep rule: 2xx or the
    catalogue's `expect`. A reader's 404 is expected: it raced the writer's
    archive/delete on a seed row; Phase 2 proved those GETs 200 otherwise."""
    failed, expected = [], []
    for w in workers:
        for route, sent in w.sent.items():
            entry = catalogue.get(route)
            allow = {entry.expect} if entry and entry.expect else set()
            if w.name != "writer":
                allow.add(404)
            bad = Counter(s.status for s in sent if not (200 <= s.status < 300) and s.status not in allow)
            ok = Counter(s.status for s in sent if s.status in allow)
            if bad:
                failed.append(f"  {route:<50} {' '.join(f'{c}x{n}' for c, n in sorted(bad.items()))}  ({w.name})")
            if ok:
                expected.append(f"  {route:<50} {' '.join(f'{c}x{n}' for c, n in sorted(ok.items()))}  ({w.name})")
    return failed, expected


def run_soak(args) -> int:
    """Mixed concurrent traffic against the container for --minutes: one writer
    running the sweep plan, --workers-1 GET-only readers, a /healthz sampler.
    Ends with the trend table, the jumps report over the run's logs, the failed
    routes, and --out as the sample series. Exit 0 clean, 1 any failed route,
    2 container/Docker/login/worker connection lost."""
    from scripts.memprobe_routes import CATALOGUE, enumerate_routes, plan

    owner = mp._opener()
    try:
        mp._send(owner, args.base, "GET", "/healthz", None)
    except (OSError,) as exc:  # URLError is an OSError
        print(f"container not reachable at {args.base}: {exc}", file=sys.stderr)
        return 2

    from app.database import SessionLocal
    from app.main import app
    from tests.e2e import _seed

    started = time.time()
    db, seed, aborted, text = SessionLocal(), None, False, ""
    stop = threading.Event()
    workers: list[Worker] = []
    start_sent = end_sent = None
    try:
        _seed.sweep_debris(db)
        seed = _seed.build(db)
        tokens = {**vars(seed), "barcode": seed.item_barcode, "wo": seed.work_order_number}
        routes, _ = enumerate_routes(app)
        p = plan(routes, CATALOGUE, tokens, args.only)

        def login(user: str):
            opener = mp._opener()
            name = seed.owner_username if user == "owner" else seed.technician_username
            mp._login(opener, args.base, name, _seed.SEED_PASSWORD)
            return opener

        try:
            mp._login(owner, args.base, seed.owner_username, _seed.SEED_PASSWORD)
            skew = mp._clock_skew(mp._send(owner, args.base, "GET", "/attendance/me", None))
            start_sent = mp._send(owner, args.base, "GET", "/healthz", None)
            writer = Worker("writer")
            readers = [Worker(f"reader{i}") for i in range(1, args.workers)]
            sampler = Worker("sampler")
            workers = [writer, *readers, sampler]
            threads = [threading.Thread(target=writer_loop, daemon=True, args=(
                writer, args.base, p.groups, tokens, args.n, args.gap, skew, stop, login, started))]
            threads += [threading.Thread(target=reader_loop, daemon=True, args=(
                r, args.base, reader_steps(p, i), tokens, args.gap, skew, stop, login("owner"), started))
                for i, r in enumerate(readers, 1)]
            sampler_thread = threading.Thread(target=sampler_loop, daemon=True,
                                              args=(sampler, args.base, owner, args.sample, stop))
            for t in threads + [sampler_thread]:
                t.start()
            wait(threads, started + args.minutes * 60, stop)
            for t in threads + [sampler_thread]:
                t.join()
            end_sent = mp._send(owner, args.base, "GET", "/healthz", None)
        except (RuntimeError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            aborted = True
        for w in workers:
            if w.error:
                print(f"{w.name}: {w.error}", file=sys.stderr)
                aborted = True
        try:  # an aborted run still reports what it measured
            time.sleep(0.5)
            text = mp.read_container_logs(args.container, started)
        except (RuntimeError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            aborted = True
    finally:
        stop.set()
        if seed is not None:
            _seed.destroy(db, seed)
        db.close()

    owner_of = {s.req: w.name for w in workers for v in w.sent.values() for s in v if s.req}
    wanted = set(owner_of) | {s.req for s in (start_sent, end_sent) if s and s.req}
    samples = mp.parse_request_lines(text, wanted)
    lines = parse_lines(text)
    writer_passes = workers[0].passes if workers else []
    start = samples.get(start_sent.req) if start_sent else None
    end = samples.get(end_sent.req) if end_sent else None
    print(f"soak    minutes={args.minutes}  workers={args.workers}  n={args.n}  gap={args.gap}  "
          f"container={args.container}  requests={sum(w.requests() for w in workers)}")
    print(f"levels  start cg_mb={mp._fmt(start.cg_mb if start else None)}  "
          f"end cg_mb={mp._fmt(end.cg_mb if end else None)}\n")
    print(render_trend(writer_passes, samples, start), "\n")
    print(render_jumps(find_jumps(lines)), "\n")
    failed, expected = _failed_routes(workers, CATALOGUE)
    print("failed\n" + ("\n".join(failed) if failed else "  none"))
    if expected:
        print("expected\n" + "\n".join(expected))
    if args.out:
        series_csv(lines, owner_of, args.out)
    if aborted:
        return 2
    return 1 if failed else 0
```

In `memprobe.main`, after the `jumps` branch:

```python
    if argv[:1] == ["soak"]:
        from scripts import memprobe_soak
        ap = argparse.ArgumentParser(prog="memprobe.py soak", description=memprobe_soak.run_soak.__doc__)
        _common_flags(ap)
        ap.set_defaults(n=5, gap=0.1)
        ap.add_argument("--minutes", type=float, default=60.0)
        ap.add_argument("--workers", type=int, default=3)
        ap.add_argument("--sample", type=float, default=5.0)
        ap.add_argument("--out", help="CSV path for the sample series")
        ap.add_argument("--only", help="substring filter on 'METHOD /path'")
        return memprobe_soak.run_soak(ap.parse_args(argv[1:]))
```

- [ ] **Step 5: Run the tests and the line-count check**

Run: `.\venv\Scripts\python.exe -m pytest tests/test_memprobe_soak.py tests/test_memprobe.py -v`
Expected: all pass

Run: `wc -l scripts/memprobe.py scripts/memprobe_soak.py`
Expected: both ≤ 500. If `memprobe.py` is over, move `run_sweep` into `memprobe_routes.py` (it already imports from there lazily; invert the lazy import) in this same task.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/memprobe.py backend/scripts/memprobe_soak.py backend/tests/test_memprobe_soak.py
git commit -m "feat(memprobe): soak subcommand with writer, readers, sampler and report"
```

---

### Task 6: Acceptance runs and docs

**Files:**
- Modify: `docs/current-state.md` (Local Docker reproduction bullets, after the sweep bullet)
- Modify: `docs/open-work.md` (N-MEMORY-CRASH)
- Modify: `docs/superpowers/specs/2026-10-13-memory-soak-p3-design.md` (one line, below)

- [ ] **Step 1: Container fresh**

```
docker rm -f inventory-local
docker run -d --name inventory-local --memory=2g -p 8124:8124 --env-file /tmp/inventory.docker.env inventory-app
```

(Recreate the env copy first if `.env` changed; never edit `.env`.) Wait for `GET /healthz` 200.

- [ ] **Step 2: `jumps` over the live container and over a prefixed file**

From `backend/` (PowerShell):

```
.\venv\Scripts\python.exe scripts\memprobe.py jumps --container inventory-local
docker logs -t inventory-local > ..\..\jumps-sample.log 2>&1
.\venv\Scripts\python.exe scripts\memprobe.py jumps ..\..\jumps-sample.log
```

Expected: both print the `jumps`/`levels` summary; the second parses despite the docker timestamp prefix. Delete the sample file afterwards.

- [ ] **Step 3: Short soak and the Ctrl-C path**

```
.\venv\Scripts\python.exe scripts\memprobe.py soak --minutes 5 --workers 3 --out ..\..\soak-5.csv
```

Expected: exit 0; trend rows (one per writer pass); jumps report; `failed none`; CSV opens with the seven columns. Then start a second run and press Ctrl-C after a minute: the full report prints, the exit code follows the normal rules, and `SELECT count(*) FROM work_orders WHERE number LIKE 'E2E-%'` is 0 afterwards.

- [ ] **Step 4: The long soak**

```
.\venv\Scripts\python.exe scripts\memprobe.py soak --minutes 120 --workers 3 --out ..\..\soak-120.csv
```

Paste the `levels` line, the trend table, and the jumps report into the completion report. Outcome A: a jump reproduces → the tally names the Phase 4 candidate. Outcome B: no jump → the next readout is a Render log export through `jumps` after the next production step.

- [ ] **Step 5: Docs**

`docs/current-state.md`, under *Local Docker reproduction*, one bullet after the sweep bullet:

> - Soak and jump finder: `python scripts/memprobe.py soak --minutes 120 --workers 3 --out soak.csv` (one writer running the sweep plan, GET-only readers, a `/healthz` sampler; ends with trend, jumps, failed) and `python scripts/memprobe.py jumps FILE|--container` (every cgroup step ≥ `--step` MB with the log window before it and a tally across windows; works on a Render log export). Spec: `docs/superpowers/specs/2026-10-13-memory-soak-p3-design.md`.

`docs/open-work.md`, N-MEMORY-CRASH: change "Phase 3 (long runs, traffic mixes, concurrency) is next." to "Phase 3 (`soak`, `jumps`) shipped on the ship date: outcome A or B from step 4 in one sentence. Production readout: export Render logs spanning the next step and run `jumps` on the file." Keep the entry inside its budget: delete the "No load or soak tooling exists" fact, which is now false.

Spec, *Report* part 3: replace "or is 404 on a route whose writer cycle archives or deletes" with "or is a reader's 404 (it raced the writer's archive/delete on a seed row)". The plan simplified the rule; the spec must say what shipped.

- [ ] **Step 6: Commit**

```bash
git add docs/current-state.md docs/open-work.md docs/superpowers/specs/2026-10-13-memory-soak-p3-design.md
git commit -m "docs: memory soak phase 3 shipped; production readout via jumps"
```

No push: `main` deploys. The user decides.
