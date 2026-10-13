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
