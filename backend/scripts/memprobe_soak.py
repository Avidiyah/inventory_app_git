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


# --- soak: orchestration ----------------------------------------------------

def _counts(c: Counter) -> str:
    return " ".join(f"{status}x{n}" for status, n in sorted(c.items()))


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
                failed.append(f"  {route:<50} {_counts(bad)}  ({w.name})")
            if ok:
                expected.append(f"  {route:<50} {_counts(ok)}  ({w.name})")
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
    except OSError as exc:  # URLError is an OSError
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
