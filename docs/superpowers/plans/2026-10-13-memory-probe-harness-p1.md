# Memory Probe Harness (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `backend/scripts/memprobe.py` drives one route against the `inventory-local` container N times and prints that route's memory cost from the container's own `event=request` lines.

**Architecture:** Three pure functions (parse logfmt lines → aggregate by request id → render a table) tested on the host, plus a thin `main()` that seeds via `tests.e2e._seed`, logs in with a stdlib cookie jar, sends requests sequentially, and reads `docker logs` back. HTTP and Docker are exercised only by the acceptance run.

**Tech Stack:** Python 3.12 stdlib (`urllib.request`, `http.cookiejar`, `subprocess`, `json`, `statistics`, `dataclasses`, `argparse`); existing `tests.e2e._seed`; pytest.

**Spec:** `docs/superpowers/specs/2026-10-13-memory-probe-harness-design.md` — the plan does not restate it; read it first.

## Global Constraints

- Stdlib only on the HTTP and log side; no `httpx`, `requests`, `psutil`.
- Never edit `backend/.env` or the container env copy; `app.database`'s `load_dotenv` is the only env reader.
- New rows only under the `E2E-` prefix; `_seed.destroy` in a `finally`.
- `scripts/memprobe.py` under 500 lines; the `tests.e2e._seed` / `app.*` imports stay inside `main()` so `test_memprobe.py` never touches the database.
- Default gap 0.05 s, strictly sequential (rate limit is 60/s per session).
- Exit codes: 0 all matched · 1 some unmatched · 2 environment/login/docker failure.
- Run targeted tests only (`tests/test_memprobe.py`). Do not push; pushing `main` deploys.

## Review Focus

1. A 429 from the rate limiter still passes through `log_request`, so it has an `X-Request-ID` and a `status=429` line: counted under `statuses`, not lost. Test in Task 2 (`test_aggregate_counts_a_429_as_a_status`).
2. A `request.error` line has no `status=`: parsed with `status=None`, still matched. Test in Task 1 (`test_parse_accepts_an_error_line_without_status`).
3. `--n 1`: the "rest" set is empty; mean must be `None`, not `ZeroDivisionError`. Test in Task 2 (`test_aggregate_with_one_request_has_no_rest`).
4. A response with no `X-Request-ID` header (proxy, truncated response): `Sent.req is None`, counted unmatched, exit 1. Test in Task 2 (`test_aggregate_reports_unmatched_ids`).
5. `docker logs` bytes that are not UTF-8: decoded with `errors="replace"`, never raises. Covered by the `encoding`/`errors` arguments in Task 3 (`read_container_logs`); no unit test.

---

### Task 1: Parse request lines

**Files:**
- Create: `backend/scripts/memprobe.py`
- Create: `backend/tests/test_memprobe.py`

**Interfaces:**
- Produces: `Sample` dataclass (`req: str`, `status: int | None`, `ms: int | None`, `rss_mb`, `cg_mb`, `cg_delta_mb`, `rss_delta_mb`: `int | None`) and `parse_request_lines(text: str, wanted: set[str]) -> dict[str, Sample]` keyed by `req`.

- [ ] **Step 1: Write the failing tests**

