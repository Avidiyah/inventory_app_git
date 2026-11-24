# Inventory App Current State

Last reviewed: 2026-11-23 · Soft word budget: 16,500 (CLAUDE.md → Documentation
conventions)

Contracts and invariants — **the authority**. Code owns the endpoint trace,
request/response contracts, and error catalog (`routers/`, `schemas/`,
`domain/errors.py`; trace with codebase-memory-mcp); `docs/open-work.md` is the
only backlog.

For implementation work: read `Fast Orientation`, `Architecture Rules`, and
`Hard Invariants`; run the focused tests in `Test Map`; update this file when
shipped behavior, schema, deployment, or known gaps change. If this file
conflicts with code, trust the code and fix this file in the same change.

## Fast Orientation

A self-hosted inventory and work-order staging system for physical materials
tracked by barcode.

- FastAPI API and static no-build SPA (`backend/static`) in one process;
  PostgreSQL via SQLAlchemy and Alembic.
- Upload decoding through backend `pyzbar`; live camera scanning through
  vendored `@zxing/browser`.
- One same-origin `/ws` WebSocket per browser for cache invalidation only; REST
  is the source of truth.
- Read-only NetFacilities work-order enrichment through each user's own Steel
  cloud browser session; Admin-gated, disabled by default.
- Render: one Docker web service on a managed Postgres.

Core workflows: find/create/edit items by barcode; stock, dispense, correct,
void and bill transaction rows; scan items into work-order batches;
import/assign/log standalone work orders (identity = number) with dispensed or
retroactive materials; plan/load/return truck staging by community, building
and unit; history review/copy; role-scoped user management; tool custody from a
user-first profile card (TechFM OA+ search users and check tools out; every
role checks in its UI-selected user's holdings; bulk tools split across
holders).

## Architecture Rules

Backend layering:

```text
routers -> schemas/services -> domain/models -> database
```

- Routers stay thin: parse schemas, enforce auth, call services, translate
  `DomainError` through `routers/_errors.py`.
- Services own database queries, transactions, row locks, and commits.
- Domain modules are pure rules with no FastAPI/SQLAlchemy imports.
- Models mirror physical schema; every schema change needs a model change and
  an Alembic migration.
- Pydantic schemas define request/response contracts, not permissions.
- Backend gates are authoritative. Frontend role visibility is UX only.
- Frontend is plain ES modules. No bundler, type checker, generated clients, or
  build-time route validation. HTML ids/classes are runtime contracts with JS.
- Static shell HTML is assembled in `backend/app/main.py` from `shell-head.html`,
  `static/pages/*.html`, and `shell-tail.html`.

## Task Routing Map

Find files with codebase-memory-mcp; this table keeps only what the graph
cannot give: non-obvious test commands, manual checks, and area-specific
traps.

| Task area | Check / trap |
| --- | --- |
| Auth, login throttle, rate limit, list cap | Behavior under Hard Invariants → Security; proxy headers live in `backend/entrypoint.sh` |
| Roles/permissions | `test_route_role_gates.py`, `test_role_mirror_parity.py`; `static/roles.js` mirrors `domain/roles.py` |
| Items, barcodes, notes | `test_item_barcodes.py`, `test_item_price_gating.py`; search normalization is pinned by `test_search_parity.py` |
| Low stock, User Requests | Events come only from after-commit listeners (`item_events.py`, `request_events.py`); `test_stock_events_flush.py` |
| Billing/receipt | Receipt exists twice (`domain/receipt.py`, `static/adminReviewReceipt.js`); `test_receipt.py` pins them together |
| Live camera scan | Tuning is field-tested (memory: scan tuning); real optics need a manual device check; `/scan-test` is the harness |
| Work Orders UI | `tests/frontend/views/workOrders/`, `backend/tests/e2e/test_work_orders.py` |
| User Hub Report | **Admin-only**; completed closed rows are a **frozen record**, `New Work Orders` is selected live by `created_at`, blocked by community, always last in Excel; contract `HubReportResponse`; manual Excel check |
| Attendance / Timesheets / Leaderboards | Role floors in Hard Invariants → Attendance and Roles And Access; `GET /hub/performance` is admin only |
| SMR27 audit | Specs `docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md` … `2026-11-06-smr-paper-stage-design.md`; tables in `models_smr.py` |
| NetFacilities | `test_netfacilities_*.py`; behavior under API Surface |
| Real-time | `test_realtime_*.py`, `test_logging.py`, all-JavaScript syntax check, manual browser check |
| Mass staging UI | `massStageActionCoverage.test.js` names all thirteen `data-action` branches; manual UI check |
| Deployment/runtime | `git diff --check`; run tests if runtime deps change |
| Navigation/layout | `backend/tests/e2e/test_smoke.py` (every page renders, clean console) plus a manual browser check |
| Schema/migration | Targeted DB-backed tests, then full pytest |

Work-order module rule: the nine other views import `workOrders.js` (the
barrel) and only that; inside the group a sibling imports `workOrderList.js`
directly, because importing the barrel from within the group makes a cycle.
Dependency order, leaf first: `workOrderGlyphs` → `workOrderPresenters` →
`workOrderSignature` / `workOrderReferenceData` / `workOrderFilters`
(→ `workOrderFilterChips`) → `workOrderStatusActions` → `workOrderCardHtml` →
`workOrderRouting` → `workOrderList` → `workOrderActions` /
`workOrderIntegrations` → barrel. `workOrderRouting` takes its list
dependencies by injection (`installWorkOrderRouting`), keeping the one real
mutual recursion (list → card page → list) out of the import graph. A
work-order module may pass the 500-line cap; past 1,000 it must move function
bodies into helper modules.

## Runtime And Stack

Pinned versions live in `backend/requirements.txt` (Python 3.12 in Docker;
Pillow 13.0.0). Live decode uses vendored `@zxing/browser` UMD 0.2.0; the
NetFacilities integration needs Playwright and Beautiful Soup at runtime
(installed Chrome for local interactive sign-in, bundled Chromium for isolated
hosted document reads).

## Deployment

- Docker image `python:3.12-slim` + Debian `libzbar0`; Playwright, bundled
  Chromium, and Beautiful Soup ship in the image. Entrypoint: `alembic upgrade
  head`, then Uvicorn on `${PORT:-8124}`.
- Render blueprint `render.yaml`: service `inventory-app`, production database
  `inventory-db-copy` via `fromDatabase` internal connection string.
  **`render.yaml` declares no `databases:` block** — the DB plan
  (`basic-256mb`, 1 GB storage) and 3-day point-in-time recovery exist only in
  the Render dashboard; nothing in the repo can detect them changing. The
  dashboard is also the authority for the production hostname
  (`https://inventory-app-gb1c.onrender.com` when last recorded).
- Deploys are manual: `autoDeploy: false` and CI has no deploy job. Click
  Manual Deploy in the Render dashboard on a commit that is green in CI.
- The 1 GB ceiling is structurally distant: **no binary data is persisted
  anywhere** — decode stores nothing, imports discard the file, there is no
  attachment feature. Growth is rows only (`transactions` grows forever;
  `sessions` and `login_attempts` are swept). Revisit if files are ever stored.
- `healthCheckPath: /healthz` runs a real database query, so a deploy that
  cannot reach Postgres fails instead of going green. `/db-test` (TechFM OA+)
  verifies database identity; `/healthz` proves only reachability.
- Required env: `DATABASE_URL`. Production sets `COOKIE_SECURE=true`,
  `SQL_ECHO=false`, `LOG_LEVEL=INFO`.
- **`VAPID_PRIVATE_KEY` enables Web Push** — set in Render's Environment page
  (`sync: false`; deliberately not in the committed Dockerfile). Absent, push
  disables itself and `/push/config` / `/push/test` return 503. Rotating it
  invalidates every existing subscription.
- **`COOKIE_SECURE` controls three things** — the cookie `Secure` flag, HSTS,
  and whether FastAPI's docs endpoints exist; one flag so a deployment cannot
  be half production. When true, `/docs`, `/redoc`, `/openapi.json` are
  **un-mounted** (404); `app.openapi()` still returns the schema and
  re-enabling takes a code change. Where mounted they render blank anyway
  (CSP; N8 in `docs/open-work.md`).
- Static assets are served `Cache-Control: no-cache`; the app sends
  `Permissions-Policy: camera=(self)` and `X-Request-ID: <12 hex>`. Windows
  local pyzbar may need the Visual C++ 2013 runtime (`msvcr120.dll`).

Local Docker reproduction — **the test environment for memory and load work**;
measurements run inside the container, never on the host, so every reading
carries the cgroup figure Render enforces:

```
docker build -t inventory-app backend
docker run -d --name inventory-local --memory=2g -p 8124:8124 --env-file <copy> inventory-app
```

