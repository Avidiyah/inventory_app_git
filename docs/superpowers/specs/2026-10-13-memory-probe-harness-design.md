# Memory Probe Harness — Phase 1 of the endpoint memory suite

**Status:** draft for review · **Backlog:** `docs/open-work.md` → N-MEMORY-CRASH
**Soft budget:** 1,800 words

## Goal

One script that drives one route against the `inventory-local` container
N times and prints that route's memory cost from the container's own
`event=request` lines. It is the measuring instrument every later phase
(sweep, soak, fix-and-guard) is built on. Phase 1 is done when one route
produces a readable table and the idle baseline (`cg_mb=178`,
`rss_mb=112`) reproduces in that table.

## Non-goals (later phases own these)

- Driving more than one route per run, enumerating `app.routes`, ranking
  routes (Phase 2).
- Long runs, realistic traffic mixes, trend lines (Phase 3).
- Any fix, any guard test, the `render.yaml` plan correction (Phase 4).
- Machine-readable output (CSV/JSON). Added in Phase 2 when the sweep
  needs it; the aggregation is a pure function so the format is a
  one-liner then.
- Measuring on the host. The script runs on the host but only reads
  figures the container logged; host readings are `-` and are ignored.

## Where it lives

`backend/scripts/memprobe.py`, one file under 500 lines, invoked from
`backend/` with the project venv like `scripts/create_owner.py`. It is
not a test and does not go under `tests/` (the `tests/e2e` conftest
launches Chromium for anything collected there; see
`tests/test_e2e_guard.py`). A small `backend/tests/test_memprobe.py`
covers the pure parsing and aggregation only.

## Interface

```
python scripts/memprobe.py GET /items --n 50
python scripts/memprobe.py POST /items/search --body '{"q":"wid"}' --n 20
```

| Flag | Default | Meaning |
|---|---|---|
| `METHOD PATH` | required | One route. Path may carry a query string. |
| `--n` | 20 | Requests to send. |
| `--body` | none | JSON string sent as the request body. |
| `--base` | `http://localhost:8124` | Where the container listens. |
| `--container` | `inventory-local` | Name passed to `docker logs`. |
| `--gap` | 0.05 | Seconds between requests (see Pacing). |

Exit code 0 when every request matched a log line, 1 otherwise. The
table prints either way.

## Flow

1. **Seed and sign in.** Import `tests.e2e._seed` (the `sys.path`
   insertion `scripts/create_owner.py` already uses), call
   `sweep_debris` then `build` against the database `DATABASE_URL`
   names, which the container shares. Log in as the seed owner with
   `SEED_PASSWORD` via `POST /auth/login`; keep the session cookie in a
   stdlib `http.cookiejar`. The seed also supplies a real item and
   work order for routes that need an id in the path (the caller
   substitutes `{item}`, `{wo}` tokens in PATH; nothing else is
   templated).
2. **Baseline.** Send one `GET /healthz` and record its `cg_mb` /
   `rss_mb` as the idle reading. This is the line that proves the
   documented baseline.
3. **Drive.** Send the route N times sequentially, `--gap` seconds
   apart. Collect each response's status and `X-Request-ID` header.
4. **Read back.** Run `docker logs --since <start> <container>`
   (stdout and stderr), keep lines whose `req=` is in the collected set,
   parse `status`, `ms`, `rss_mb`, `cg_mb`, `cg_delta_mb`,
   `rss_delta_mb` (`-` → absent).
5. **Tear down.** `_seed.destroy` in a `finally`, so a crashed run
   leaves nothing (and `sweep_debris` covers the one case it cannot).
6. **Print.**

## Correlation by request id, not by time

Each response echoes `X-Request-ID`, and the log line carries the same
value as `req=`. Matching on it means a concurrent `/healthz` poll or
any other traffic cannot be mis-attributed to the probed route. The
`--since` window is only a cheap pre-filter. A sent request with no
matching line is reported as unmatched, never silently dropped: the
request that tips a container over is often the one whose line is lost.

## Pacing and the rate limit

`app.domain.rate_limit` allows 60 requests per second per session and a
refused request is not logged as a normal request line. Fast routes
from a tight loop would trip it, and a burst would also smear one
request's allocation into its neighbour's delta. The harness is
therefore strictly sequential with a default 50 ms gap (20 req/s). A
429 is counted as a failed request in the table; the fix is a larger
`--gap`, not a retry.