```python
"""Host-side tests for the pure half of scripts/memprobe.py. No HTTP, no
Docker, no database: the acceptance run in the plan covers those."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import memprobe

LINE = (
    "ts=2026-10-13T15:07:38.974Z level=INFO req={req} event=request method=GET "
    "path=/items status={status} ms={ms} rss_mb={rss} cg_mb={cg} "
    "cg_delta_mb={cgd} rss_delta_mb={rssd}"
)


def _line(req, status=200, ms=5, rss=112, cg=178, cgd=0, rssd=0):
    return LINE.format(req=req, status=status, ms=ms, rss=rss, cg=cg, cgd=cgd, rssd=rssd)


def test_parse_keeps_only_wanted_request_ids():
    text = "\n".join([_line("aaa"), _line("bbb"), "==> starting uvicorn", _line("ccc")])
    out = memprobe.parse_request_lines(text, {"aaa", "ccc"})
    assert set(out) == {"aaa", "ccc"}
    assert out["aaa"] == memprobe.Sample("aaa", 200, 5, 112, 178, 0, 0)


def test_parse_treats_dash_as_absent():
    text = _line("aaa", rss="-", cg="-", cgd="-", rssd="-")
    sample = memprobe.parse_request_lines(text, {"aaa"})["aaa"]
    assert (sample.rss_mb, sample.cg_mb, sample.cg_delta_mb, sample.rss_delta_mb) == (None,) * 4
    assert sample.status == 200


def test_parse_accepts_an_error_line_without_status():
    text = (
        "ts=x level=ERROR req=err1 event=request.error method=POST path=/items "
        "ms=12 rss_mb=120 cg_mb=190 cg_delta_mb=8 rss_delta_mb=8"
    )
    sample = memprobe.parse_request_lines(text, {"err1"})["err1"]
    assert sample.status is None
    assert sample.cg_delta_mb == 8


def test_parse_ignores_non_request_events_with_a_matching_id():
    text = "ts=x level=INFO req=aaa event=auth.login_ok user=o ip=1.2.3.4"
    assert memprobe.parse_request_lines(text, {"aaa"}) == {}
```

- [ ] **Step 2: Run to verify failure**

From `backend/`: `python -m pytest tests/test_memprobe.py -v`
Expected: 4 errors, `ModuleNotFoundError: No module named 'scripts.memprobe'` (collection error counts).

- [ ] **Step 3: Implement**

Create `backend/scripts/memprobe.py`:

```python
"""Drive one route against the inventory-local container N times and print
its memory cost from the container's own `event=request` lines.

    python scripts/memprobe.py GET /items --n 50
    python scripts/memprobe.py POST /items/search --body '{"q":"wid"}' --n 20

Spec: docs/superpowers/specs/2026-10-13-memory-probe-harness-design.md.
Correlation is by the echoed `X-Request-ID`, never by time, so other
traffic (the platform's /healthz polls, for one) cannot be mis-attributed.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
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
```

- [ ] **Step 4: Run to verify pass**

`python -m pytest tests/test_memprobe.py -v` — Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/memprobe.py backend/tests/test_memprobe.py
git commit -m "feat(memprobe): parse container request lines by request id"
```

---

### Task 2: Aggregate and render

**Files:**
- Modify: `backend/scripts/memprobe.py` (append)
- Modify: `backend/tests/test_memprobe.py` (append)

**Interfaces:**
- Consumes: `Sample`, `parse_request_lines` from Task 1.
- Produces: `Sent` dataclass (`req: Optional[str]`, `status: int`); `Summary` dataclass; `aggregate(sent: list[Sent], samples: dict[str, Sample]) -> Summary`; `render(route: str, container: str, baseline: Optional[Sample], summary: Summary) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
def _sent(*ids, status=200):
    return [memprobe.Sent(i, status) for i in ids]


def _samples(*rows):
    """rows: (req, cg_delta, rss_delta, cg_mb, rss_mb, ms)"""
    return {
        r[0]: memprobe.Sample(r[0], 200, r[5], r[4], r[3], r[1], r[2]) for r in rows
    }


def test_aggregate_separates_first_from_rest_and_reports_drift():
    sent = _sent("a", "b", "c")
    samples = _samples(("a", 12, 9, 190, 121, 40), ("b", 1, 1, 191, 122, 5), ("c", 3, 0, 194, 122, 7))
    s = memprobe.aggregate(sent, samples)
    assert s.sent == 3 and s.matched == 3 and s.unmatched == []
    assert s.first == {"cg_delta_mb": 12, "rss_delta_mb": 9}
    assert s.rest["cg_delta_mb"] == {"sum": 4, "max": 3, "mean": 2.0}
    assert s.rest["rss_delta_mb"] == {"sum": 1, "max": 1, "mean": 0.5}
    assert s.drift == {"cg_mb": (190, 194), "rss_mb": (121, 122)}
    assert (s.ms_p50, s.ms_max) == (7, 40)


