# Memory Sweep — Phase 2 of the endpoint memory suite

**Status:** draft for review · **Backlog:** `docs/open-work.md` → N-MEMORY-CRASH
**Builds on:** `2026-10-13-memory-probe-harness-design.md` (Phase 1)
**Soft budget:** 1,800 words

## Goal

One command drives every HTTP route through the Phase 1 instrument and
prints a ranked table naming the routes whose memory cost repeats. Phase 2
is done when a full sweep against `inventory-local` completes, every route
is measured or explicitly excluded, and the ranking plus a CSV come out.

## Non-goals (later phases own these)

- Long runs, traffic mixes, trend lines across runs (Phase 3).
- Any fix or guard test for a route the ranking names (Phase 4).
- Concurrency, the WebSocket, outbound integrations (see Excluded).

## Interface

```
python scripts/memprobe.py sweep --n 20 --out sweep.csv
python scripts/memprobe.py sweep --only /tools --n 5
python scripts/memprobe.py GET /items --n 50        # Phase 1 form, unchanged
```

| Flag | Default | Meaning |
|---|---|---|
| `--n` | 20 | Requests per route (every cycle member gets `n`). |
| `--gap` | 0.05 | Seconds between requests, as Phase 1. |
| `--out` | none | CSV path; written even when the run fails. |
| `--only` | none | Substring filter on `METHOD /path`; excluded and skipped routes outside the filter are not listed. |
| `--base`, `--container` | as Phase 1 | |

Exit 0 when every non-excluded route was measured with matched lines and
only expected statuses; 1 when any route failed, was unmatched, or is
uncatalogued; 2 when the container, Docker CLI or login is unavailable.
Infrastructure loss mid-run stops the sweep, prints what was measured,
writes the CSV, and exits 2.

## Where it lives

| File | Change |
|---|---|
| `backend/scripts/memprobe.py` | `sweep` subcommand (argparse subparsers; the bare `METHOD PATH` form stays the default). One login, one seed, loop over routes reusing `drive` / `parse_request_lines` / `aggregate`. Stays under 500 lines. |
| `backend/scripts/memprobe_routes.py` | `CATALOGUE` dict plus pure functions: `enumerate_routes(app)`, `plan(routes, catalogue, seed, only) -> list[Step]`, `rank(results) -> list[Row]`, `to_csv(rows)`. |
| `backend/tests/e2e/_seed.py` | More prefixed rows (below); `_purge` learns `Tool` by barcode pattern. |
| `backend/tests/test_memprobe.py` | Pure-function tests plus the coverage test. |
| `render.yaml` | `plan: free` → the live 2 GB / 1 CPU plan, in the same commit (backlog instruction). |

## Route enumeration

`enumerate_routes(app)` walks `app.routes`, yields `(method, path)` for
every HTTP method except HEAD/OPTIONS, and records the WebSocket and the
static mount as non-HTTP. Enumeration happens at run time, so a route added
to the app with no catalogue entry appears in the next sweep as **skipped**
and fails the run. The coverage test does the same check at test time so CI
catches it first.

Today's surface: 125 HTTP routes, one WebSocket, one mount.

## Catalogue

`CATALOGUE: dict[str, Entry]`, keyed `"METHOD /path"` exactly as enumerated.
A GET with no path tokens and no body needs no entry. Every other route
needs one, or the sweep lists it as skipped.

| Field | Meaning |
|---|---|
| `body` | JSON string. `{prefix}` → seed prefix, `{seq}` → request index within the route. Created rows therefore carry the `E2E-` prefix and are unique per request. |
| `file` | Fixture path relative to `backend/`, sent as multipart `file`. Stdlib `email`-free encoder, ~15 lines, boundary + CRLF. |
| `cycle` | Ordered list of route keys run in rotation; see Cycles. Declared once, on the first member. |
| `expect` | A status that is the correct answer for this route (404 for `GET …/enrich/{job_id}`). Any other non-2xx marks the route failed. |
| `exclude` | Reason string. The route prints under *excluded* and never affects the exit code. |
| `token` | Literal overrides for path tokens the seed cannot supply (`{job_id}` → a fixed UUID). |

### Path tokens

