# Memory Soak — Phase 3 of the endpoint memory suite

**Status:** draft for review · **Backlog:** `docs/open-work.md` → N-MEMORY-CRASH
**Builds on:** `2026-10-13-memory-sweep-p2-design.md` (Phase 2)
**Soft budget:** 1,800 words

## Goal

Production memory is a staircase: stable, jump, stable, jump, until the
instance dies. Phase 2 showed no route repeats growth at 20 requests, so the
jump is a discrete event, not a drip. Phase 3 adds two commands: `jumps`,
which reads any log text and prints what happened just before each step up,
and `soak`, which runs mixed concurrent traffic for a long time so a step can
be provoked locally. Phase 3 is done when `jumps` names the carrying line
and the preceding window for every step in a log, and a multi-hour `soak`
completes with a trend table, a jumps report, and a CSV.

## Non-goals (later phases own these)

- Fixing or guarding whatever a jump names (Phase 4).
- WebSocket clients and the outbound netfacilities jobs; still excluded. A
  jump window that names a realtime or job event is the trigger to build
  that driver, as its own phase.
- Per-request attribution under concurrency. The telemetry smears
  neighbours; `soak` finds windows, `jumps` reads them.

## Interface

```
python scripts/memprobe.py jumps render-export.log --step 8 --window 30
python scripts/memprobe.py jumps --container inventory-local
python scripts/memprobe.py soak --minutes 120 --workers 3 --out soak.csv
python scripts/memprobe.py soak --minutes 20 --only /hub
```

| Flag | Default | Meaning |
|---|---|---|
| `jumps FILE` | none | Log text; `-` reads stdin. Omit to read `--container` via `docker logs`. |
| `--step` | 8 | MB rise between consecutive samples that counts as a jump. |
| `--window` | 30 | Seconds of log before each jump to print. |
| `--minutes` | 60 | Soak duration. Ctrl-C ends it early and still reports. |
| `--workers` | 3 | One writer plus `workers-1` readers (below). |
| `--n` | 5 | Requests per route per pass (sweep default is 20). |
| `--gap` | 0.1 | Seconds between requests per worker. |
| `--sample` | 5 | Seconds between `/healthz` samples from the sampler thread. |
| `--only`, `--out`, `--base`, `--container` | as Phase 2 | `--out` is the sample series, not a route table. |

Exit codes: `jumps` 0 always, 2 when no line carried `cg_mb`. `soak` as
the sweep: 0 clean, 1 any failed route, 2 container/Docker/login lost.

## Where it lives

| File | Change |
|---|---|
| `backend/scripts/memprobe_soak.py` | New. Pure functions `parse_lines`, `find_jumps`, `tally`, `render_jumps`, `render_trend`, `series_csv`; the worker and sampler loops. Under 500 lines. |
| `backend/scripts/memprobe.py` | `jumps` and `soak` subparsers that call into the new module; reuses `_opener`, `_login`, `_send`, `_clock_skew`, `run_group`, `read_container_logs`. Must stay ≤ 500 lines (409 today); if the two entry points push it over, `run_sweep` moves to `memprobe_routes.py`. |
| `backend/tests/test_memprobe_soak.py` | Pure-function tests. `test_memprobe.py` is at 317 lines and stays as is. |

## Jump finder

**Input.** Every line of the text, in file order. A line is kept when it
contains an `event=` token; anything before the first `key=value` token (a
Render export prefix, a docker timestamp) is ignored. `ts=` is parsed as
ISO 8601; a line without `ts=` or `event=` is dropped. This makes one parser
serve `docker logs`, a Render log export, and a pasted excerpt.

**Series.** The samples are the kept lines that carry `cg_mb` (request
lines, including `/healthz` polls). A jump is a rise of at least `--step`
between consecutive samples. The sample that shows the new level is the
**carrier**; its own `cg_delta_mb` says whether the request on that line
allocated the step (carrier delta ≈ step) or merely observed it (delta ≈ 0,
so the work happened between request lines: a background task, a WebSocket
broadcast, a job).