def test_aggregate_reports_unmatched_ids():
    sent = [memprobe.Sent("a", 200), memprobe.Sent(None, 200), memprobe.Sent("z", 200)]
    s = memprobe.aggregate(sent, _samples(("a", 0, 0, 178, 112, 5)))
    assert s.matched == 1
    assert s.unmatched == ["<no X-Request-ID>", "z"]


def test_aggregate_with_one_request_has_no_rest():
    s = memprobe.aggregate(_sent("a"), _samples(("a", 5, 2, 183, 114, 9)))
    assert s.first["cg_delta_mb"] == 5
    assert s.rest["cg_delta_mb"] == {"sum": 0, "max": None, "mean": None}


def test_aggregate_excludes_absent_readings_from_sums():
    sent = _sent("a", "b", "c")
    samples = _samples(("a", 1, 1, 180, 113, 5), ("c", 2, 2, 182, 115, 5))
    samples["b"] = memprobe.Sample("b", 200, 5, None, None, None, None)
    s = memprobe.aggregate(sent, samples)
    assert s.rest["cg_delta_mb"] == {"sum": 2, "max": 2, "mean": 2.0}
    assert s.readings == 2


def test_aggregate_counts_a_429_as_a_status():
    sent = _sent("a") + _sent("b", status=429)
    samples = _samples(("a", 0, 0, 178, 112, 5), ("b", 0, 0, 178, 112, 1))
    assert memprobe.aggregate(sent, samples).statuses == {200: 1, 429: 1}


def test_render_prints_dashes_for_absent_values():
    s = memprobe.aggregate(_sent("a"), _samples(("a", 5, 2, 183, 114, 9)))
    text = memprobe.render("GET /items", "inventory-local", None, s)
    assert "baseline     -" in text
    assert "rest(max)" in text and "matched      1/1" in text
```

- [ ] **Step 2: Run to verify failure**

`python -m pytest tests/test_memprobe.py -v` — Expected: new tests FAIL with `AttributeError: ... has no attribute 'Sent'`.

- [ ] **Step 3: Implement**

Append to `backend/scripts/memprobe.py` (add `import statistics` and `from collections import Counter` at the top):

```python
_DELTAS = ("cg_delta_mb", "rss_delta_mb")
_LEVELS = ("cg_mb", "rss_mb")


@dataclass(frozen=True)
class Sent:
    req: Optional[str]  # None when the response carried no X-Request-ID
    status: int


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
    statuses = "  ".join(f"{code}×{n}" for code, n in summary.statuses.items()) or "-"
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
        return f"{_fmt(a)}→{_fmt(b)} ({change})"

    drift = "   ".join(f"{k} {_span(a, b)}" for k, (a, b) in summary.drift.items())
    rows += ["", f"drift        {drift}   over {summary.matched} requests",
             f"ms           p50={_fmt(summary.ms_p50)}  max={_fmt(summary.ms_max)}"]
    if summary.unmatched:
        rows.append(f"unmatched    {' '.join(summary.unmatched)}")
    return "\n".join(rows)
```

- [ ] **Step 4: Run to verify pass**

`python -m pytest tests/test_memprobe.py -v` — Expected: 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/memprobe.py backend/tests/test_memprobe.py
git commit -m "feat(memprobe): aggregate first/rest deltas and drift, render the table"
```

---

### Task 3: Drive, read back, `main()`

**Files:**
- Modify: `backend/scripts/memprobe.py` (append; stays under 500 lines)