## The table

```
route        GET /items     n=50   container=inventory-local
baseline     cg_mb=178  rss_mb=112        (idle, from /healthz)
statuses     200×50
matched      50/50

                 first   rest(sum)   rest(max)   rest(mean)
cg_delta_mb         12          3           1         0.06
rss_delta_mb         9          2           1         0.04

drift        cg_mb 178→193 (+15)   rss_mb 112→123 (+11)   over 50 requests
ms           p50=6  max=41
```

- **first vs rest.** The first call of a route pays one-time costs
  (imports, pool warm-up, caches). Reporting it apart from the steady
  state is what lets Phase 2 rank routes by *repeating* growth rather
  than by warm-up.
- **drift.** First and last absolute readings across the run. The
  per-request deltas should sum to roughly the drift; a large gap
  between them means other traffic or a background task moved memory,
  and the reader should distrust the run.
- Absent values print `-` and are excluded from sums and means; the
  `matched` line says how many lines had readings.

## Components

| Unit | Does | Depends on |
|---|---|---|
| `parse_request_lines(text, wanted_ids) -> list[Sample]` | logfmt split, field coercion, `-` handling | nothing |
| `aggregate(samples) -> Summary` | first/rest, drift, matched count, latency percentiles | nothing |
| `render(summary) -> str` | the table | nothing |
| `drive(session, method, path, n, gap) -> list[Sent]` | HTTP loop, collects ids and statuses | `urllib.request`, cookie jar |
| `main()` | argparse, seed lifecycle, `docker logs`, exit code | `tests.e2e._seed`, `subprocess` |

The first three are pure and are what `test_memprobe.py` covers with
pasted log lines (including a `-` line, an unmatched id, and a 429).
No test drives HTTP or Docker; that is the acceptance run below.

## Error handling

| Condition | Behaviour |
|---|---|
| Container not reachable at `--base` | Exit 2 before seeding, with the URL in the message. |
| Login fails | Exit 2 after teardown. |
| `docker` CLI missing or container name wrong | Exit 2 after teardown, with the CLI's stderr. |
| Non-2xx response | Counted in `statuses`; its deltas still aggregated if logged. |
| Unmatched request id | Counted in `matched`; exit 1. |
| Memory field `-` | Treated as absent; never raises. |

Nothing is retried. The harness measures; it does not recover.

## Constraints carried from the repo

- Stdlib only on the HTTP and log side (`urllib.request`,
  `http.cookiejar`, `subprocess`, `json`, `statistics`). No `httpx`,
  no `requests`, no `psutil`.
- Reads `backend/.env` only through `app.database`'s existing
  `load_dotenv`; never edits `.env` or the container env copy.
- No new rows outside the `E2E-` prefix. Seeded rows are visible in the
  dev database for the length of a run, as the e2e suite already
  accepts.
- No push. Pushing `main` deploys to production.

## Acceptance (the Execute phase's exit)

Run in order against the live container, pasting the tables into the
completion report:

1. `GET /healthz --n 20` — baseline line shows `cg_mb≈178`,
   `rss_mb≈112`; `rest(sum)` is 0 or near it; `matched 20/20`.
2. `GET /items --n 50` — a non-trivial route produces a full table with
   a visible `first` cost and a small `rest`.
3. `pytest tests/test_memprobe.py` passes on the host.

Those three results, plus the script's usage line, are also the entire
documentation update: one bullet under *Local Docker reproduction* in
`docs/current-state.md` naming the script, and the N-MEMORY-CRASH entry
in `docs/open-work.md` marked "Phase 1 shipped".

## Decisions made without asking (flag any you want changed)

| Decision | Alternative rejected | Why |
|---|---|---|
| Seed owner login via `tests.e2e._seed` | `--user/--password` flag for a real account | Reuses teardown-safe rows and gives Phase 2 its mutation targets for free; no credentials on the command line. |
| Correlate by `X-Request-ID` | Time window around each request | Immune to `/healthz` polls and clock skew between host and container. |
| Sequential with a fixed gap | Concurrent workers | Attribution per request is the whole point; concurrency smearing is a documented caveat of the telemetry. |
| Stdlib HTTP | `httpx2` from dev requirements | One fewer import to break; the harness sends two kinds of request. |
| Plain-text table only | CSV/JSON now | Phase 2 adds it when a consumer exists. |
