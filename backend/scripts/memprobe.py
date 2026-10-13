"""Drive one route against the inventory-local container N times and print
its memory cost from the container's own `event=request` lines.

    python scripts/memprobe.py GET /items --n 50
    python scripts/memprobe.py POST /items/search --body '{"q":"wid"}' --n 20
    python scripts/memprobe.py sweep --n 20 --out sweep.csv     # every route, ranked
    python scripts/memprobe.py jumps FILE                       # cgroup steps in any log text
    python scripts/memprobe.py soak --minutes 120               # mixed concurrent traffic

Specs: docs/superpowers/specs/2026-10-13-memory-probe-harness-design.md (one
route), 2026-10-13-memory-sweep-p2-design.md (sweep) and
2026-10-13-memory-soak-p3-design.md (jumps, soak).
Correlation is by the echoed `X-Request-ID`, never by time, so other
traffic (the platform's /healthz polls, for one) cannot be mis-attributed.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_REQUEST_EVENTS = ("request", "request.error")
_INT_FIELDS = ("status", "ms", "rss_mb", "cg_mb", "cg_delta_mb", "rss_delta_mb")


@dataclass(frozen=True)
class Sample:
    req: str
    status: Optional[int]
    ms: Optional[int]
    rss_mb: Optional[int]
    cg_mb: Optional[int]
    cg_delta_mb: Optional[int]
    rss_delta_mb: Optional[int]


def _int_or_none(value: Optional[str]) -> Optional[int]:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None  # absent, "-", or garbage all read the same


def parse_request_lines(text: str, wanted: set[str]) -> dict[str, Sample]:
    """logfmt lines -> Sample per wanted request id. Values are unquoted on
    these lines (the path is logged without its query string)."""
    out: dict[str, Sample] = {}
    for line in text.splitlines():
        fields = dict(tok.split("=", 1) for tok in line.split() if "=" in tok)
        req = fields.get("req")
        if req not in wanted or fields.get("event") not in _REQUEST_EVENTS:
            continue
        out[req] = Sample(req, *(_int_or_none(fields.get(k)) for k in _INT_FIELDS))
    return out


_DELTAS = ("cg_delta_mb", "rss_delta_mb")
_LEVELS = ("cg_mb", "rss_mb")


@dataclass(frozen=True)
class Sent:
    req: Optional[str]  # None when the response carried no X-Request-ID
    status: int
    body: Optional[str] = None  # the sweep reads a created row's `id` from it


@dataclass
class Summary:
    sent: int
    statuses: dict[int, int]
    matched: int
    readings: int  # matched lines whose memory fields were present
    unmatched: list[str]
    first: dict[str, Optional[int]]
    rest: dict[str, dict[str, Optional[float]]]
    drift: dict[str, tuple[Optional[int], Optional[int]]]
    ms_p50: Optional[int]
    ms_max: Optional[int]


def _stats(values: list[int]) -> dict[str, Optional[float]]:
    if not values:
        return {"sum": 0, "max": None, "mean": None}
    return {"sum": sum(values), "max": max(values), "mean": statistics.fmean(values)}


def aggregate(sent: list[Sent], samples: dict[str, Sample]) -> Summary:
    """Order is the order sent: the first request pays warm-up costs and is
    reported apart from the steady-state rest."""
    ordered = [samples[s.req] for s in sent if s.req in samples]
    unmatched = [s.req or "<no X-Request-ID>" for s in sent if s.req not in samples]
    first, rest = (ordered[0] if ordered else None), ordered[1:]
    with_readings = [s for s in ordered if s.cg_mb is not None or s.rss_mb is not None]
    ms = [s.ms for s in ordered if s.ms is not None]
    return Summary(
        sent=len(sent),
        statuses=dict(sorted(Counter(s.status for s in sent).items())),
        matched=len(ordered),
        readings=len(with_readings),
        unmatched=unmatched,
        first={k: (getattr(first, k) if first else None) for k in _DELTAS},
        rest={k: _stats([v for s in rest if (v := getattr(s, k)) is not None]) for k in _DELTAS},
        drift={
            k: ((getattr(with_readings[0], k), getattr(with_readings[-1], k)) if with_readings else (None, None))
            for k in _LEVELS
        },
        ms_p50=int(statistics.median(ms)) if ms else None,
        ms_max=max(ms) if ms else None,
    )


def _fmt(value) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def render(route: str, container: str, baseline: Optional[Sample], summary: Summary) -> str:
    base = (
        f"cg_mb={_fmt(baseline.cg_mb)}  rss_mb={_fmt(baseline.rss_mb)}        (idle, from /healthz)"
        if baseline else "-"
    )
    statuses = "  ".join(f"{code}x{n}" for code, n in summary.statuses.items()) or "-"
    rows = [
        f"route        {route}     n={summary.sent}   container={container}",
        f"baseline     {base}",
        f"statuses     {statuses}",
        f"matched      {summary.matched}/{summary.sent}   readings={summary.readings}",
        "",
        f"{'':16} {'first':>6} {'rest(sum)':>10} {'rest(max)':>10} {'rest(mean)':>11}",
    ]
    for k in _DELTAS:
        r = summary.rest[k]
        rows.append(f"{k:16} {_fmt(summary.first[k]):>6} {_fmt(r['sum']):>10} {_fmt(r['max']):>10} {_fmt(r['mean']):>11}")

    def _span(a, b):
        change = "-" if a is None or b is None else f"{b - a:+d}"
        return f"{_fmt(a)}->{_fmt(b)} ({change})"

    drift = "   ".join(f"{k} {_span(a, b)}" for k, (a, b) in summary.drift.items())
    rows += ["", f"drift        {drift}   over {summary.matched} requests",
             f"ms           p50={_fmt(summary.ms_p50)}  max={_fmt(summary.ms_max)}"]
    if summary.unmatched:
        rows.append(f"unmatched    {' '.join(summary.unmatched)}")
    return "\n".join(rows)


def _send(opener, base: str, method: str, path: str, body, content_type: str = "application/json") -> Sent:
    data = body.encode() if isinstance(body, str) else body
    req = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", content_type)
    try:
        resp = opener.open(req, timeout=60)
    except urllib.error.HTTPError as err:  # a 4xx/5xx is still a response
        resp = err
    with resp:
        raw = resp.read()
        return Sent(resp.headers.get("X-Request-ID"), resp.status, raw.decode("utf-8", "replace") if raw else None)


def multipart(filename: str, data: bytes) -> tuple[bytes, str]:
    """One `file` part, the way the import and decode routes expect it."""
    boundary = "memprobe" + uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def _payload(step, tokens, seq: int, now: datetime, last_id: Optional[str]):
    """(path, body, content_type) for one step, or None when the path needs an
    `{id}` no earlier response in the group supplied."""
    from scripts.memprobe_routes import fill
    path = fill(step.path, tokens, seq, now)
    if "{id}" in path:
        if last_id is None:
            return None
        path = path.replace("{id}", last_id)
    if step.file is None:
        return path, (fill(step.body, tokens, seq, now) if step.body else None), "application/json"
    if isinstance(step.file, tuple):
        name, data = step.file[0], fill(step.file[1], tokens, seq, now).encode()
    else:
        with open(step.file, "rb") as fh:
            name, data = os.path.basename(step.file), fh.read()
    body, ctype = multipart(name, data)
    return path, body, ctype


def run_group(openers, base: str, group, tokens, n: int, gap: float,
              now: Optional[datetime] = None, skew: timedelta = timedelta(0),
              seq0: int = 0) -> dict[str, list[Sent]]:
    """One cycle rotation: every member is sent n times; `{id}` comes from the
    most recent JSON response in the group that carried one. A step whose
    `{id}` is unresolvable is recorded as Sent(None, 0) and not sent. `{now}`
    is the wall clock at each request plus `skew` (container minus host, so a
    self-close lands after its punch-in) unless a fixed `now` is given. `{seq}`
    counts from `seq0`: an archived row keeps its barcode, so a repeat rotation
    must not reuse one."""
    out: dict[str, list[Sent]] = {s.route: [] for s in group}
    last_id = None
    for seq in range(seq0, seq0 + n):
        for step in group:
            p = _payload(step, tokens, seq, now or datetime.now(timezone.utc) + skew, last_id)
            if p is None:
                out[step.route].append(Sent(None, 0, None))
                continue
            path, body, ctype = p
            sent = _send(openers[step.as_user], base, step.method, path, body, ctype)
            out[step.route].append(sent)
            try:
                last_id = str(json.loads(sent.body or "")["id"]) or last_id
            except (ValueError, KeyError, TypeError):
                pass
            time.sleep(gap)
    return out


def drive(opener, base: str, method: str, path: str, n: int, gap: float, body: Optional[str]) -> list[Sent]:
    """Strictly sequential: attribution per request is the whole point, and
    the app's limiter allows 60/s per session."""
    sent = []
    for _ in range(n):
        sent.append(_send(opener, base, method, path, body))
        time.sleep(gap)
    return sent