**Window.** For each jump, every kept line in the `--window` seconds before
the carrier's `ts`, oldest first, one line each: `ts` offset in seconds
before the jump, `event`, and for request lines `method path status ms
cg_delta_mb`; for other events the remaining fields verbatim. Nothing is
filtered out of the window: the realtime and netfacilities events are the
ones that explain a carrier with zero delta.

**Tally.** Across all jumps, each route and each non-request event is
counted by the number of jump windows it appears in. The tally is printed
last, sorted by that count then by name. A route present in every window
is the lead; a route present in every window and absent from the plateaus
between is the answer. The plateau check is the reader's, not the tool's.

**Summary line.** First to last sample level, total rise, number of jumps,
and the sum of their sizes. A total rise well above the jump sum means the
growth is gradual at this `--step`; lower it. This is the check that the
threshold did not hide the staircase.

```
jumps   samples=14,212  span=2026-10-14T06:01Z→2026-10-14T18:40Z
levels  181→944 MB  rise +763   jumps=6  jump sum=741  (step≥8)

#1  2026-10-14T09:12:41Z  181→309 (+128)  carrier GET /healthz cg_delta_mb=0
   -27.4s  request      GET  /hub/report            200  412ms  Δ+2
   -26.1s  realtime.x   ...
   -0.8s   request      POST /items/dispense-exports 200  3,118ms  Δ+121
…
tally  (of 6 windows)
   6  POST /items/dispense-exports
   6  GET  /healthz
   2  realtime.wakeup_failed
```

## Soak driver

**Seed, login, baseline.** As the sweep, once: reachability check,
`sweep_debris`, `build`, owner login, clock skew, start `/healthz`.

**Workers.** Threads, each with its own opener and its own login, so each
is its own rate-limit caller (60/s per session; `--gap` 0.1 is 10/s per
worker). Worker 0 is the **writer**: it runs the full Phase 2 plan in
rotation exactly as `run_sweep` does, including the cycles and the
technician re-login per group. Workers 1..N are **readers**: they run only
the plan's token-free or seed-token GET steps, each in a different shuffled
order. Readers never mutate, so no two workers race a cycle, and the shape
(one person changing things, several looking) is what the app sees in use.

**Passes.** Each worker loops its step list until the deadline or the stop
flag. A pass is one full rotation of a worker's list; the writer's pass
count is the trend table's row count.

**Sampler.** One more thread sends `GET /healthz` every `--sample` seconds
through the owner opener, so the series has a reading every few seconds
even while a worker is stuck in a slow route. `/healthz` is exempt from the
limiter.

**Stop.** The deadline, Ctrl-C (`KeyboardInterrupt` sets the stop flag;
workers check it between requests), or a dropped connection in any worker
(sets the flag, marks the run aborted). The main thread then joins the
workers, sends the end `/healthz`, sleeps 0.5 s, reads `docker logs
--since start` once, and reports. Teardown in `finally`, as before.

**Report.** Three parts, always printed, even on abort:

1. Trend table: one row per writer pass: pass number, elapsed, `cg_mb` and
   `rss_mb` from the nearest sample at pass end, rise since start, requests
   sent so far, failed so far.
2. The `jumps` report over the whole container log of the run, with the
   default `--step`, so a provoked step is read exactly as a production one.
3. Failed routes, as the sweep prints them: route, status counts, which
   worker. A reader seeing a non-2xx on a route the writer just mutated
   (a 404 on an archived work order) is expected and is listed under
   `expected` when the status matches the catalogue's `expect` or is 404 on
   a route whose writer cycle archives or deletes; anything else is failed.

`--out` writes the sample series: `ts, cg_mb, rss_mb, method, path,
cg_delta_mb, worker` for every request line in the run, so Excel can chart
the staircase and filter by worker.