**Interfaces:**
- Consumes: everything from Tasks 1–2.
- Produces: `drive(opener, base, method, path, n, gap, body) -> list[Sent]`; `read_container_logs(container, since_epoch) -> str`; `main(argv) -> int`.
- Path tokens: `{barcode}` → `seed.item_barcode`, `{wo}` → `seed.work_order_number` (the seed exposes those, not numeric ids; the spec's `{item}` is this token).

- [ ] **Step 1: Implement**

Append (add `import argparse, json, subprocess, time, urllib.error, urllib.request` and `from http.cookiejar import CookieJar` at the top):

```python
def _send(opener, base: str, method: str, path: str, body: Optional[str]) -> Sent:
    data = body.encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        resp = opener.open(req, timeout=60)
    except urllib.error.HTTPError as err:  # a 4xx/5xx is still a response
        resp = err
    with resp:
        resp.read()
        return Sent(resp.headers.get("X-Request-ID"), resp.status)


def drive(opener, base: str, method: str, path: str, n: int, gap: float, body: Optional[str]) -> list[Sent]:
    """Strictly sequential: attribution per request is the whole point, and
    the app's limiter allows 60/s per session."""
    sent = []
    for _ in range(n):
        sent.append(_send(opener, base, method, path, body))
        time.sleep(gap)
    return sent


def read_container_logs(container: str, since_epoch: float) -> str:
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since_epoch - 1))
    proc = subprocess.run(
        ["docker", "logs", "--since", since, container],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"docker logs failed: {proc.stderr.strip()}")
    return proc.stdout + proc.stderr  # uvicorn writes to stderr


def _login(opener, base: str, username: str, password: str) -> None:
    sent = _send(opener, base, "POST", "/auth/login",
                 json.dumps({"username": username, "password": password}))
    if sent.status != 200:
        raise RuntimeError(f"login failed: HTTP {sent.status}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("method"); ap.add_argument("path")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--body")
    ap.add_argument("--base", default="http://localhost:8124")
    ap.add_argument("--container", default="inventory-local")
    ap.add_argument("--gap", type=float, default=0.05)
    args = ap.parse_args(argv)

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
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
```

- [ ] **Step 2: Smoke it against the live container**

From `backend/` with the venv: `python scripts/memprobe.py GET /healthz --n 3`
Expected: a table, `matched 3/3`, exit 0. If `login failed`, confirm the container's `DATABASE_URL` points at the same Postgres as `backend/.env` (seed rows must be visible to the container).

- [ ] **Step 3: Confirm the unit tests still pass and the file length**

`python -m pytest tests/test_memprobe.py -v` — Expected: 10 PASS. `wc -l scripts/memprobe.py` under 500.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/memprobe.py
git commit -m "feat(memprobe): seed, sign in, drive one route, read docker logs back"
```

---

### Task 4: Acceptance run and docs

**Files:**
- Modify: `docs/current-state.md` (Local Docker reproduction block, one bullet)
- Modify: `docs/open-work.md` (N-MEMORY-CRASH entry)

- [ ] **Step 1: Acceptance runs** (container must be up: `docker ps --filter name=inventory-local`)

```
python scripts/memprobe.py GET /healthz --n 20
python scripts/memprobe.py GET /items --n 50
```

Expected: run 1 baseline `cg_mb≈178 rss_mb≈112`, `rest(sum)` 0 or near, `matched 20/20`. Run 2 a full table with a visible `first` and small `rest`. Paste both tables verbatim into the completion report; they are the Phase 1 evidence.

- [ ] **Step 2: Docs**

`docs/current-state.md`, append to the Local Docker reproduction bullets:

```
- Per-route probe: `python scripts/memprobe.py GET /items --n 50` from
  `backend/` (seeds an `E2E-` owner, signs in, correlates by
  `X-Request-ID`, prints first/rest deltas and drift). Phase 1 of the
  endpoint memory suite; spec
  `docs/superpowers/specs/2026-10-13-memory-probe-harness-design.md`.
```

`docs/open-work.md` N-MEMORY-CRASH: change the trigger line's tail to
"Phase 1 (harness, `scripts/memprobe.py`) shipped 2026-10-13; Phase 2
(sweep) is next." Delete nothing else. Both files also carry last
session's uncommitted tooling documentation; it ships in this commit.

- [ ] **Step 3: Commit**

```bash
git add docs/current-state.md docs/open-work.md
git commit -m "docs: memory probe harness shipped; Docker repro and N-MEMORY-CRASH entries"
```

Do not push. The user decides when `main` deploys.