- `--memory=2g` is the live service ceiling; the container reaches host
  Postgres 8801 via `host.docker.internal`. `<copy>` is a copy of `.env` with
  the `DATABASE_URL` host rewritten; recreate it when `.env` changes, never
  edit `.env` itself. Secrets stay out of the image.
- Idle baseline is per container lifetime (`cg_mb` 178 right after start, 131
  after an hour idle): compare runs within one lifetime, or restart first.
  Render polls `/healthz`, so every `event=request` line is a free sampler:
  `docker logs inventory-local | grep event=request`.
- `scripts/memprobe.py` (probe, sweep, soak, jumps; run from `backend/`, under
  Git Bash set `MSYS_NO_PATHCONV=1`) drives the container; phases and status
  are owned by `docs/open-work.md`. `tests/test_memprobe.py` fails when a new
  route is neither catalogued nor excluded in `scripts/memprobe_routes.py`.

## Logging (`app/logging_config.py`)

- **Format is logfmt** — `ts= level= req= [user_id=] event= <fields>` on
  stdout. The record's message is the event name, so `grep event=<name>` is a
  complete query and `grep req=<id>` returns one whole request.
- Every request gets a 12-hex id minted by the outermost middleware and echoed
  as `X-Request-ID`; the incoming header is never trusted.
- One `event=request` line per request: method, path, status, ms, `rss_mb`,
  `cg_mb` (container cgroup total, the figure Render enforces) and
  `cg_delta_mb` / `rss_delta_mb`. The same route repeating with a positive
  delta is a leak; a one-off is allocator high-water retention. Uvicorn's own
  access log stays on as the fallback.
- **`user_id` is bound once**, in `auth_deps.get_current_user`.
- **Never logged**: passwords, session tokens raw or hashed, the `Cookie`
  header, request bodies, query strings (path only), and the database URL.
- **A failed login logs the username only if the account exists**, otherwise
  `user=unknown` (`services.auth.username_exists`): logging the submitted
  string verbatim would put a mistyped password in the logs permanently.
- Verbosity is `LOG_LEVEL`; an unrecognised value falls back to INFO.

## Real-time invalidation

- The wire envelope is exactly `type`, `id`, `req` — no row data, no actor. The
  vocabulary, audiences and pinned emitter sets live in `domain/realtime.py`,
  asserted by `test_realtime_emit.py`. Audience is a noise rule, not a
  security boundary; scoping happens on the client's REST refetch. Emission is
  non-blocking and best-effort, after the mutating service returns.
- **Targeted emit**: `services/realtime.emit(envelope, user_ids=…)` reaches only
  those users' sockets; `message.changed` (id = conversation id) is the only
  targeted event, sent to a chat's members by `routers/_message_events.py`.
  `messagesStore.js` is the one subscriber with no `activePage` gate.
- The browser connects after auth and disconnects on logout or any global 401;
  the connection is **generation-guarded** so an old socket's callbacks cannot
  reconnect over a cleared session. Retries use equal-jitter exponential
  backoff (0.5–1 s doubling to 15–30 s); a successful **recovery** (never the
  first connect) notifies each handler once, since events may have been missed.
- `static/realtime.js` has no DOM/view dependency; only explicitly subscribed
  views refresh, and only while their page is active. No client→server
  messages.
- Live repaints never steal focus or clobber typed input (`morph.js`, skip
  rules in `patchBodyLive` / `patchHub`); fetches coalesce to one in flight
  plus one rerun, and a response overtaken by a newer request or the user's own
  repaint is dropped. A filtered Work Orders list is a snapshot refined by live
  badges: a row that no longer matches keeps its badge until the next full load.
- Admin Review unpriced rule: a blank or $0.00 price is unpriced (`is_priced` /
  `isUnpriced`, the rule that opens a missing-price request). Such cards paint
  red, withhold the receipt box, disable Close, and open an item picker that
  jumps to User Requests → Missing price.

## Upload size caps

`app/routers/_uploads.py::read_capped` guards every upload route:
`POST /barcodes/decode` **10 MB**; `POST /work-orders/import` and the four SMR
import routes in `routers/work_orders_smr.py` **25 MB** (six call sites). A new
upload route must call it. Over the cap is 413 naming the limit. Caps are
constants, not env vars — an upload limit is a contract. The cap bounds what is
held in memory, not what is transmitted (Starlette has already spooled the
body). The role gate resolves before the body is read, so an unauthorised
oversized upload is 403. Refusals log `event=upload.rejected_too_large`.

## Hard Invariants

Work Orders save conflicts (W3):

- The flush listener in `app/field_stamps.py` is the only writer of
  `work_order_field_stamps` and of `updated_by_id` on material lines and labor
  entries; the actor is `session.info["actor_id"]`, set by `get_current_user`.
  Never stamp from a route.
- `user_request.changed` is emitted only by the after-commit listener in
  `app/request_events.py`, and `item.low_stock.changed` only by
  `app/item_events.py` (one envelope per changed row per commit). Never emit
  either from a route.
- Edit details, material quantity and billing, and labor hours send expected
  values (`workOrderConflict.js`, from `data-original-*` /
  `data-expected-minutes` / `data-billable-quantity`, which a live patch leaves
  alone); Edit details sends only dirty fields.

Attendance:

- One open punch per person, enforced by `uq_attendance_punches_open_user`
  (partial index) — not by a service check.
- An open punch ends at the Central midnight after its start
  (`domain.attendance.capped_end`): every read computes it, and
  `services.attendance.sweep_open_punches` writes it (`end_source=
  auto_clock_out`, `needs_review=true`, no audit row). It never stops a
  work-order clock (the 12-hour cap owns that). No self-close.
- Clocked ≠ tracked ≠ billed. Clocked comes from `attendance_punches` and is
  never rounded to 30 minutes.
- Lunch is flat: `LUNCH_MINUTES` (30) comes off any day whose gross clocked
  minutes reach `LUNCH_MIN_DAY_MINUTES` (360) unless waived; no time-of-day
  logic. `paid_minutes = clocked - lunch` is what the day cards, day page,
  profile and CSV print; delta, the boards and the Home tab stay gross. The
  waiver is `lunch_waived` on the day's first non-carried punch (audited) and
  never clears `needs_review`.