## Failure semantics

| Condition | Behaviour | Exit |
|---|---|---|
| Container unreachable, login fails, Docker CLI missing | As Phase 2 | 2 |
| Worker connection dropped | Stop flag, aborted, report what ran | 2 |
| Ctrl-C | Stop flag, full report, exit by the other rules | 0/1 |
| Any failed route (above) | Listed | 1 |
| 429 from a worker | Failed route; raise `--gap` or lower `--workers` | 1 |
| `jumps` input has no `cg_mb` line | Message naming the file | 2 |

Nothing is retried.

## Tests

`tests/test_memprobe_soak.py`, pure functions only:

- `parse_lines`: docker prefix, Render prefix, pasted excerpt, a line
  without `ts=`, a quoted value with spaces.
- `find_jumps`: two steps in a synthetic series; a gradual rise below
  `--step` yields no jumps and the summary shows rise > jump sum; the
  carrier delta distinguishes allocating from observing.
- `tally`: a route in every window outranks one in some.
- Reader step selection: only GET steps, no cycle members, seed tokens
  resolved, shuffled per worker with a fixed seed.
- `render_trend`, `series_csv`: shape.

No test drives HTTP, threads or Docker; the acceptance run is the proof.

## Acceptance

1. `pytest tests/test_memprobe_soak.py` and `tests/test_memprobe.py` pass
   on the host.
2. `jumps --container inventory-local` over the current container log
   prints the summary and the (likely empty) jump list; `jumps` over a
   pasted file with a Render prefix parses it.
3. `soak --minutes 5 --workers 3` against a fresh `inventory-local`
   completes: trend rows, jumps report, failed list empty or explained,
   CSV opens. Ctrl-C at minute 1 of a second run still prints the report
   and tears down the seed.
4. `soak --minutes 120 --workers 3 --out soak.csv`. The trend table and
   jumps report go in the completion report. Either a step reproduces and
   the window names a candidate for Phase 4, or the staircase does not
   appear locally and the next readout is a Render log export through
   `jumps` after the next production step.
5. Docs: one bullet under *Local Docker reproduction* in
   `docs/current-state.md` for the two forms; N-MEMORY-CRASH in
   `docs/open-work.md` marked "Phase 3 shipped" with the outcome of step 4
   and the production readout instruction.

## Constraints carried forward

Stdlib only (`threading`, `queue`, `random`, `datetime` join the list);
`.env` through `app.database`; no rows outside `E2E-`; no push. Files
under 500 lines; the soak module is logic, the catalogue stays data.

## Decisions

| Decision | Alternative rejected | Why |
|---|---|---|
| `jumps` first, works on any log text | Local reproduction only | The telemetry deployed today will capture the next production step; reading it costs nothing. |
| Jump = rise between consecutive samples | Rolling baseline, change-point detection | Samples every few seconds make a step visible in one interval; the summary's rise-vs-jump-sum check catches the miss. |
| Carrier delta tells allocating from observing | Blame the carrier | A `/healthz` carrier with zero delta means non-request work; the window holds every event for that reason. |
| Tally by windows-present | Sum of deltas in windows | A culprit that allocates in a job carries no delta on its own line. |
| One writer, N readers | All workers run everything | Cycles race across threads; readers cannot. |
| Own login per worker | Shared session | Rate limit is per session; threads sharing a cookie jar also race it. |
| Sampler thread | Rely on worker lines | A slow route starves the series exactly when it matters. |
| CSV is the sample series | Per-route table as Phase 2 | The staircase is a time series; Excel charts it. |
| Ctrl-C reports | Abort silently | A two-hour run must never lose its readout. |
| Reader 404 after a writer archive is expected | Failed | Otherwise every long run exits 1 for a known race. |
| WebSocket and jobs stay excluded | Build a WS client now | Wait for a window to name them. |