Tokens resolve by name from the Seed dataclass fields, so `{work_order_id}`
reads `seed.work_order_id`. Phase 1's `{barcode}` and `{wo}` keep working
(`{wo}` aliases `work_order_number`; `{number}` too). Unresolvable token →
skipped with the token named.

### Cycles

A mutating route that succeeds once per state sits in a cycle that returns
the seed to its starting state. The sweep sends the cycle in rotation until
every member has `n` requests; each member is ranked as its own route. Rules:

- A route belongs to at most one cycle.
- A create/delete pair is a cycle of 2 where the delete's path token comes
  from the create response's `id` (top-level JSON) before the seed.
- The work-order lifecycle closes through `PATCH /work-orders/{work_order_id}`
  with body `{"status":"created"}`; that PATCH entry is ranked like any
  other and belongs only to this cycle.
- Archive/restore (users, work orders), checkout/return (tools), punch-in/
  punch-out, hold/resume, signature post/delete, cancel after create are
  cycles of 2.
- A reset step is never hidden: every request sent is a ranked route.

The plan derives the exact cycle lists from the domain transition tables
(`app/domain/work_orders.py`, `tools.py`, `attendance.py`,
`material_requests.py`, `mass_staging.py`) and the e2e journeys that already
drive them.

### Excluded routes

| Route | Reason |
|---|---|
| `WS /ws` | No stdlib WebSocket client. |
| `POST /auth/login`, `POST /auth/logout` | Login is measured once per run as the sign-in step; logout drops the session. |
| `POST /push/subscribe`, `POST /push/unsubscribe` | Needs a browser subscription object and VAPID keys. |
| `POST /users/{user_id}/reset-password` | Changing a password mid-sweep breaks later routes. |
| `POST /integrations/netfacilities/cloud/auth/start` | Opens a Playwright session against the real site. |
| `POST /integrations/netfacilities/work-orders/enrich` | Starts a job calling the external API. |
| `POST /integrations/netfacilities/cloud/downloads/import` | Ingests an external download. |

The read-only integration GETs and the cancel route stay in. `/docs`,
`/redoc`, `/openapi.json`, `/db-test`, `/service-worker.js`, `/` and
`/workorder_card/{number}` are swept as ordinary GETs. `POST /push/test`
is swept; with no subscriptions it is a no-op.

## Seed extension

`_seed.build` adds, all prefixed and created through the services the
routes themselves use:

| Row | Seed field(s) |
|---|---|
| Technician user | `user_id`, `technician_username` |
| Tool | `tool_id`, `tool_barcode` |
| Transaction on the seed item | `transaction_id` |
| Mass stage, one slot holding the seed WO, one stage item | `stage_id`, `slot_id`, `stage_item_id` |
| Material request for the seed item | `request_id` |
| Closed punch for the technician | `punch_id` |
| Labor line and item line on the seed WO | `labor_id`, `wo_item_id` |
| Existing | `work_order_id`, `item_id` added beside the number/barcode |

`_purge` gains `Tool` by `barcode LIKE pattern`; every other new row is
already reachable from the work-order, item or user ids it purges. The
e2e suite keeps working: it reads only the fields it already used.

## Flow

1. Reachability check, seed, login: as Phase 1, once.
2. `GET /healthz` → start baseline.
3. `plan()` expands the catalogue into steps; `--only` filters.
4. For each route (cycles interleaved): `drive` as Phase 1, collect ids.
   A dropped connection stops the sweep (exit 2 path).
5. `GET /healthz` → end baseline. Sleep 0.5 s, `docker logs --since start`
   once, `parse_request_lines` with every id from the run.
6. `aggregate` per route, `rank`, print, write CSV, teardown in `finally`.

One `docker logs` read at the end, not one per route: the pre-filter window
is the whole run and correlation is by request id, as Phase 1 established.

## Output