- Shop hours: `attendance_punches.shop`. Home's switch (`POST
  /attendance/switch`) closes the open punch and opens the other kind at the
  same instant. Clocking into the shop stops a running job clock; starting a
  job clock from the shop switches to work-order time. Shop is paid and on the
  timesheet, not "Off job", and left out of the performance score.
- A day with `pending_review` (`domain.attendance.day_pending_review`: a
  `needs_review` punch, midnight closes included, or an auto-closed/over-cap
  session with no `reviewed_at`) is left out of every hours total (compare
  payload, CSV "Pending review" row, profile) and shown greyed with "⚠".
  Admin "Mark all reviewed" accepts the week's estimates, sweeping open
  punches first.
- Self-edit: a worker adds, edits and deletes their own punches and keys/revises
  their own hand-entered labor (on the crew; never a session row) only while
  the week is open (`labor_day.week_is_open`, Central); else 403 "You can only
  change your own time in the current week." Never `needs_review` alone or
  lunch. Edits are marked Self/Admin on the profile timeline and Labor card.
- No punch may cross Central midnight (400). A legacy cross-midnight row
  belongs to its start day, shows `carried` on the next, and is editable only
  on its start day.
- Leaderboards (Admin+, `GET /hub/performance`, scored in
  `domain/performance.py`): one score per person, components Billed $ 40%
  (each completed order's `labor_charge` split by labor minutes, Skilled lines
  ignored), Efficiency 25% (sessions + hand-keyed ÷ clocked), Accuracy 20%
  (sessions ÷ clocked), Clean days 15%; each scaled to the best eligible
  person = 100. Under 16 h clocked (week) / 60 h (month) a person is unranked,
  below a divider. Trust rule: a day with an `auto_clock_out`/`self_reported`
  punch (or flagged / cross-midnight), an auto-closed or over-cap job clock,
  > 5 min charged off shift, or more charged than clocked is left out whole
  and named on the row; an order with a flawed job clock earns nothing for
  anyone. **Review never re-admits a day** — only keying the real time does
  (delete the flawed labor entry and re-key).

Inventory/transactions:

- Quantities and prices use `Decimal`/`Numeric`, never floats in backend logic.
- Stock/dispense/correction/void operations lock the item row before changing
  quantity.
- Scan / Stock and the Work Orders Add Item action record a dispense even when
  it exceeds the recorded count. Quantity may go negative so a later removal is
  the exact inverse, and the same commit creates one open `inventory_recount`
  User Request linked to the transaction. Work Order quantity edits, Mass
  Stage, tools, corrections, and reversal guards still reject an operation that
  would cross below zero.
- Transactions are append-only. Corrections are new `adjust` rows with a
  required reason.
- Voiding is a soft delete (`voided_at`/`voided_by_id`): hide from history,
  reverse the stock effect, resolve any linked recount request. It is rejected
  if reversal would make stock negative.
- Item archive is soft delete (`archived_at`). User archive is soft delete
  (`users.archived_at`): archived users cannot log in, sessions are revoked,
  the row is retained for history. Archive is refused with 409 while the user
  holds tools; retrying with `force_return_tools=true` checks every held tool
  in (ordinary `return` rows attributed to the archiving admin) then archives,
  in one transaction (the Users page offers it as a second confirm). Hard
  delete is blocked if transactions reference the user.
- Stock/dispense snapshot `Item.price` into `transactions.unit_price`; History
  reports the frozen snapshot, so editing a price does NOT rewrite past line
  values. Exception: a row snapshotted at 0 (free dispense) or NULL
  (legacy/adjust) tracks the live `Item.price`.
- Mass-stage unused returns add stock without transaction rows — the one
  deliberate silent stock change.
- `transactions.affects_stock` is TRUE for every ordinary stock/dispense/adjust
  and FALSE only for a *retroactive* work-order entry: it shows in History like
  a dispense but did NOT move on-hand, so its creation and its void skip the
  stock change (`void_transaction` branches on the flag).

Security/access:

- Backend role gates are the source of truth; frontend hiding is convenience.
- **Every static role gate is declarative** — `Depends(require_min_role(...))`
  on the route, never a rank check in a handler body. `auth_deps.py` is the one
  place a role 403 is raised. The one deliberate exception is
  `routers/transactions.py`, which gates on `can_transact(role,
  payload.transaction_type)` and needs the parsed body. Gated routes in
  `routers/work_orders.py` also declare `responses={403: ...}` (FastAPI does
  not infer it). Per-row *visibility* and the per-field edit matrix live in the
  services, which need the loaded row. The line-billing route answers 403
  before 422 (its gate is a dependency).
- Sessions are server-side rows carried by an HttpOnly `session` cookie. The
  row's primary key is the **SHA-256 hash** of the token
  (`services.auth._hash_token`); the raw token is returned once and never
  persisted, so reading `sessions` yields nothing replayable. SHA-256 not scrypt
  on purpose: the token is 256 CSPRNG bits and the hash runs on every request.
- Every session has a hard absolute `expires_at` (NOT NULL, 12 h;
  `SESSION_LIFETIME` / `REMEMBER_LIFETIME`, currently equal). "Remember this
  device" only makes the *cookie* persistent. There is no idle timeout and no
  per-request write. An expired row is deleted on the read that presents it;
  `sweep_expired_sessions` runs on every login, so no scheduler exists.
- Sessions are revoked (`services.auth.revoke_user_sessions`) on user archive,
  role change, **and password reset**; `user_id` cascades on user delete.
- Passwords are case-sensitive, not stripped, minimum 4 characters. The floor
  is below NIST 800-63B rev 4 (8) and a known, deliberately deferred gap —
  raising it invalidates existing passwords. Hash format
  `scrypt$n$r$p$salt_hex$hash_hex`.
- `POST /auth/login` is throttled by exponential backoff keyed on (submitted
  username, client IP): 5 free attempts, then 5 s doubling to a 15 min ceiling,
  returned as **429 + `Retry-After`**, never by sleeping (a sleeping handler
  holds a threadpool slot). Backoff keyed on the IP too, not account lockout, so
  nobody can lock a crew member out by hammering a username. A locked caller is
  refused even with the correct password. A wider per-IP layer ships disabled
  (`LOGIN_THROTTLE_PER_IP`): enable it only after confirming distinct client IPs
  reach the app, or the whole crew throttles as one client. `entrypoint.sh`
  passes `--proxy-headers --forwarded-allow-ips='*'` so `request.client` is the
  real caller; safe only because the container is reachable only through
  Render's proxy.
- **Every non-exempt path is capped at 60 requests/second per caller** by the
  `rate_limit` middleware (`main.py`): **429 + `Retry-After: 1`**. Exempt and
  uncounted: `/`, `/static/*`, `/healthz` (page loads cannot consume the
  budget; a busy caller cannot fail a deploy). Callers are keyed by session
  (SHA-256 of the cookie, truncated), falling back to client IP when
  unauthenticated (it runs before dependencies resolve). Counters are in
  memory — the window is one second. Refused requests are not counted, so the
  cap cannot become a lockout. A ceiling on malfunction, not a quota.
- **Every list endpoint returns at most 5,000 rows** (`MAX_LIST_ROWS`,
  `domain/list_limits.py`, applied via `services/_list_cap.py`): a safety
  ceiling, not pagination — no `limit`/`offset`, no page contract. When it
  bites the list is truncated silently and `event=list.truncated list=<name>
  cap=5000` is logged; that line is the trigger for real pagination. Capped:
  `/items/`, `/tools/`, `/users/`, `/mass-stages/`, `/user-requests/`,
  `/work-orders/`. The SQL paths fetch `MAX_LIST_ROWS + 1` to detect
  truncation without `COUNT(*)`. `GET /work-orders/` orders in Python
  (`schedule_date` is raw text), so its cap bounds the response, not the query;
  its `limit` param is bounded by `MAX_LIST_ROWS`. **The work-order CSV export is
  deliberately uncapped**: a CSV that silently omits rows while looking
  complete is a records problem.
- User management requires strict subordinate authority (actor rank > target).
  Owner is bootstrap-only; API users cannot manage an owner.
- Cost fields (`price`, `product_link`, labor rate/total) are redacted
  server-side below TechFM OA.

Work orders:

- A work order is a standalone entity; **identity is its `number`**, unique
  case-insensitively + trimmed (`uq_work_orders_number_ci`).
- **Work orders are import-only.** `services.work_orders.get_or_create_work_order`
  (CSV import) is the only creator; there is no create endpoint or form. Every
  other surface calls `resolve_work_order`, which attaches to an existing number
  and 404s otherwise. References fill blank attributes but never overwrite
  non-blank ones; explicit edits overwrite. Existing rows are locked before an
  import merge: incoming Team Lead routing applies only while the locked row is
  still unassigned, so a manual reroute survives later and concurrent re-imports.
- **List cards preview; the card page edits.** A tap opens a read-only preview;
  "Open work order" navigates to `/workorder_card/<number>` (the SPA shell
  served by `main.py`, so refresh/bookmark/pasted links resolve). Deep links
  resolve number→id through the server-scoped list search
  (`apiListWorkOrders({ q })`), **not** `/work-orders/lookup` (Team Lead+, would
  403 a Technician); an archived and an unknown number are indistinguishable
  ("not available"). The card must remain a `details.wo-card` inside
  `#work-orders-list` — moving it silently breaks the delegated action layer
  (~20 click branches) and the realtime card lookup, with no error. The card
  page is tabbed (Details · Notes · Materials · Labor · Invoice); an open
  section marks the card **held** (`heldWorkOrderCards`, re-login resume only).
- **Back returns to the list at its offset.** `history.scrollRestoration` is
  `manual`: the browser restores at `popstate`, before the list refetches, and
  clamps to 0. `openWorkOrderPage` stamps `woListScrollY` on the list's history
  entry via `replaceState`, and `popstate` arms a one-shot the completed render
  consumes (reading at the render site would make nav, filters and live
  refreshes jump the page). A card opened from an SMR tile or a profile carries
  an origin (`profileOrigin.js`) whose Back returns there; a nav click clears it.
- List filters are server-side and AND together before the caller's visibility
  scope: My Work Orders (`mine`, **on by default for every role**), status,
  exact normalized service type, routed Team Lead, derived community, exact
  scheduled date, and one search box (`text_q`: number OR location OR task,
  never notes). `q` / `location_q` / `task_q` remain for SMR and deep links.
  Community membership checks both `community` and raw CSV `location` for
  Scholars, Centennial, Commons (`commons`/`cimarron`/`cimmarron`), or Young
  Hall; a multi-location row may match several; Academics is the fallback.
- `schedule_date` stays raw imported text; a leading `M/D/YYYY` (two-digit
  years, optional time) or ISO date is parsed for sorting. Valid dates sort
  newest first; blank/malformed sort last.
- `GET /work-orders/export?scope=` writes one scoped CSV row per work order.
  `variant=full` exports the whole current filtered result (never the recent-10
  display cap), leads with the seven import headers so it re-imports through
  fill-blanks, and is named by UTC date/time plus filters (`_all.csv` when
  unfiltered). `variant=client` is the billing sheet (`WORK ORDER`, `MATERIAL
  TOTAL`, `LABOR TOTAL`, `RECEIPT`), controlled only by the scope dropdown; both
  totals are billed figures (materials +15%, labor = labor charge) so they sum
  to the receipt Total.
- The receipt has two implementations (`static/adminReviewReceipt.js` and
  `app/domain/receipt.py`) that must stay identical — mark-up, 41-character
  width, name truncation, `NO PRICE` / `Total (incomplete)`, money/quantity
  formatting — pinned by `tests/test_receipt.py`.
- Live status is `created` → `assigned` → `in_progress` → `ready_to_complete` →
  `completed` → `review`, with `on_hold` as the pause state (a plain `Text`
  column, no CHECK). **On-Hold means exactly one thing: nobody is on the
  clock.** Imports start Created; assigning technicians advances a pre-work row
  to Assigned and clearing them returns it to Created; later states never
  rewind automatically. The first committed material activity advances
  Created/Assigned to In-Progress; hand-keyed labor changes no status (it is
  the correction route), and material activity does not resume On-Hold.
  `completed_at` is kept through Review and cleared by rollback/reopen. Closed
  is not a stored status: it is `archived_at`.
- The walkthrough is built on **tracked time**. `POST
  /work-orders/{id}/tracking/start` opens a labor session for the caller and
  advances a pre-work row to In-Progress or resumes an On-Hold one;
  `tracking/stop` closes the caller's own session, and closing the **last**
  running session on an In-Progress row moves it to On-Hold. Both idempotent.
  **Begin Charging is self-assignment:** `start` is open to every role except
  the Owner (403, before the punch opens) on any visible work order and, past
  the status guard, adds the caller to the crew (`assigned_by_id` = caller,
  nobody removed, no notification). A start the status guard refuses assigns
  nobody. **Prior-work gate:** when another user has a session, labor entry or
  material line on the row, the caller has none, and the row has notes, `start`
  returns 409 until the body sends `notes_acknowledged: true`.
- `POST /work-orders/{id}/complete` ("Notify Team Lead") finishes the job and
  stops every clock. **Where it lands is the caller's role**
  (`domain.work_orders.completion_target_status`): Team Lead+ reaches
  Completed; a Technician's finish goes to **Ready to Complete** with the
  server note `marked work ready to complete`, from which Team Lead+ Approve
  (`PATCH completed`) or Send Back (`PATCH in_progress`, raises
  `work_order.sent_back`). Completed is the billing state the Admin queue reads,
  so it stays a supervisory decision. Idempotency compares against the caller's
  own target. `POST /work-orders/{id}/start` survives for the Scan / Stock
  confirmation (a Technician must already be on the crew).
- `POST .../hold` (assigned worker, In-Progress only) places the row On-Hold and
  stops **every** clock. `POST .../resume` returns it to In-Progress and
  deliberately **starts no clock**: stopping can only under-bill, starting
  bills somebody who may not be on site. A PATCH into `on_hold`,
  `ready_to_complete` or `completed` also stops every session.
- Review is stricter: the row must be Completed and the caller an Admin+ or its
  routed Team Lead who is not an assigned worker (two-person handoff).
- Closing (archive) requires TechFM OA+ from every live status. The row and
  lines remain, the number stays reserved, and only `restore_work_order`
  returns it to live views. CSV import counts and ignores it; transactions keep
  their own `work_order_number`.
- Logging a material writes a `dispense` transaction carrying `work_order_id` +
  number. `entry_mode` decides `affects_stock` (`dispense` moves stock,
  `retroactive` is stock-neutral); mode is snapshotted per line.
- An SMR order never moves stock (`domain.work_orders.stock_locked`): adds and
  Scan / Stock dispenses log `retroactive`; edits and removals leave on-hand
  alone. Mass Stage loads still move stock (a truck load is physical).
- A `work_order_items` line is the **aggregate** of its dispenses for one item:
  `services.work_orders.attach_dispense_line` is the single home every
  stock-out funnels through (Work Orders button, Scan/Stock, scan-and-go via
  `apply_transaction`, Mass Stage `load_item`). Re-logging ADDS to the line
  (each scan is its own ledger row); membership is `(work_order_id, item_id)`.
  A stock-in never creates a line.
- `line.quantity` is the authoritative stored total. Editing it corrects stock
  by the delta with one reconciling `adjust` transaction (original rows stay
  intact). Deleting a line returns its net units and voids every transaction it
  aggregated. Voiding a work-order dispense from History, or a Mass Stage
  return (`reduce_dispense_line`), walks the line back (dropped at zero).
  `get_work_order` lazily self-heals an orphaned linked dispense into a line.
- The line is the **billing unit**: charge = `effective_billable * current
  Item.price` (TechFM OA+ only; `effective_billable` = `billable_quantity` when
  set else `quantity`), summed into `materials_total`. Work-order-linked
  transaction rows are a pure inventory record — History suppresses their
  per-row charge — so a line edit never double-bills and its signed `adjust` is
  never billed as a negative. Ad-hoc transactions keep the per-row charge.
- `work_order_items.billable_quantity` (TechFM OA+, `PATCH .../items/{id}/billing`):
  NULL bills full `quantity`, `0` records but does not charge, a value <=
  quantity bills a partial count. Never moves stock; lowering `quantity` below
  an override clears it. Fee, tax and discount layers are deferred.
- **Every recognised role sees every live work order**
  (`domain.work_orders.can_view_work_order`, `_scoped_to_user`); an
  unrecognised role fails closed to its assignments; archived/unknown are 404.
  **Seeing is not acting:** a Technician not on the crew is read-only (403
  "Begin Charging on this work order first",
  `services.work_orders.require_crew_for_technician`; Team Lead+ never locked).
  The write matrix is under Roles And Access.

Mass staging:

- Stage status moves only `planning -> loading -> completed`; slots/items are
  editable only in `planning`, loading/returning only in `loading`.
- One active non-completed stage per `(community, building_name)`
  (`building_name` holds the building *number*; column name kept).
- A stage references work orders through `mass_stage_work_orders` slots; adding
  one enforces community/building match.
- Loading writes real per-slot `dispense` transactions carrying the slot's work
  order; returns reverse-fill across slots, write no ledger row, and walk the
  work order's line back so it reflects net consumption.

Barcode:

- A primary item barcode and every additional barcode must be globally unique
  across `items.barcode` and `item_barcodes.code`; lookup resolves either to one
  live item; archived items are hidden from lookup.

Frontend:

- Live camera must stop on page leave/tab hide to release track/torch.

## Roles And Access

```text
owner > admin > techfm_oa > supervisor > technician
```

**Naming:** the stored role value, API fields (`supervisor_id`…), CSS classes
and code keep `supervisor`; every label a person reads says **Team Lead**
(`roles.ROLE_LABELS`, mirrored in `static/roles.js`). Ranks: technician 0,
supervisor 1, techfm_oa 2, admin 3, owner 4. "Team Lead+" = rank >= 1.

| Capability | Rule |
| --- | --- |
| Login/logout/me | login public; logout/me require session |
| Dispense | any authenticated role |
| Stock; History; list users; mass-stage page/API; edit item notes | Team Lead+ |
| Void transaction | Team Lead+ for any actionable row; a Technician only their own work-order dispense |
| Create/edit/archive item; correct count; view price/product link; set billing override | techfm_oa+ (price/link redacted server-side below techfm_oa) |
| Create/reset/archive/restore/delete user | actor must outrank target |
| Edit user name + username | self, or actor outranks target |
| Change a user's role | techfm_oa+ AND actor outranks both the current and the new role (a TechFM OA never touches an Admin/Owner nor hands those roles out) |
| Tutorial progress: own rows read/write | any authenticated role (writes always target the caller) |
| `GET /tutorials/progress/users` (completed keys per active user) | Team Lead+ |
| Work Orders list/get/items | any authenticated user; `mine` / `assigned_to_id` narrow it |
| Notes, add/remove material, Material/Catalogue request, witness sign-off, Scan / Stock dispense against a work order | Team Lead+ on any; a **Technician only on a work order they are on the crew of** |
| Begin / Stop Charging | every role **except the Owner** (403), on any visible work order; start adds the caller to the crew |
| Be assigned to a work order | Technician, Team Lead, TechFM OA, Admin — not the Owner |
| Routing (team lead), crew, status, entry mode, logged-material quantity | Team Lead+ (routing target must be an active Admin, TechFM OA or Team Lead; the editor sends its original `supervisor_id` and a stale pick is a named 409) |
| Hand-enter/edit/remove labor | Team Lead+ for anyone's (`services.work_orders._require_labor_editor`; credited worker must be on the crew or be the recorder); a worker only their own, in the open week |
| Finish assigned work into Completed | Team Lead+ on the crew (a Technician's finish lands Ready to Complete) |
| Approve / Send Back from Ready to Complete | Team Lead+ |
| Send Completed to Review | **admin+** only, never an assigned worker; the one capability an Admin holds that a TechFM OA lacks |
| Edit imported metadata; import/export CSV; close/archive; line billing override | techfm_oa+ (scoped, server-side) |
| Preview/re-archive all live legacy work orders | owner only (gate and service check) |
| Admin Review page / receipt; Low Stock; User Requests; Mark material request stocked | techfm_oa+ |
| File a material request | any authenticated user who can see the work order; catalogue request: any authenticated user |
| Cancel own open material request | the filer |
| Scan-gate cards | any authenticated user (a Technician's gate lists only their assignments) |
| Tools: view list/lookup, return | any authenticated user |
| Tools: create, edit, archive, checkout | techfm_oa+ |
| Timesheets, live roster, `POST /hub/attendance/clock-out/{user_id}`, `GET /hub/people/{user_id}/week` | Team Lead+ |
| Export CSV, Mark all reviewed, lunch waiver, Leaderboards, Hub Report | admin+ |
| Own punches (in/out/switch) | any authenticated user plus the service guard |

TechFM OA nuance: it carries the whole Admin toolkit minus two things, both
falling out of rank: (1) it **cannot send a work order to Review**
(`services.work_orders._require_review_handoff_permission` is an Admin floor;
the card shows the button disabled with the reason; an Admin who Begins
Charging joins the crew and is excluded from reviewing that order too); (2) it
**cannot re-role an Admin/Owner or hand those roles out** (`can_manage` is
false at equal rank and above). Admin-floor *route* gates are an explicit
allowlist in `tests/test_route_role_gates.py`
(`test_no_route_gate_is_left_at_the_admin_floor`), so a `ROLE_ADMIN` written
out of habit fails loudly; adding a genuinely Admin-only route means adding it
there with a reason.

Scoping nuance:

- Tools UI: TechFM OA+ search every active user and act on that user's custody
  card; Team Lead/Technician are pinned to their own card. The return route
  accepts any `assigned_to_id` — the self-scope is a frontend workflow boundary,
  not backend authorization.
- `GET /mass-stages/` is scoped (Team Lead sees own, techfm_oa+ all); stage-by-id
  routes are Team Lead+ gated but not creator-scoped.
- The `/work-orders` write checks live in `services.work_orders` because
  Technicians reach those routes (matrix above).

## Data Model

Primary keys are UUIDs; timestamps are timezone-aware. Columns are code-owned
(`models.py`, `models_smr.py`); only rules a reader cannot infer follow.

### `users`

- `archived_at` NULL = active. An archived user cannot authenticate and leaves
  the default list; the row stays so history resolves names; archiving deletes
  their sessions.
- `username` is the unique login identifier (editable via `PATCH
  /users/{id}/name`, uniqueness surfaced as 400; sessions survive since they key
  on user id). Operational pages render `full_name`; only login, account
  creation and the Users table show a username. New users require both names;
  legacy nameless accounts render `Name unavailable` and cannot auto-route a CSV
  work order until Edit Details sets them.
- `role` is editable by TechFM OA+ via `PATCH /users/{id}/role`, which revokes
  the target's sessions.
- Full names are not unique: two active routing-eligible users (Admin or Team
  Lead) with the same normalized name are intentionally ambiguous in CSV routing.
- `authenticate` rejects archived users indistinguishably from bad credentials.

### `sessions`, `login_attempts`

Rules are under Hard Invariants → Security. `login_attempts` is a transient
throttle counter, **not an audit trail**: `UNIQUE(scope, key)`, deleted on
successful login, swept after `ATTEMPT_TTL` (24 h), so it cannot answer "who
tried last week". `scope="user_ip"` (always on) keys on `"<casefolded
username>|<ip>"`; `scope="ip"` is active only with `LOGIN_THROTTLE_PER_IP`.
The key uses the **submitted** username, never a resolved id — keying on an id
would leak account existence through which attempts get throttled. The backoff
curve is pure, in `domain/login_throttle.py`.

### `push_subscriptions`

- **`endpoint` is the primary key.** A subscription belongs to a browser
  profile, not an account; keying on it makes a re-subscribe *reassign* the row,
  which stops a shared crew phone from notifying the previous user.
- `user_id` cascades on user delete and is indexed (fan-out selects by
  recipient). `p256dh` / `auth` are per-device payload-encryption secrets: never
  logged, never returned by any route.
- No expiry or sweep: a row dies only on a 404/410 from the push service
  (`domain/push.py::classify_push_response`) or logout of that device. Archived
  users are filtered at query time, so un-archiving restores their devices.

### `tutorial_progress`

- Primary key `(user_id, script_key)`; keys only (the scripts live in the
  frontend), `^[a-z0-9][a-z0-9.-]{0,79}$`, at most 500 rows per user.
- `seen_at` / `completed_at` are first-write-wins and never cleared; replaying
  a finished script writes nothing. `user_id` cascades on delete; archiving a
  user keeps the rows.

### `items`, `item_barcodes`

- `barcode` is the canonical code; `item_barcodes` holds additional package
  codes (unique within the table; cross-table uniqueness is a service check).
  Rows cascade only on a true hard delete.
- `notes` is JSONB, string keys, scalar values; saves replace the whole object.
- `archived_at` hides the item from lists/lookups but keeps joins for history.
- `low_stock_threshold` is a whole number >= 1 (CHECK), default 6; at or below
  it the item is "low" (Low Stock page; a write crossing it pushes to TechFM
  OA+, `domain/low_stock.py`). Not redacted.
- `PATCH /items/{id}` is a partial update keyed on `model_fields_set`; explicit
  `null` clears `price` / `product_link`; `barcode` / `name` / `location` reject
  null or blank.

### `transactions`

- `transaction_type`: `stock`, `dispense`, `adjust`. Stock/dispense quantity is
  positive; adjust is a signed delta and requires `reason`.
- `work_order_id` links the work order; `work_order_number` is the denormalized
  snapshot History filters on, so transactions stay searchable by number after
  archive.
- `unit_price` snapshots `Item.price` (NULL for adjust/pre-snapshot rows);
  fallback rules under Hard Invariants. For a work-order row (`work_order_id`
  set) History forces `item_price` NULL: it bills via its line.
- `billable_quantity` is the ad-hoc override (NULL = full, `0` = no charge, never
  above the recorded quantity, never on an `adjust`); work-order rows carry the
  override on the line instead.
- `voided_by_id` is a plain UUID, not a second FK. `affects_stock` per Hard
  Invariants.

### `user_requests`

- Types: `inventory_recount`, `missing_item_price`, `catalogue_request` (NULL
  `item_id` until fulfilled), `material_request` (item at `<= 0` on the shelf;
  `item_id` and `work_order_id` required). Statuses `open`/`resolved`;
  `material_request` also uses `stocked`. Vocabulary in
  `domain/material_requests.py`; no CHECK. Requests are resolved/reopened,
  never deleted. `created_by_id`/`resolved_by_id` are `ON DELETE SET NULL`.
- Material request: one live row per (work order, item); a second filing
  overwrites quantity/link/note. A stock write taking on-hand from `<= 0` to
  `> 0` moves every open request for the item to `stocked` in the same
  transaction and pushes `material_request.stocked` to the crew + filer;
  `> 0` to `<= 0` sends `stocked` back to `open` silently. `POST
  /user-requests/{id}/mark-stocked` (TechFM OA+) fires the same transition at
  any on-hand. Adding the material from the stocked line resolves it.
  Stocking against an archived work order resolves with a note and notifies
  nobody. Fulfilling a catalogue request whose item ends `<= 0` auto-files a
  material request on that order (`origin = catalogue_fulfilment`, no push).
- A short Scan / Stock or Add Item dispense creates the recount request
  atomically with the transaction; `details` freezes recorded-before,
  dispensed, shortage and work order number.
- Adding a material priced NULL or `<= 0` to any work order creates one open
  `missing_item_price` request per item (`details.work_order_numbers`
  accumulates). It stays open until a positive price **and** nonblank link both
  exist; `update_item` supplying both auto-resolves it.
- Voiding a source Scan / Stock transaction or removing its Work Order line
  auto-resolves the linked request (`Source transaction removed.`).

### `work_orders`

- Import-only entity; identity and creation rules under Hard Invariants → Work
  orders. `status` is a plain `Text` column. `legacy` marks pre-import rows
  (descriptive attributes NULLed, `number`/`status`/assignment/items kept);
  unlike `archived_at` it does NOT hide the row from lists/search. The
  Owner-only legacy re-archive soft-archives only `legacy=true AND archived_at
  IS NULL` rows, atomically.
- `entry_mode` (`dispense`/`retroactive`) is the default for newly logged
  materials.
- `notes` is an append-only text log: every nonblank Technician+ save is
  serialized under the row lock and appends `MM/DD/YY hh:MM AM/PM Full Name
  note text` in `America/Chicago` server time. Older free-form and `[h:mm
  AM/PM] [MMDDYY] [Full Name]` lines are never rewritten; blank input cannot
  erase history. Begin/Stop Charging and Notify Team Lead append server-authored
  lines through the same formatter.
- `work_order_technicians` is the authoritative plural crew relation (composite
  PK; eligible: Technician, Team Lead, TechFM OA, Admin — not the Owner;
  `roles.WORK_ORDER_ASSIGNEE_ROLES`). It gates what a Technician may write and
  who may hold/resume/finish, not visibility. `assigned_to_id` is a
  compatibility mirror of the first worker (Mass Stage, older clients).
  `roles.WORK_ORDER_TECHNICIAN_ROLES` (Team Lead, Technician) still defines
  floor crew for attendance rosters and Hub time buckets. Two writers: Team
  Lead+ replaces the full set via `PATCH` `assigned_to_ids` (removing someone
  closes their running clock); Begin Charging adds the caller. Removing an
  assignment never removes historical labor.
- `archived_at` is the Closed state; `lookup_work_order` is the one read that
  reports a closed order (so History can offer restore).
- **CSV import** (`POST /work-orders/import`, TechFM OA+) maps columns to
  `location` (raw, deliberately unparsed), `output_to`, `vendor_assignee` (the
  vendor contact, NOT a system user), `service_type`, `schedule_date` (raw),
  `description` (SYMPTOM/TASK). A blank task becomes
  `https://system.netfacilities.com/tools/viewworkorders/<URL-encoded number>`;
  only that exact generated URL is replaceable by a later real task, and every
  other non-blank value stays authoritative under fill-blanks. Notes,
  assignments, lifecycle, materials, labor and billing are untouched. Archived
  matches count as `closed` and are skipped before routing or merge. The header
  row may be first or follow Excel's UTF-8 BOM + `sep=,` hint; the next row must
  hold exactly one `WORK ORDER` header; other columns are optional. Invalid
  UTF-8, an empty file, a wrong delimiter, or an absent/duplicate number header
  is HTTP 400 before any row is written (records are materialized first).
- `supervisor_id` is the Admin/TechFM OA/Team Lead the order is routed to (UI:
  Team Lead). Import sets it by matching the normalized `vendor_assignee` to an
  active routing-eligible user's first + last name
  (`services.work_orders._supervisor_lookup`); missing, unmatched, archived,
  ineligible or ambiguous names import as unassigned. Routing locks the same row
  as import, validates the target, can compare `expected_supervisor_id` (stale →
  409), changes no lifecycle status, and no longer affects visibility; it
  drives `mine`, notifications and the Hub crew board.

### `work_order_items`

- Editable "materials actually used" list, separate from `mass_stage_items`
  (truck planning); `UNIQUE(work_order_id, item_id)`; aggregate and billing
  rules under Hard Invariants. Response `unit_price` is redacted below TechFM OA.
- Any in-scope role may add a material; editing an aggregate quantity or
  removing a line is Team Lead+ (Technicians get a read-only quantity plus Add
  Item).
- `mode` snapshots the order's `entry_mode` at logging time (a stock-moving
  entry joining a `retroactive` line surfaces as `dispense`).
- `transaction_id` is the most recent contributing transaction and may be NULL
  on a backfilled/self-healed line. `work_order_id` cascades; `item_id` is plain.

### `work_order_labor`

- Positive whole-minute actual labor per worker, mostly produced by stopping a
  tracked session. Edit rules under Roles And Access; every keyed row is marked
  Self or Admin.
- Billing sums all actual minutes on the order, rounds the combined total up
  once to the next 30 minutes, then charges `$62.50/hour` (SMR two-rate
  variant below). Rate and total are returned only to TechFM OA+; actual and
  billed durations are visible to every in-scope user.
- Hand-keyed labor changes no lifecycle status, including edits and deletes.

### `work_order_labor_sessions`

- A session records **when** somebody worked; `ended_at IS NULL` = clock
  running. Stopping computes minutes, creates a `work_order_labor` row and links
  it via `labor_id`.
- **An open session contributes nothing to billing** (no labor row yet), so
  billing, receipt and CSV are correct for a job in progress. Sessions have their
  own table so `minutes` need not be nullable.
- A partial unique index on `(technician_id) WHERE ended_at IS NULL` enforces one
  running clock per person across all orders. Starting a clock elsewhere first
  closes the other (labor row, `stopped work` note, that order's auto-hold; the
  abandoned row comes back through `services.work_orders.side_transitions` so
  its notification is not lost).
- Stopping the last clock on an In-Progress row moves it to On-Hold and fires
  `work_order.held`. Sessions stop wherever work provably ended: Stop Tracking,
  `/hold`, Notify Team Lead, archive, a Team Lead PATCH into
  `on_hold`/`ready_to_complete`/`completed`. `/resume` starts none. Each closed
  session writes a `stopped work` note authored by **its own technician**.
- **The 12-hour cap** (`domain.work_orders.LABOR_SESSION_MAX_MINUTES`,
  `capped_session_minutes`) truncates an overrun session, pulls `ended_at` back
  to the capped instant, and sets `auto_closed_at`. It is applied **lazily** (any
  read or tracking write; no task runner exists, same pattern as
  `_heal_orphan_lines`), so a never-opened order stays open past 12 h until read
  but closes at the correct time. It deliberately does **not** auto-hold. The
  card tags such entries "auto-stopped"; nothing blocks them billing. Its note is
  written at the capped time, so it can appear out of chronological order
  (entries are never sorted).

### `work_order_signatures`

- One witness sign-off per work order (unique `work_order_id`, cascade); a
  unique-index race gives the loser 409. "Unsigned" is no row, which keeps the
  image (deferred bytea) out of list queries. Optional, gates nothing; any
  viewer captures, Team Lead+ clears (no confirm; the note log records both);
  archive/restore leave it alone. Caps in `domain/work_orders.py`: PNG magic,
  <= 256 KB decoded, name <= 120, US phone normalized to 10 digits.

### `attendance_punches`, `attendance_punch_edits`

- A punch is **on-shift** time, the pay record, not the billable one.
  `start_source` is `manual`/`auto_work_order`; `end_source` is `manual`,
  `auto_clock_out`, `self_reported` (legacy only; nothing writes it) or
  `admin_edit`.
- Starting a work-order clock off shift opens an `auto_work_order` punch;
  punching out force-stops any running labor session. Attendance imports work
  orders, never the reverse.
- Audit rows (one per changed field, same transaction; `reason` optional) are
  written by `services.attendance` `admin_add_punch` / `admin_edit_punch` /
  `admin_delete_punch`.
- `deleted_at` makes a delete **soft** — the audit CASCADEs off the punch, so a
  hard delete would erase the record of the deletion. Every read goes through
  `attendance.live_punches()`, and the open-punch partial unique index is
  `WHERE ended_at IS NULL AND deleted_at IS NULL`.

### `tools`, `tool_transactions`

- `tools` is parallel to `items` but smaller (no location/price/link; not
  billed). `quantity` is on-hand, with items' `apply_delta` semantics. A row may
  be one serialized unit or a bulk batch (`quantity` > 1, shared barcode); no
  schema distinction.
- `archived_at` hides the tool but keeps history; archive is rejected while any
  user holds a positive balance. Barcode uniqueness is a **partial** index on
  live rows, so an archived tool's barcode is free to reuse; there is no
  cross-check against `items.barcode`.
- `tool_transactions` is an append-only checkout/return/adjust ledger (separate
  from `transactions`, which is coupled to billing). `adjust` is a signed delta;
  checkout/return quantity is positive. `assigned_to_id` (custody holder;
  required for checkout/return, NULL for adjust) and `performed_by_id` may
  differ.
- Custody is **derived, not stored**: per `(tool_id, assigned_to_id)`,
  Sum(checkout) - Sum(return) over checkout/return rows only
  (`services.tools.tool_custody` / `_outstanding_for_user` / `_custody_query`),
  so a count correction never corrupts a balance. A return may not exceed the
  user's balance (`domain.tools.validate_return`). A checkout target must be an
  active user. `user_custody` serves only the user-archive guard; the frontend
  card inverts `ToolResponse.custody`.
- `adjust` is Correct Count (`POST /tools/{id}/adjust`, TechFM OA+): the client
  sends the **absolute** new quantity, the service computes the delta under the
  row lock, and `reason` is required. It is also the only restock path.
- `work_order_id` / `work_order_number` on checkout/return are optional and
  stored as given (no find-or-create).

### `mass_stages`, `mass_stage_work_orders`, `mass_stage_items`

- A building's truck-staging plan; it **references** work orders. Slots
  (`UNIQUE(stage_id, work_order_id)`, `sort_order` drives load allocation;
  `stage_id` cascades, `work_order_id` is plain) hold planned items
  (`UNIQUE(stage_work_order_id, item_id)`). Planning moves no stock; loading
  increments `loaded_quantity`, returning `returned_quantity`; net consumed is
  loaded - returned.

### `conversations`, `conversation_members`, `messages` (Messaging)

| Fact | Rule |
|---|---|
| Kinds | `direct` (unique `direct_key` = `"<low id>:<high id>"`, race-safe get-or-create) or temporary `group` (Team Lead+ starts, 2–29 others, name ≤ 60; only the starter ends it = hard delete) |
| Read mark | `conversation_members.last_read_message_id` (no FK), only rises, capped at the newest message; a read emits only when it moved (stops two-reader loops). Client posts reads only while the page is visible and the chat is on screen |
| Unread / Seen | unread = messages past my mark not sent by me; badge = distinct senders. "Seen" (direct only) = the other member's mark ≥ my last message |
| Retention | direct messages 90 days; a group quiet 7 days (`coalesce(last_message_at, created_at)`) is deleted. Swept by the first `GET /messages/conversations` per 24 h per process — no lifespan job |
| Privacy | non-member → 404 on every chat route; text never on the socket, in a push or a log. Push = "New message from <name>", tag `chat-<id>` with `renotify`; tap posts `open-chat` to a window or opens `/?chat=<id>` |
| Frontend | one panel (`messagePanel.js` + `messagePanelChat.js`) in two hosts: the floating bubble (`messageBubble.js`, `#msg-float`, bottom sheet under 600 px, hidden during tutorials) and the Hub Messages tab (`hubMessages.js`). Bubble storage: `techfm.msgBubble.pos` `{side, y}`, `techfm.msgBubble.away` `"1"` (put away; clears on a real sign-in, not a reload — then a notification tap opens the Hub tab) |

## API Surface

Code owns the route table (`app.openapi()`), contracts and error catalog. What
stays here is behavior the code does not state in one place:

- **Tutorial progress.** `GET /tutorials/progress/me`, `PUT
  /tutorials/progress/{key}` (body `{event: seen|completed}` → 200 `{first}` = this call set it, key regex
  above, first write wins), `GET /tutorials/progress/users` (Team Lead+,
  `{user_id: [completed keys]}`, active users, row-capped).
- All routes except `POST /auth/login`, `GET /`, `GET /workorder_card/*`, and
  `GET /healthz` require authentication.
- **NetFacilities.** Disabled by default; production enables it in both the
  Dockerfile and `render.yaml` (a plain deploy does not sync new `render.yaml`
  env into an existing service). Auth is per-user Steel cloud sign-in only
  (env gates and timings in `integrations/netfacilities/` config). A captured
  session is **bearer-equivalent**: Fernet-encrypted one row per user, never
  committed, logged, returned, or placed in an env var; expiry is recovered by
  signing in again. The client **primes each context with one `GET /myhome`**
  before its first work-order read (an unprimed session gets a trimmed document
  with no Priority row) and re-primes any document lacking the `Priority Level`
  label. Enrichment fills only the exact generated Task/Symptom fallback and a
  blank Priority, via compare-and-set; responses and logs never contain source
  values, storage state, cookies, or headers. The two unverified edges are
  `N-NF-STEEL-SESSION` in `open-work.md`.
- **`/ws` runs no application middleware** — the rate limiter, security headers
  and request logger are `@app.middleware("http")` and the handshake is a
  `websocket` scope; the route does its own origin check and logging. Auth is
  the session cookie **revalidated every 60 s** (logout or role change closes
  the socket). Refusals happen before `accept()` as plain HTTP 401/429.
- **Web Push has two deliberately separate role floors**: `SUBSCRIBE_MIN_ROLE`
  (Technician) decides who is *offered* the opt-in (`/push/subscribe` itself is
  not role-gated; a subscription grants no authority), and
  `TEST_AUDIENCE_MIN_ROLE` (Admin) is `/push/test`'s audience; merging them
  makes the Owner's diagnostic buzz the whole crew. iOS exposes push only to a
  Home-Screen-installed app; logout unsubscribes **this device only**; only a
  404/410 deletes a subscription; the endpoint allowlist is re-checked on
  **every** send (a stored endpoint is an SSRF primitive); `/service-worker.js`
  is served from root because a worker's scope is its serving directory.
- Notification triggers are registered in `docs/notification-events.md`
  (updated in the same commit as any trigger change; procedure in
  `docs/adding-a-notification-trigger.md`), which also owns the mechanism rules.
- Attendance routes: `GET /hub/attendance/week`, `/live` and `POST
  /hub/attendance/clock-out/{user_id}` are Team Lead+; `/export` and
  `/week/review` admin only; the three punch writes use `get_current_user` plus
  the service guard.

## Frontend Feature Context

Navigation (`views/nav.js::showPage`): five task-domain groups — Inventory,
Field, People, Review, Integration. Every page in `PAGE_ACCESS` belongs to exactly one group
in `shell-head.html` or it does not appear in the nav; `applyRoleVisibility`
hides buttons, then empty groups. Icons are inline SVG `stroke="currentColor"`
(CSP forbids icon fonts). Activating Work Orders, Find Item, or Mass Stage
refetches (`cache: "no-store"`).

Login/landing: boot calls `/auth/me`; 401 shows login; any later 401 returns to
login globally. Landing is role-based (`landingPageForRole`): technician →
Transaction, Team Lead → Work Orders, admin/owner → History; a resumed batch
overrides it and opens Transaction.

Tutorials ("How this page works" pill, `tutorial.js`):
- Registry `tutorials/index.js` → per page `tutorials/<page>.js` (data-only `SCRIPTS`) + `<page>.sample.js` (`sample(user)` → `{"GET <path>": body}`). Pages: work-orders, transaction, user-hub, tools, saved-items, mass-stage, history, saved-users, user-requests, create-item, low-stock, admin-review, integrations; plus the page-less `starter` entry (below).
- Sample mode: `api.js::setSampleResponder` answers GETs by path (query ignored); writes go to the server. Sample ids use the reserved prefix `ffffffff-ffff-4fff-8fff-`.
- Pill goes in `[data-tutorial-slot]`, else the page's first `h2`. Start refuses while typed text is on the page; start and End reload the page (start waits for the reload to land); End fires `tutorial:end`.
- `open` selectors: a click is skipped when what it reveals is visible; `?` prefix = optional. The last click is judged by the script's `here` selector when it has one; `open` is retried once and waits for late targets to settle. A step whose target is missing or hidden is skipped.
- `minRole` on a script: the picker, Next and the guard skip scripts above the signed-in role.
- `starter` (`tutorials/starter.js`: menu, inventory, field, people, review): no sample, no page button, every script `sample: false`, so start reloads nothing and never calls `showPage`. A wait step (`waitTap`, optional `via` + `viaText`; logic in `tutorialWait.js`) lights one real menu button; the cover swallows all input except a tap inside the lit rect, forwarded to that element only (Enter/ArrowRight too; other keys blocked). A role that cannot see `waitTap` skips it and the steps up to the next wait. `expectNav` (3 s) keeps the run alive across the page change a forwarded tap causes; only `showPage`'s `endTutorial({fromNav})` is held back by it, sign-out and 401 still end it.
- `nav.showPage` to another page and `showLoginScreen` end a tutorial without a reload.
- `tests/frontend/views/tutorialGuard.test.js` is the rule for new scripts (targets per role, one sentence per box, ≤ 3 per step, ≤ 120 chars, id prefix); `describe("starter scripts")` walks every starter on the real nav per role.
- Progress: `tutorialProgress.js` caches `GET /tutorials/progress/me` once per sign-in and is cleared on sign-out and any 401; the player sends `seen` on start and `completed` on the last step. `tutorials/catalogue.js` flattens the registry; `tutorials/relevance.js` decides who a script is for from the live role (`PAGE_ACCESS` plus `minRole`).
- Welcome (`tutorials/welcome.js`, standalone: real data, no reload, centred targetless step 1): `auth.enterApp` → `views/welcome.js` `runWelcomeThenClockIn`; plain sign-ins only (not resumed batch / deep link); once per person ever via `claimSeen` (server `first`); clock-in prompt after it ends; Done lands on the Starter sub-tab. A manual run before it fired also uses it up (accepted). `startTutorial(page, key, { onEnd })` reports "done"/"ended".
- Red dot (`tutorialDots.js`): a page's button is dotted while any script relevant to the signed-in role is not completed; nobody signed in = no dot.
- `views/hubTutorials.js`: User Hub "Tutorials" tab (To do / Completed / Starter sub-tabs, tab dot; `setTutorialsSub(name)` picks the opening one); tapping plays the script, Replay records nothing. `views/usersTutorials.js`: Users row "N of M tutorials" and a profile list of unfinished ones; totals are computed in the browser from the `users` map.

Scanner: upload mode posts to `/barcodes/decode`; live mode is vendored ZXing in
the browser (environment camera, 1280×720 ideal, torch only if the track
reports it) and never calls the backend. Live scan uses dwell + same-barcode
cooldown; the camera auto-starts only with permission already granted and
stops on page leave/tab hide. Add Item has Item/Tool tabs, each with its own
scoped scan widget (`allowCreate: false`; page-leave stops both cameras).
`scan-test.html` is an unauthenticated diagnostic harness outside the SPA.

Scan / Stock: manual entry hides until a card is selected and commits through
the same `commitScannedItem` path a scan uses. A short dispense still commits
and renders red `Please re-count stock`. Technicians' gate sends
`assigned_to_id`, and the server refuses a dispense against an order they are
not on.

Work Orders: collapsed card background encodes status (Created gray, Assigned
red, In-Progress yellow, On-Hold orange, Ready to Complete violet, Completed
blue, Review green). Begin Charging is offered to every role but the Owner,
whose only forward action is Mark Completed. The Edit-details status dropdown
never offers `ready_to_complete` or Review. Buttons needing the crew
server-side are gated client-side too; **a Technician off the crew gets a
read-only card** (no notes box, add-material row or Remove buttons, one
`.wo-crew-lock` hint). The list loads every matching order in one request (no
cap, no "Show all").

SMR Labor card (`workOrderSmrLines.js` / `workOrderSmrActions.js`, Admin+
edits): an SMR order's Labor card lists its **charged** vendor lines only
(`GET /work-orders/{id}` sends charged lines only); Remove hard-deletes after
one confirm. The server links a keyed name to a live worker or alias of that
vendor silently. An SMR order whose only labor was keyed in the app keeps the
ordinary Labor card with no vendor entry row: a vendor line there would stop
those hours billing. An order with no vendor lines prints its standard labor as
`Belfor ST` at $62.50/h. The Request and Signature sections left the card
2026-11-06; `workOrderRequests.js`, `workOrderSignature.js` and routes 72a–72d /
S10–S12 remain, unmounted, and stay tested so the coverage gate holds
(`helpers/detachedSections.js`).

User Requests: a recount card's shortage snapshot is never editable (whitelist
`EDITABLE_DETAILS`; a rejected key is 409). Catalogue fulfilment links or
creates an item and logs it on the originating order **always retroactively**
(never moves stock; calls `attach_dispense_line` directly), warns-and-skips a
closed order recording the reason, and cascades to admin-confirmed siblings
matched on token-set equality.

Mass Stage: completed stages are read-only and terminal; Stage Again creates a
fresh empty stage (nothing copied).

Admin Review: one persistent receipt textarea (`pricingText.js` 41-char lines,
`billable ?? quantity` × current price +15%, labor total with no second markup,
`wrap="off"`); `NO PRICE` disables Close; either action keeps the receipt
visible for copying.

Tools: the Tools page defaults to **Custody**; a scan never commits
automatically; check-in defaults and caps to the outstanding balance. The page
composes existing endpoints — no custody endpoint or migration exists.

History: the work-order overlay filter matches each row's own
`work_order_number` (searchable forever, archived included); an exact archived
number prompts restore. Copy table exports all matching rows (cap 100 pages ×
100); the TechFM OA+ export fills work-order rows' pricing from the line
`unit_price` and appends the **Work Order Summary** block (`materials_total` +
15%) — per-row figures can diverge from it; the summary is authoritative.

Timesheets/Users profile: the week read (`GET /hub/attendance/week`) is
side-effect-free (no sweep, no locks; a forgotten job clock is clipped on read
by `work_orders.capped_session_end`), as is the profile
(`GET /hub/people/{user_id}/week`; Owner rows have none). A day-page time
change clears `needs_review`. A profile day is "Completed" for a crew member on
an order whose `completed_at` falls on that Central day; profile figures are
wall-clock minutes only, no billed number or dollars.

## Test Map

Run all tests with the repo venv (the system Python may lack dependencies):

```powershell
backend\venv\Scripts\python.exe -m pytest backend\tests
```

Database-backed tests use `backend/tests/conftest.py`, need Postgres through
`DATABASE_URL`, skip if it is unreachable, and let services `commit()` inside a
rolled-back outer transaction.

Guard tests that must be extended with the thing they guard:

| Test file | Extend or heed when |
| --- | --- |
| `test_route_role_gates.py` | adding a route: minimum-role gates, plus a guard that no gate is left at the Admin floor |
| `test_realtime_emit.py` | adding an emitter: it asserts the **exact** emitter set |
| `test_list_caps_applied.py` | adding a list endpoint: fails if it forgets the row cap |
| `test_memprobe.py` | adding a route: it must be catalogued or excluded in `scripts/memprobe_routes.py` |
| `test_notifications_domain.py` | adding a notification event: every event is a number event or a count event |
| `test_role_mirror_parity.py` | changing roles: `static/roles.js` must match `domain/roles.py` |
| `test_work_order_status_parity.py` | changing statuses: `ALL_STATUSES`, `statusLabel`, the page filter and the badge CSS must agree |
| `test_search_parity.py` | changing search normalization: `services/items.py` and `static/format.js` are pinned together |
| `test_receipt.py` | changing the fixed-width receipt: backend output must match the frontend contract |
| `test_db_availability_guard.py` | CI: DB-backed tests must not silently skip |
| `test_realtime_dependency.py` | dependencies: `TestClient` would pass without the WebSocket library installed |
| `test_push_subscriptions.py` | fan-out tests hide the developer database's real subscriptions inside the rolled-back transaction; keep that, or an enrolled device joins every send under test |
| `test_tutorial_progress_model.py`, `test_tutorials_service.py`, `test_tutorials_router.py` | progress table, first-write-wins and row cap, the three routes and their gates |

Frontend and E2E:

- Vitest (`npm test`, repo root): `static/` modules under jsdom on the real
  assembled shell with MSW answering `fetch`, so the real `api.js` runs.
  **Coverage is blocking** (thresholds in `vitest.config.js`, ratcheted by hand
  at each phase close); a view with no test shows as 0 %. Load shared-state
  view modules through `importView` inside the test. `helpers/actionAudit.js`
  (`auditActions()`) flags any rendered `data-action` with no handler, any
  handler outside its frozen list, and any action no behaviour test mentions.
- E2E (`pytest -m e2e` from `backend/`): real Chromium over the real app — every
  `SHELL_PARTS` page renders its landmark with an empty console, plus two
  work-order journeys and account creation. The only layer that sees CSP
  violations and the service worker. Needs Postgres and `python -m playwright
  install chromium`; missing either skips locally and fails under `CI=true`.
  Deselected by default (`backend/pytest.ini`) because it COMMITS
  `E2E-`-prefixed rows to `DATABASE_URL`, deleted at teardown and swept before
  the next run.

Anything neither covers: backend tests plus a manual browser check.

## Known Gaps

Do not "fix" these accidentally unless the task asks for it. Security gaps
(password floor, disabled per-IP throttle) are under Hard Invariants.

- Create Item UI sends blank price as `0`.
- Direct mass-stage detail/mutation routes are Team Lead+ gated but not
  creator-scoped; completed stages cannot be reopened; stage deletion does not
  reverse load transactions already written.
- Frontend ID and module contract drift is checked manually (no bundler/types).
- NetFacilities: `NetFacilitiesClient` needs an injected browser context (only
  the Steel adapter builds a working one); managed downloads, app-side
  credential/MFA handling and secondary-data retrieval are absent; default tests
  never make a live request. **Not yet done:** the manual D5/D6 replay spike,
  and deleting the unused `netfacilities-storage-state.json` secret file in
  Render's dashboard.
- Work-order numbers are one global namespace (no per-community scoping).
- A free-text work-order number on a transaction is *resolved* (never created)
  and only for Team Lead+; a technician's scan must carry a `work_order_id`.
- Not built: work-order `due_date` and `external_ref`/`source`.
- Tools: no void/undo for a checkout or return; no dedicated ledger page (only
  the derived custody balance is exposed); any authenticated user may return a
  tool on someone else's behalf (matches "any role can return").

## Removed, Replaced, And Dormant

Kept so a removal is not re-proposed and a dormant file is not mistaken for a
working feature.

| What | When | Replaced by / why |
|---|---|---|
| `GET /items/search-index` | 2026-08-10 (X3) | no caller; `GET /items/?q=` covers it |
| `backend/static/index.html` | 2026-06-12 | runtime shell assembly in `main.py`, deliberately uncached |
| Sliding-window session idle timeout | `c7e9a1b3d5f8` | absolute `expires_at` + remember-me; consequence: a password reset must revoke sessions |
| Pre-Steel NetFacilities auth — local headed sign-in, shared secret file, five local routes, `services/netfacilities_auth.py` and siblings | 2026-08-29 | per-user Steel cloud auth (`services/netfacilities_cloud_auth.py`) |

Still live — occasionally assumed dead: the **three** HTTP middleware layers in
`main.py` (`rate_limit`, `add_security_headers`, `log_request`; registration
order is the reverse of execution order, and `/ws` runs none of them), and
`static/scan-test.html` (an unauthenticated diagnostic harness outside the SPA).