def read_container_logs(container: str, since_epoch: Optional[float]) -> str:
    argv = ["docker", "logs"]
    if since_epoch is not None:
        argv += ["--since", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since_epoch - 1))]
    proc = subprocess.run(argv + [container], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"docker logs failed: {proc.stderr.strip()}")
    return proc.stdout + proc.stderr  # uvicorn writes to stderr


def _login(opener, base: str, username: str, password: str) -> None:
    sent = _send(opener, base, "POST", "/auth/login",
                 json.dumps({"username": username, "password": password}))
    if sent.status != 200:
        raise RuntimeError(f"login failed: HTTP {sent.status}")


def _opener():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def _clock_skew(me: Sent) -> timedelta:
    """Container clock minus host clock, from /attendance/me's server_now. The
    Docker VM drifts enough that a host-stamped self-close can precede its
    own punch-in. Zero when the field is missing."""
    try:
        server_now = datetime.fromisoformat(json.loads(me.body or "")["server_now"].replace("Z", "+00:00"))
    except (ValueError, KeyError, TypeError):
        return timedelta(0)
    return server_now - datetime.now(timezone.utc)


def _common_flags(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--base", default="http://localhost:8124")
    ap.add_argument("--container", default="inventory-local")
    ap.add_argument("--gap", type=float, default=0.05)


def run_sweep(args) -> int:
    """Every catalogued route through the Phase 1 instrument, ranked by
    repeating cgroup growth. Exit 0 clean, 1 any failed/skipped route, 2
    container/Docker/login lost."""
    from scripts.memprobe_routes import CATALOGUE, RouteResult, enumerate_routes, plan, rank, render_sweep, to_csv

    owner = _opener()
    try:
        _send(owner, args.base, "GET", "/healthz", None)
    except (urllib.error.URLError, OSError) as exc:
        print(f"container not reachable at {args.base}: {exc}", file=sys.stderr)
        return 2

    from app.database import SessionLocal
    from app.main import app
    from tests.e2e import _seed

    start = time.time()
    db, seed, aborted = SessionLocal(), None, False
    sent_by_route: dict[str, list[Sent]] = {}
    start_sent = end_sent = None
    samples = {}
    try:
        _seed.sweep_debris(db)
        seed = _seed.build(db)
        tokens = {**vars(seed), "barcode": seed.item_barcode, "wo": seed.work_order_number}
        routes, _ = enumerate_routes(app)
        p = plan(routes, CATALOGUE, tokens, args.only)
        try:
            _login(owner, args.base, seed.owner_username, _seed.SEED_PASSWORD)
            skew = _clock_skew(_send(owner, args.base, "GET", "/attendance/me", None))
            start_sent = _send(owner, args.base, "GET", "/healthz", None)
            for group in p.groups:
                openers = {"owner": owner}
                if any(s.as_user == "technician" for s in group):
                    # Archiving the technician revokes their sessions: log in
                    # again before every group that uses the technician jar.
                    openers["technician"] = _opener()
                    _login(openers["technician"], args.base, seed.technician_username, _seed.SEED_PASSWORD)
                for route, sent in run_group(openers, args.base, group, tokens, args.n, args.gap, skew=skew).items():
                    sent_by_route.setdefault(route, []).extend(sent)
            end_sent = _send(owner, args.base, "GET", "/healthz", None)
        except (RuntimeError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            aborted = True
        try:  # an aborted run still reports what it measured
            time.sleep(0.5)  # let the last line flush before reading
            wanted = {s.req for v in sent_by_route.values() for s in v if s.req}
            wanted |= {s.req for s in (start_sent, end_sent) if s and s.req}
            samples = parse_request_lines(read_container_logs(args.container, start), wanted)
        except (RuntimeError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            aborted = True
    finally:
        if seed is not None:
            _seed.destroy(db, seed)
        db.close()

    def expect_for(route):
        entry = CATALOGUE.get(route)
        return entry.expect if entry else None

    results = [RouteResult(route, aggregate(sent, samples), expect_for(route), "measured")
               for route, sent in sent_by_route.items()]
    rows = rank(results)
    print(render_sweep(rows, samples.get(start_sent.req) if start_sent else None,
                       samples.get(end_sent.req) if end_sent else None, p, args.container, args.n))
    if args.out:
        to_csv(rows, p.skipped, p.excluded, args.out)
    if aborted:
        return 2
    return 1 if p.skipped or any(r.state == "failed" for r in rows) else 0


def main(argv: Optional[list[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["jumps"]:
        from scripts.memprobe_soak import run_jumps
        ap = argparse.ArgumentParser(prog="memprobe.py jumps", description=run_jumps.__doc__)
        ap.add_argument("file", nargs="?", help="log text; '-' for stdin; omit to read --container")
        ap.add_argument("--step", type=int, default=8)
        ap.add_argument("--window", type=float, default=30.0)
        ap.add_argument("--container", default="inventory-local")
        return run_jumps(ap.parse_args(argv[1:]))
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
    if argv[:1] == ["sweep"]:
        ap = argparse.ArgumentParser(prog="memprobe.py sweep", description=run_sweep.__doc__)
        _common_flags(ap)
        ap.add_argument("--out", help="CSV path, written even when the run fails")
        ap.add_argument("--only", help="substring filter on 'METHOD /path'")
        return run_sweep(ap.parse_args(argv[1:]))

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("method"); ap.add_argument("path")
    ap.add_argument("--body")
    _common_flags(ap)
    args = ap.parse_args(argv)

    opener = _opener()
    try:
        _send(opener, args.base, "GET", "/healthz", None)
    except (urllib.error.URLError, OSError) as exc:
        print(f"container not reachable at {args.base}: {exc}", file=sys.stderr)
        return 2

    # Imported here so tests/test_memprobe.py never opens the database.
    from app.database import SessionLocal
    from tests.e2e import _seed

    start = time.time()
    db = SessionLocal()
    seed = None
    try:
        _seed.sweep_debris(db)
        seed = _seed.build(db)
        path = args.path.replace("{barcode}", seed.item_barcode).replace("{wo}", seed.work_order_number)
        try:
            _login(opener, args.base, seed.owner_username, _seed.SEED_PASSWORD)
            baseline_sent = _send(opener, args.base, "GET", "/healthz", None)
            sent = drive(opener, args.base, args.method.upper(), path, args.n, args.gap, args.body)
            time.sleep(0.5)  # let the last line flush before reading
            wanted = {s.req for s in sent if s.req} | {baseline_sent.req}
            samples = parse_request_lines(read_container_logs(args.container, start), wanted)
        except (RuntimeError, OSError) as exc:
            # OSError covers a vanished docker CLI (FileNotFoundError) and a
            # dropped connection mid-drive (URLError). Teardown still runs.
            print(str(exc), file=sys.stderr)
            return 2
    finally:
        if seed is not None:
            _seed.destroy(db, seed)
        db.close()

    summary = aggregate(sent, samples)
    print(render(f"{args.method.upper()} {path}", args.container, samples.get(baseline_sent.req), summary))
    return 1 if summary.unmatched else 0


if __name__ == "__main__":
    sys.exit(main())