```
sweep        routes=125 measured=116 failed=1 skipped=0 excluded=8 (+ws)   n=20  container=inventory-local
baseline     start cg_mb=178 rss_mb=112   end cg_mb=241 rss_mb=160   drift +63 / +48

rank  route                               first  rest(sum) rest(max) rest(mean)  rss(sum)  p50ms  statuses
   1  GET /hub/report/export                 14       41         6       2.16        30     88  200×20
   2  POST /items/dispense-exports            9       18         3       0.95        12     41  200×20
   …
 116  GET /healthz                            0        0         0       0.00         0      2  200×20

failed
  POST /transactions/adjust     422×20  (unexpected status)
skipped
  POST /new-route               no catalogue entry
excluded
  WS /ws                        no stdlib WebSocket client
  …
```

- Ranking key: `rest(sum)` of `cg_delta_mb`, descending; ties by `rest(max)`.
- `first` is shown but never ranked on.
- CSV columns: `method, path, n, first_cg, rest_sum_cg, rest_max_cg,
  rest_mean_cg, first_rss, rest_sum_rss, drift_cg, p50_ms, max_ms,
  statuses, matched, state` where `state` ∈ measured/failed/skipped/excluded.
- Absent readings print `-` and are excluded from sums, as Phase 1.

## Failure semantics

| Condition | Route state | Exit |
|---|---|---|
| All statuses 2xx or `expect`, all lines matched | measured | — |
| Any other status, incl. 429 and 5xx | failed | 1 |
| Any request id with no log line | failed (unmatched count shown) | 1 |
| No catalogue entry, unresolvable token | skipped | 1 |
| `exclude` set | excluded | — |
| Container/Docker/login lost | run stops | 2 |

Nothing is retried; a 429 means a larger `--gap`.

## Tests

`tests/test_memprobe.py` grows:

- `plan()` with a toy catalogue: token substitution, `{seq}` uniqueness,
  cycle rotation order, id capture from a create response, `--only`.
- `rank()` ordering and tie-break; absent values.
- `to_csv()` row shape.
- Coverage: import `app.main`, assert every enumerated route is catalogued,
  token-free GET, or excluded. This is the drift guard CI runs.

No test drives HTTP or Docker. The acceptance run below is the proof.

## Constraints carried forward

Stdlib only; `.env` read through `app.database`; no rows outside `E2E-`;
no push (`main` deploys). `memprobe.py` ≤ 500 lines; the catalogue file
may grow with the route count but stays data, not logic.

## Acceptance

1. `pytest tests/test_memprobe.py` passes on the host (venv interpreter,
   cwd `backend/`).
2. `sweep --only /healthz --n 20` reproduces the Phase 1 baseline table
   shape inside the sweep output.
3. Full `sweep --n 20 --out sweep.csv` against a fresh `inventory-local`:
   `skipped=0`, `failed=0`, every excluded route listed with its reason,
   the CSV opens with one row per route. Table pasted into the completion
   report.
4. Docs: one bullet under *Local Docker reproduction* in
   `docs/current-state.md` for the sweep form; N-MEMORY-CRASH in
   `docs/open-work.md` marked "Phase 2 shipped" with the top five routes
   from the acceptance run; the `render.yaml` note removed once fixed.

## Decisions

| Decision | Alternative rejected | Why |
|---|---|---|
| Sweep everything with a hand-written catalogue | GET-only | User choice: the growth may live in a mutation. |
| Cycles keep every request a real success | Accept the error path; re-seed per request | User choice: measures the mutation, not the refusal, without seed churn. |
| Rank by `rest(sum)` of cgroup delta | mean, max | User choice: stepwise growth is a leak that repeats; cgroup is what Render kills on. |
| CSV via `--out` | JSON, none | User choice: Excel-friendly, Phase 3 can diff. |
| Continue on failure, exit 1 at end | Abort first | User choice: one run yields the whole picture. |
| Uncatalogued route fails the run | Informational | User choice: coverage cannot decay silently. |
| Seed rows from `_seed.build` | Create through the API in-sweep | User choice: order-independent, one teardown. |
| Outbound integrations excluded, status GETs kept | All in / all out | User choice. |
| Unexpected non-2xx fails the route | Only 5xx | A stale body returns 422 and would otherwise measure validation. |
| `--only` filter | None | Iterating on the catalogue without 2,500 requests. |
| `app.routes` order | Shuffle, GETs first | Per-request deltas make order immaterial. |
| One `docker logs` read per run | Per route | Fewer subprocesses; correlation is by id anyway. |
