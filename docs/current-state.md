# Inventory App Current State

Last reviewed: 2026-08-06

Purpose of this file: give an AI or developer enough current-state context to
make technical changes without rereading the whole repository. Start here, then
open only the files named for the task.

This is the single durable repo documentation artifact for contracts and
invariants. Its companion `docs/endpoint-map.md` traces every endpoint
Database ↔ User View (router → service → table, and `api.js` → view) — use it to
locate the files for an endpoint without searching.

## How To Use This Doc

For implementation work:

1. Read `Fast Orientation`, `Architecture Rules`, and `Hard Invariants`.
2. Use `Task Routing Map` to pick the relevant files.
3. Read the matching `Feature Context` and `API Surface` rows.
4. Run the focused tests named in `Test Map`.
5. Update this file if shipped behavior, routes, schema, deployment, or known
   gaps change.

For review/debugging work:

1. Use `Data Model` and `API Surface` to identify the contract.
2. Use `Known Gaps` to avoid confusing intentional limitations with regressions.
3. Use `Test Map` to find existing coverage and missing coverage.

If this file conflicts with code, trust the code and update this file as part of
the change. The 2026-08-06 working-tree baseline has 72 OpenAPI application
operations, Alembic head `faa2c4e6b8d0`, and 478 passing backend tests. The
current documentation reconciliation is part of this baseline and must not be
mistaken for an older committed state.

## Fast Orientation

The app is a self-hosted inventory and work-order staging system for physical
materials tracked by barcode.

Runtime shape:

- FastAPI API and static SPA in one process.
- PostgreSQL persistence through SQLAlchemy and Alembic.
- Static no-build frontend under `backend/static`.
- Barcode upload decoding through backend `pyzbar`.
- Live camera scanning through vendored `@zxing/browser`.
- Render deployment: one Docker web service wired to an existing managed
  Postgres instance.

Core workflows:

- Find/create/edit inventory items by barcode.
- Stock, dispense, correct, void, and bill transaction rows.
- Scan items into work-order batches.
- Import/assign/log standalone work orders (identity = number); dispense or
  retroactively backfill materials.
- Plan/load/return materials for a community/building by unit (truck staging).
- Review/copy transaction history.
- Manage users and role-scoped access.
- Add tools by barcode and manage custody from a user-first profile card:
  Admin/Owner search active users and check out available tools by search or
  scan; every role can check in its UI-selected user's holdings. Bulk tools
  (`quantity > 1`) can still be split across multiple holders.

## Architecture Rules

Backend layering:

```text
routers -> schemas/services -> domain/models -> database
```

Rules:

- Routers stay thin: parse schemas, enforce auth, call services, translate
  `DomainError` through `routers/_errors.py`.
- Services own database queries, transactions, row locks, and commits.
- Domain modules are pure rules with no FastAPI/SQLAlchemy imports.
- Models mirror physical schema; every schema change needs a model change and
  an Alembic migration.
- Pydantic schemas define request/response contracts, not permissions.
- Backend gates are authoritative. Frontend role visibility is UX only.
- Frontend is plain ES modules. No bundler, type checker, generated clients, or
  build-time route validation.
- Static shell HTML is assembled from fragments in `backend/app/main.py`.

## Task Routing Map

Use this table before searching broadly.

Path shorthand:

- `domain/*`, `routers/*`, `schemas/*`, `services/*`, `models.py`, and
  `auth_deps.py` mean files under `backend/app/`.
- `static/*` means files under `backend/static/`.
- `test_*.py` means files under `backend/tests/`.

| Task area | Read these first | Usual tests |
| --- | --- | --- |
| Auth/session/login/logout | `app/auth_deps.py`, `routers/auth.py`, `services/auth.py`, `schemas/auth.py`, `static/views/auth.js`, `static/api.js` | `test_auth_password.py`, `test_auth_session_lifetime.py`, `test_session_token_hashing.py`, `test_password_reset_revokes_sessions.py` |
| Login throttling / lockout | `domain/login_throttle.py`, `services/login_throttle.py`, `routers/auth.py`, `models.py` (`LoginAttempt`), `backend/entrypoint.sh` (proxy headers) | `test_login_throttle.py`, `test_login_throttle_service.py` |
| Request rate limiting (all routes) | `domain/rate_limit.py`, `services/rate_limit.py`, `main.py` (`rate_limit` middleware), `backend/entrypoint.sh` (proxy headers, single process) | `test_rate_limit.py`, `test_rate_limit_service.py`, `test_rate_limit_middleware.py` |
| List-size ceiling (all list endpoints) | `domain/list_limits.py`, `services/_list_cap.py`, the six `list_*` service functions | `test_list_limits.py`, `test_list_cap_service.py`, `test_list_caps_applied.py` |
| Roles/permissions/user management | `domain/roles.py`, `routers/users.py`, `services/users.py`, `schemas/users.py`, `static/roles.js`, `static/views/users.js`, `static/views/nav.js` | `test_roles.py`, `test_route_role_gates.py`, `test_user_names.py`, `test_user_role_edit.py`, `test_user_archive.py` |
| Item CRUD/lookup/archive | `routers/items.py`, `services/items.py`, `schemas/items.py`, `models.py`, `static/views/items.js`, `static/views/itemEditor.js`, `static/api.js` | `test_item_barcodes.py`, `test_item_price_gating.py`, route-gate tests |
| Item notes | `domain/notes_validation.py`, `services/notes.py`, `schemas/items.py`, `routers/items.py`, `static/views/notes.js` | add/extend focused tests if behavior changes |
| Alternate barcodes | `models.py`, `services/items.py`, `schemas/items.py`, `routers/items.py`, `static/views/itemEditor.js`, `static/views/addBarcode.js` | `test_item_barcodes.py` |
| Stock/dispense/correction/void | `domain/quantity.py`, `services/transactions.py`, `routers/transactions.py`, `schemas/transactions.py`, `static/views/transactions.js`, `static/views/correction.js` | `test_quantity_reverse.py`, `test_user_requests.py`, route-gate tests |
| User Requests / operational exceptions | `models.py`, `services/user_requests.py`, `routers/user_requests.py`, `schemas/user_requests.py`, `services/items.py`, `services/work_orders.py`, `static/views/userRequests.js`, `static/pages/user-requests.html` | `test_user_requests.py`, `test_route_role_gates.py` |
| Billing/charge override | `domain/billing.py`, `services/transactions.py`, `services/work_orders.py`, `services/history.py`, `routers/transactions.py`, `routers/work_orders.py`, `static/pricingText.js`, `static/adminReviewReceipt.js`, `static/views/history.js`, `static/views/workOrders.js`, `static/views/adminReview.js` | `test_billing_validation.py`, `test_work_order_billing.py`, `test_history_price_snapshot.py`, `test_item_price_gating.py` |
| History filters/export | `services/history.py`, `routers/transactions.py`, `schemas/transactions.py`, `static/views/history.js`, `static/api.js` | `test_history_wo_filter.py` |
| Barcode upload decode | `services/barcodes.py`, `routers/barcodes.py`, `schemas/barcodes.py`, `static/views/scan.js`, `static/api.js` | `test_barcodes.py` |
| Live camera scan | `static/scan/barcode-decoder.js`, `static/scan/frame-debouncer.js`, `static/views/scan.js`, `static/scan-test.html`, `static/scan-test.js` | manual browser/device check; unit tests cover backend decode only |
| Scan-and-go work-order batch | `static/views/transactions.js`, `static/views/scan.js`, `routers/transactions.py`, `services/transactions.py`, `static/pages/transaction.html` | transaction/domain tests plus manual UI check |
| Mass staging API/domain | `domain/mass_staging.py`, `services/mass_staging.py`, `routers/mass_stages.py`, `schemas/mass_stages.py`, `models.py` | `test_mass_staging.py`, `test_mass_staging_load.py`, `test_mass_stages_api.py` |
| Mass staging UI (community tree) | `static/views/massStage.js`, `static/pages/mass-stage.html`, `static/api.js`, then backend mass-stage files | mass-stage tests plus manual UI check |
| Work Orders API/domain | `domain/work_orders.py`, `services/work_orders.py`, `routers/work_orders.py`, `schemas/work_orders.py`, `models.py` | `test_work_orders_domain.py`, `test_work_orders_service.py`, `test_work_order_line_sync.py`, `test_work_order_billing.py`, `test_route_role_gates.py` |
| Work Orders UI | `static/views/workOrders.js`, `static/pages/work-orders.html`, `static/api.js`, then backend work-order files | work-order tests plus manual UI check |
| Admin Review / fixed-width receipt | `static/views/adminReview.js`, `static/adminReviewReceipt.js`, `static/pricingText.js`, `static/pages/admin-review.html`, `static/views/history.js`, `static/views/nav.js`, `static/api.js` | work-order billing/role tests, pure receipt assertions, served DOM/resource check, manual UI check |
| Tools API/domain/service (custody) | `domain/tools.py`, `domain/quantity.py` (reused), `services/tools.py`, `routers/tools.py`, `schemas/tools.py`, `models.py` | `test_tools_domain.py`, `test_tools_service.py`, `test_route_role_gates.py` |
| Tools UI (Add Tools card + Tools page) | `static/views/tools.js`, `static/views/toolCheckout.js`, `static/views/toolReturn.js`, `static/pages/tools.html`, `static/pages/create-item.html`, `static/api.js` | manual UI check (no frontend test harness) |
| Deployment/runtime | `backend/Dockerfile`, `backend/entrypoint.sh`, `backend/alembic.ini`, `backend/app/database.py`, `render.yaml`, `requirements*.txt` | `git diff --check`; run tests if runtime deps change |
| Frontend navigation/layout | `static/shell-head.html`, `static/shell-tail.html`, `static/pages/*.html`, `static/views/nav.js`, `static/styles.css` | manual browser check; no frontend test harness |
| Database schema/migration | `models.py`, matching schemas/services, `backend/alembic/versions`, `database.py` | targeted DB-backed tests, then full pytest |

## File Map

Backend:

```text
backend/app/main.py              FastAPI app, routers, static mount, shell assembly
backend/app/auth_deps.py         cookie/session dependency and role gates
backend/app/database.py          engine/session setup and URL normalization
backend/app/models.py            SQLAlchemy schema model
backend/app/domain/*.py          pure business rules and domain errors
backend/app/domain/work_orders.py work-order status/mode/visibility rules
backend/app/domain/tools.py      tool-return outstanding-balance cap (validate_return)
backend/app/routers/*.py         route handlers and auth gates
backend/app/routers/work_orders.py Work Orders page routes (server-scoped)
backend/app/routers/tools.py     Tools CRUD + checkout/return routes
backend/app/schemas/*.py         request/response contracts
backend/app/services/*.py        DB-backed application logic
backend/app/services/work_orders.py Work Orders materials log (dispense/retro)
backend/app/services/tools.py    Tool CRUD + checkout/return + custody aggregate
backend/app/services/user_requests.py durable operational exception queue
backend/alembic/versions/*.py    migrations
backend/scripts/create_owner.py  owner bootstrap
backend/scripts/import_local_data.ps1 local data import helper
```

Frontend:

```text
backend/static/main.js           frontend composition root
backend/static/api.js            fetch wrappers for every backend route
backend/static/state.js          shared client state
backend/static/roles.js          frontend mirror of role hierarchy
backend/static/format.js         display/error/safe-url helpers
backend/static/dom.js            DOM helpers and confirm dialog
backend/static/views/*.js        page/view modules
backend/static/views/workOrders.js Work Orders page view
backend/static/views/tools.js    Tools page (list/search/scan) + Add Tool form binding
backend/static/views/toolCheckout.js Tool checkout sub-flow (Admin+)
backend/static/views/toolReturn.js Tool return sub-flow (any role)
backend/static/views/userRequests.js Admin/Owner request queue
backend/static/pages/*.html      SPA page fragments
backend/static/pages/work-orders.html Work Orders page fragment
backend/static/pages/tools.html  Tools page fragment
backend/static/shell-*.html      shell fragments
backend/static/styles.css        global styles
backend/static/scan/*.js         live scanner wrapper/debouncer
backend/static/vendor/*          vendored ZXing browser library
```

Tests:

```text
backend/tests/test_auth_*.py
backend/tests/test_roles.py
backend/tests/test_route_role_gates.py
backend/tests/test_barcodes.py
backend/tests/test_item_*.py
backend/tests/test_billing_validation.py
backend/tests/test_history_wo_filter.py
backend/tests/test_quantity_reverse.py
backend/tests/test_user_requests.py
backend/tests/test_mass_staging*.py
backend/tests/conftest.py
```

## Runtime And Stack

| Area | Current implementation |
| --- | --- |
| Python | 3.12 in Docker; local venv currently Python 3.13.7 |
| Web/API | FastAPI 0.136.3, Starlette 1.3.1, Uvicorn 0.48.0 |
| ORM/database | SQLAlchemy 2.0.50, psycopg 3.3.4, PostgreSQL |
| Migrations | Alembic 1.18.4 |
| Validation | Pydantic 2.13.4 |
| Env/config | python-dotenv 1.2.2 |
| Uploads | python-multipart 0.0.32 |
| Upload barcode decode | pyzbar 0.1.9, Pillow 12.3.0, native zbar |
| Live barcode decode | vendored `@zxing/browser` UMD 0.2.0 |
| Tests | pytest 9.0.3 |
| Fixture generation only | python-barcode 0.16.1 |

Deployment:

- Docker image: `python:3.12-slim`.
- Native package: Debian `libzbar0`.
- Entrypoint: `alembic upgrade head`, then Uvicorn on `${PORT:-8124}`.
- Render blueprint: `render.yaml`. Service name `inventory-app`, repo-declared
  production database target `inventory-db-copy`.
- `DATABASE_URL` is intended to be populated by
  `fromDatabase.name: inventory-db-copy` using Render's internal connection
  string. The original `inventory-db` is no longer declared in `render.yaml`
  after the 2026-08-10 work-order import rollback cutover. A CI deploy hook
  restart does not by itself prove this environment binding changed; verify a
  cutover with the Render service Environment page, Blueprint sync status, or
  the Admin-gated `/db-test` route. Public `/healthz` proves only database
  reachability, not the database identity. Owner confirmed later the same day
  that the Render environment/Blueprint binding was applied and the database
  rollback/cutover is successful and closed. The incident cause was an import
  of 800+ work orders that did not belong to the company.
- **`inventory-db-copy`, verified in the Render dashboard 2026-08-10:** plan
  **`basic-256mb`** (256 MB RAM, 0.1 CPU, **1 GB storage**), **point-in-time
  recovery available up to 3 days**, and the `inventory-app` binding confirmed
  and intended to stay. So the guarantees N5 closed on -- no expiry clock, a
  3-day recovery floor -- apply to the *active* production database and not
  merely to the instance N5 was written about. **`render.yaml` no longer
  declares any `databases:` block**, so these values exist only in the Render
  dashboard and in this line; nothing in the repo can detect them changing.
- The 1 GB storage ceiling is years away at this app's scale, structurally
  rather than by estimate: **no binary data is persisted anywhere.**
  `POST /barcodes/decode` stores nothing, the CSV import keeps parsed rows and
  discards the file, and there is no attachment feature. Growth is rows only --
  `transactions` grows forever, `sessions` is bounded by the 12h cap and the
  login sweep, `login_attempts` is swept after 24h. Revisit if the app ever
  stores files or if bulk imports become routine.
- Production URL: `https://inventory-app-gb1c.onrender.com` (owner-supplied
  2026-08-09; verified `GET /healthz` -> 200 `{"status":"ok"}` that day, which
  is the first confirmation that the B4 deploy came up healthy). **The Render
  dashboard is the authority, not this line** -- the hostname can change, and it
  had previously been recorded nowhere at all, which left `/healthz` unreachable
  for a full session after B2 built it.
- `healthCheckPath: /healthz` -- a real database query. It pointed at `/` until
  2026-08-09; `/` is a filesystem-only read, so deploys went green while
  Postgres was unreachable. A deploy that cannot reach the database now fails
  instead of succeeding silently. Render's own health polling does **not**
  keep a free instance awake (free services still spin down after ~15 min
  idle), so this changed nothing about spin-down behavior.
- Required env: `DATABASE_URL`.
- Production env should set `COOKIE_SECURE=true`, `SQL_ECHO=false`, and
  `LOG_LEVEL=INFO`.
- **`COOKIE_SECURE` now controls three things**, all meaning "this deployment is
  HTTPS/production": the session cookie's `Secure` flag, whether HSTS is sent
  (A4), and whether FastAPI's built-in docs endpoints exist at all (C4). It is
  deliberately one flag rather than three, so a deployment cannot be half
  production. `render.yaml` sets it to `"true"`.
- **`/docs`, `/docs/oauth2-redirect`, `/redoc`, and `/openapi.json` are absent in
  production** — `main._doc_urls` passes `None` for all three URLs when
  `COOKIE_SECURE` is true, which un-mounts the routes rather than gating them,
  so they return a plain 404. They are mounted normally when it is false.
  Closing `/openapi.json` removes the route, **not** the schema:
  `app.openapi()` still returns the full dict, which is what every
  operation-count check in `docs/api-hardening-checklist.md` relies on. There is
  no override env var; re-enabling in production takes a code change.
  Note that `/docs` and `/redoc` render blank wherever they *are* enabled,
  because A4's CSP blocks their CDN-hosted assets — see checklist item N8.
- Static assets are served with `Cache-Control: no-cache`.
- App sends `Permissions-Policy: camera=(self)` and `X-Request-ID: <12 hex>`.
- Windows local pyzbar may need Visual C++ 2013 runtime (`msvcr120.dll`).

Logging (`app/logging_config.py`, added 2026-08-09 as N1):

- **Format is logfmt** -- `ts= level= req= [user_id=] event= <fields>` on
  stdout, which Render captures. The record's *message* is the event name
  (`auth.login_failed`), so `grep event=auth.login_failed` is a complete query
  and `grep req=<id>` returns one whole request.
- **Every request gets a 12-hex id**, minted by the outermost middleware and
  echoed as `X-Request-ID` so a user's "it broke around 2:15" maps to an exact
  line. The incoming header is never trusted -- the id is always generated.
- **One `event=request` line per request**, with method, path, status, and ms.
  Uvicorn's own access log stays on alongside it: it is the fallback that keeps
  working if this middleware ever breaks. Uvicorn's loggers do not route
  through this formatter (`uvicorn` sets `propagate=False` and its dictConfig
  declares no `root`), so nothing is double-printed.
- **`user_id` is bound once**, in `auth_deps.get_current_user` -- the single
  dependency every authenticated route passes through.
- **Never logged**: passwords, session tokens raw or hashed, the `Cookie`
  header, request bodies, query strings (the request line records
  `request.url.path` only), and the database URL.
- **A failed login logs the username only if the account exists**, otherwise
  `user=unknown` (`services.auth.username_exists`). This is not politeness:
  logging the submitted string verbatim would put a password in the logs
  permanently the first time someone types it into the username field.
- Verbosity is `LOG_LEVEL` (default `INFO`); an unrecognised value falls back
  to INFO rather than failing the boot.
- Adding logs elsewhere needs no plumbing: `logging.getLogger(__name__)` and
  `extra={"fields": {...}}`. The request context is read at format time, so it
  attaches itself.

Upload size caps (`app/routers/_uploads.py`, added 2026-08-09 as B1):

- The app has exactly **two** upload routes and both are capped:
  `POST /barcodes/decode` at **10 MB**, `POST /work-orders/import` at **25 MB**.
  Both call `read_capped`; neither calls `file.file.read()` directly, and a
  third upload route should call it too.
- Over the cap is **413** with a `detail` naming the limit in MB. `api.js`
  surfaces `detail` for any non-2xx, so this renders in the existing error UI
  with no frontend code. Under the cap the behavior is byte-identical.
- The caps are **constants, not env vars** -- deliberately unlike `LOG_LEVEL`.
  Verbosity is operational; an upload limit is a contract, and one that varies
  per environment cannot be reasoned about from the code.
- **What the cap does not do:** Starlette's multipart parser has already
  received the whole body and spooled it (to disk past 1 MB) before any handler
  runs, so this bounds what is held **in memory** and what reaches Pillow or the
  CSV parser -- it does not stop a large body being transmitted. Refusing that
  early would need a `Content-Length` check in middleware; that was considered
  and rejected as a global interceptor against an already-disk-bounded threat.
- On `/work-orders/import` the Admin+ gate runs **before** the size check, so an
  unauthorised caller gets 403 and learns nothing about the cap. Since C1
  (2026-08-10) that ordering is FastAPI's rather than statement order in the
  handler: the gate is a dependency and the upload is a body param, and
  dependencies are solved before the form body is read.
- A refusal logs `event=upload.rejected_too_large` with `size` and `limit`.

## Hard Invariants

These are the constraints most likely to break real behavior if missed.

Inventory/transactions:

- Quantities and prices use `Decimal`/`Numeric`, not floats in backend logic.
- Stock/dispense/correction/void operations lock the item row before changing
  quantity.
- Scan / Stock and the Work Orders Add Item action record a dispense even when
  it exceeds the locked recorded count. The quantity may go negative so a later
  removal is the exact inverse, and the same commit creates one open
  `inventory_recount` User Request linked to the transaction. Work Order
  quantity edits, Mass Stage, tools, corrections, and reversal guards still
  reject an operation that would cross below zero.
- Transactions are append-only. Corrections are new `adjust` rows with a
  required reason.
- Voiding is a soft delete: set `voided_at`/`voided_by_id`, hide from history,
  reverse stock effect, and resolve any linked recount request.
- Voiding is rejected if reversal would make stock negative.
- Item archive is soft delete through `archived_at`.
- User archive is soft delete through `users.archived_at`: archived users
  cannot log in, sessions are revoked, and the row is retained for history.
  Archive is refused with 409 while the user has outstanding tool custody;
  retrying with `force_return_tools=true` checks every held tool in first
  (ordinary `return` rows attributed to the archiving admin) and then
  archives, in one transaction. The Users page offers that retry as a second
  confirm. Hard delete still exists but is blocked if transactions reference
  the user.
- Stock/dispense snapshot `Item.price` into `transactions.unit_price`;
  History reports that frozen snapshot, so editing an item price does NOT
  rewrite past line values. The single exception: a row snapshotted at 0 (a
  free dispense) tracks the live `Item.price`, so giving a previously-free
  item a real price DOES flow onto its past rows. A NULL snapshot
  (legacy/adjust) likewise falls back to the live price.
- Mass-stage unused returns add stock without transaction rows. This is the one
  deliberate silent stock change.
- `transactions.affects_stock` is TRUE for every ordinary stock/dispense/adjust.
  It is FALSE only for a *retroactive* work-order entry: such a row shows in
  History identically to a real dispense but did NOT move on-hand, so both its
  creation and its void skip the stock change. `void_transaction` branches on
  this flag (a stock-neutral void only soft-deletes the row).

Security/access:

- Backend role gates are source of truth.
- Frontend role hiding is only convenience.
- **Every static role gate is declarative** — `Depends(require_min_role(...))`
  on the route, never a rank check inside a handler body (item C1, 2026-08-10).
  `auth_deps.py:73` is the single place a role 403 is raised. There is exactly
  one deliberate exception, `routers/transactions.py:55`, which gates on
  `can_transact(role, payload.transaction_type)` and therefore needs the parsed
  body — a stock and a dispense are the same route with different minimums. The
  eight gated routes in `routers/work_orders.py` also declare
  `responses={403: ...}`, because FastAPI does not infer a 403 from a dependency
  that can raise one. Per-row *visibility* and the per-field edit matrix stay in
  the services, which need the loaded row.
- Sessions are server-side rows and carried by an HttpOnly `session` cookie.
  The row stores only the **SHA-256 hash** of the cookie token
  (`services.auth._hash_token`); the raw token is never persisted, so reading
  the `sessions` table yields nothing replayable. SHA-256 rather than scrypt is
  deliberate: the token is 256 CSPRNG bits, so there is no keyspace for a slow
  KDF to defend, and this hash runs on every authenticated request.
- Every session carries a hard absolute `expires_at` (NOT NULL, 12h). "Stay
  signed in for this shift" changes only whether the *cookie* is persistent, not
  server-side validity. There is no idle timeout — migration `c7e9a1b3d5f8`
  removed the old sliding window on purpose. An expired row is deleted on the
  first request that presents it; `sweep_expired_sessions` runs on every login
  and clears the rest, which is why no scheduler or background task exists.
- Sessions are revoked on user archive, role change, **and password reset** —
  all three via `services.auth.revoke_user_sessions`.
- Passwords are case-sensitive, not stripped, minimum 4 characters. The 4-char
  floor is below every current standard (NIST 800-63B rev 4 requires 8) and is
  a known, deliberately deferred gap — raising it invalidates existing
  passwords.
- `POST /auth/login` is throttled by exponential backoff, keyed on
  (submitted username, client IP): 5 free attempts, then 5s doubling to a 15min
  ceiling, returned as **429 + `Retry-After`**. It is never enforced by sleeping
  — a sleeping handler would hold a threadpool slot. Keying includes the IP and
  uses backoff rather than account lockout specifically so no one can lock a
  crew member out by hammering their username. A wider per-IP layer exists but
  ships disabled (`LOGIN_THROTTLE_PER_IP`); see Known Gaps.
- **Every non-exempt path is capped at 60 requests/second per caller** by the
  `rate_limit` middleware (`main.py`), which returns **429 + `Retry-After: 1`**
  above it. Exempt and neither counted nor refused: `/`, `/static/*`, and
  `/healthz` — so page loads cannot consume the budget, an over-limit caller can
  still load the SPA that fixes it, and a busy caller cannot fail a deploy
  through `healthCheckPath`. Callers are keyed by **session** (SHA-256 of the
  cookie, truncated), falling back to client IP when unauthenticated; the
  middleware runs before route dependencies resolve, so no user id exists yet.
  Counters are **in memory**, not in Postgres — the window is one second, so
  nothing older survives being worth keeping, and a write per request would cost
  more than the runaway client it catches. Refused requests are not themselves
  counted, so the cap cannot become an open-ended lockout. Never enforced by
  sleeping. This is a ceiling on malfunction, not a quota: the UI's heaviest
  action is far below it, and a runaway `fetch` loop is far above it —
  **confirmed by an owner browser pass against the deployed service on
  2026-08-10**, in which ordinary field work never approached the cap.
- **Every list endpoint returns at most 5,000 rows** (`MAX_LIST_ROWS`,
  `domain/list_limits.py`), applied in the service layer via
  `services/_list_cap.py`. This is a **safety ceiling, not pagination** — there
  are no `limit`/`offset` params and no page contract. When it bites, the list
  is truncated and an N1 line `event=list.truncated list=<name> cap=5000` is
  emitted; the caller receives a short list with no other signal, which is the
  accepted trade (X3). That log line is the trigger for building real
  pagination, and it names which list overflowed.
  - Capped: `/items/`, `/tools/`, `/users/`, `/mass-stages/`,
    `/user-requests/`, `/work-orders/`. The five SQL paths fetch
    `MAX_LIST_ROWS + 1` so truncation is detectable without a `COUNT(*)`,
    which bounds the database work as well as the response.
  - **`GET /work-orders/` is the exception in how the cap applies.** Its
    ordering is decided in Python because `schedule_date` is raw text (X2), so
    the ceiling bounds the *response*, not the query. Its `limit` param also
    gained an upper bound of `MAX_LIST_ROWS` (it was `ge=1`, unbounded), and
    omitting `limit` no longer takes a separate uncapped code path — same rows,
    same order, less loading.
  - **The Admin+ work-order CSV export is deliberately exempt** and remains the
    uncapped filtered set. A CSV that silently omits rows while looking complete
    is a records problem, not a performance one.
- Both upload routes are size-capped (10 MB image / 25 MB CSV) and return 413
  above it; see *Upload size caps* under Runtime And Stack. On the import route
  the role gate runs first, so an unauthorised caller never reaches the check.
- User management requires strict subordinate authority: actor rank must be
  greater than target role rank.
- Owner is bootstrap-only; API users cannot manage an owner.
- Admin/Owner cost fields are redacted server-side for lower roles.

Work orders:

- A work order is a standalone entity; **identity is its `number`**, unique
  case-insensitively + trimmed.
- Work Orders list filters are server-side and joinable: status, exact normalized
  service type, routed supervisor, derived community, exact scheduled date, and
  number substring all combine with AND before the caller's normal visibility
  scope is applied.
  Community membership checks both `community` and raw CSV `location` for
  Scholars, Centennial, Commons (`commons`/`cimarron`/`cimmarron`), or Young
  Hall. A multi-location row may match several named communities; Academics is
  the fallback when none match, including blank locations.
- `schedule_date` remains raw imported text. A leading `M/D/YYYY` (including
  two-digit years and optional trailing time) or ISO date is parsed for list
  behavior. Valid dates sort descending; blank/malformed legacy values sort
  last. The date control matches one exact calendar date.
- **Work orders are import-only.** The CSV import
  (`services.work_orders.get_or_create_work_order`) is the only path that creates
  one; there is no create endpoint and no "new work order" form. Every other
  surface calls `resolve_work_order`, which attaches to an existing number and
  404s on one no import has brought in. References still fill blank attributes
  but never overwrite non-blank ones. Existing rows are locked before an import
  merge: incoming supervisor routing applies only while the freshly locked row
  is still unassigned, so a manual reroute survives both later and concurrent
  re-imports.
- `GET /work-orders/export?scope=` writes one CSV row per work order and remains
  scoped to the caller like the list. Its two variants intentionally use
  different controls:
  - `variant=full` (the "Export filtered CSV" button beside Search) exports the
    complete current live result set with the same status, service type,
    supervisor, community, scheduled date, and number predicates as the cards;
    the recent-10 display cap never applies. It leads with the seven import
    headers and adds status, technicians, supervisor, billing totals, and
    timestamps, so the file re-imports through the idempotent fill-blanks path.
    The filename is a readable UTC date/time plus the active filter values, such
    as `08-04-26_17-12_status-in-progress-community-commons.csv`; an
    unfiltered export ends in `_all.csv`.
  - `variant=client` (the "For Client" button) is the billing sheet: `WORK
    ORDER`, `MATERIAL TOTAL`, `LABOR TOTAL`, `RECEIPT`. It remains controlled
    only by the existing `all`/status/archived scope dropdown. Both totals are the
    billed figures — materials carry the 15% mark-up, labor is the labor charge
    — so they add up to the receipt's own Total rather than disagreeing with the
    document next to them. `RECEIPT` holds the full Admin Review receipt text.
    Its filename uses the same convention with `client-<scope>`.
- The receipt has two implementations: `static/adminReviewReceipt.js` renders it
  for the Admin Review copy box, and `app/domain/receipt.py` renders the same
  characters for the client export. They must stay identical — the mark-up rate,
  the 41-character line width, name truncation, `NO PRICE` /
  `Total (incomplete)`, and money/quantity formatting all match, pinned by
  `tests/test_receipt.py`. Change one and the other has to move with it.
- Live status is `created` → `assigned` → `in_progress` → `completed` →
  `review`, with `on_hold` as a pause state that an assigned worker may enter
  only from In-Progress and Supervisor+ may otherwise manage. Every new
  import starts Created. Assigning one or more technicians advances a
  pre-work row to Assigned, and clearing every technician returns an Assigned
  row to Created; later states never rewind automatically. The first committed
  material or labor activity advances Created/Assigned to In-Progress through
  the same domain transition. An assigned Technician or Supervisor can use the
  Work Orders card walkthrough: the existing narrow `POST
  /work-orders/{id}/start` action moves Assigned to In-Progress, then the narrow
  `POST /work-orders/{id}/complete` action moves In-Progress to Completed.
  While In-Progress, the assigned worker also has a separate narrow `POST
  /work-orders/{id}/hold` action that places the row On-Hold. While On-Hold, its
  button is replaced by the assignment-checked `POST /work-orders/{id}/resume`
  action, which returns the row to In-Progress. Supervisor+ retains the unchanged
  general status controls as an additional management path.
  Selecting an Assigned Scan / Stock card also confirms the start transition and
  starts the batch in place; Created still redirects to Work Orders for
  assignment. Supervisor+ retains general status rollback, On-Hold/resume, and
  completion authority. Review is stricter: the row must already be Completed,
  and the caller must be an Admin+ or its routed Supervisor who is not also an
  assigned worker. This two-person handoff prevents an assigned Supervisor from
  completing and reviewing the same work. Manual pre-work rollback still derives
  Created/Assigned from the technician field. Material/labor activity does not
  resume On-Hold. `completed_at` is retained through Review and cleared by
  rollback/reopen. Closed is not a stored status: it is `archived_at`.
- Closing requires Admin+ and is valid from every live status. Each expanded Work
  Orders card exposes the confirmed Archive action to Admin/Owner; Admin Review
  retains its receipt-aware Close action for Review rows. The row and lines
  remain, the number stays reserved, and only the explicit `restore_work_order`
  workflow can return it to live views. CSV import counts and ignores it. Closing
  never touches historical transactions, which retain
  their own `work_order_number`.
- Logging a material writes a `dispense` transaction carrying `work_order_id` +
  number. `entry_mode` decides `affects_stock`: `dispense` moves stock,
  `retroactive` is stock-neutral (still shown in History). Mode is snapshotted
  per line; switching mode only affects subsequent entries.
- A `work_order_items` line is the **aggregate** of its dispenses for one item:
  `services.work_orders.attach_dispense_line` is the single home that every
  stock-out funnels through -- the Work Orders page button, the Scan/Stock page
  and scan-and-go (`services.transactions.apply_transaction`), and a Mass Stage
  truck-load (`services.mass_staging.load_item`). Re-logging an item ADDS to its
  one line (each scan is its own ledger row); membership is derived by
  `(work_order_id, item_id)`, not a single FK. A stock-in never creates a line
  (it is not "material used").
- `line.quantity` is the authoritative stored total. Editing it corrects stock by
  the delta and appends a single reconciling `adjust` transaction (the original
  scan rows stay intact -- the ledger stays append-only). Deleting a line returns
  its net units and voids every transaction it aggregated. Voiding a work-order
  dispense from History walks the line back (drops it at zero); a Mass Stage
  return (`reduce_dispense_line`) does the same so a loaded-then-returned item
  reflects net consumption. `get_work_order` lazily self-heals any orphaned
  linked dispense into a line (companion to the one-time backfill migration
  `c4e6a8b0d2f5`).
- The line is the **billing unit** for work-order materials: the customer charge
  is `effective_billable * current Item.price` (Admin/Owner only), where
  `effective_billable` is `work_order_items.billable_quantity` when set else the
  line `quantity`. Shown per line and summed into `materials_total` on the Work
  Orders page. Work-order-linked transaction rows (`work_order_id` set) are a pure
  inventory record -- History suppresses their per-row charge -- so editing a line
  never double-bills and a line-edit's signed `adjust` (the stock delta, e.g. `-6`
  when a line goes 2->8) is never billed as a negative. Ad-hoc (non-work-order)
  transactions keep their per-row History charge.
- `work_order_items.billable_quantity` is the per-line billing override
  (Admin/Owner, `PATCH .../items/{id}/billing`): NULL bills the full `quantity`,
  `0` records but does not charge, a value <= quantity bills a partial count. It
  never moves stock. Lowering a line's `quantity` below an existing override
  clears the override (reverts to full). Labor billing is implemented separately;
  additional fee, tax, and discount layers remain deferred.
- List/get/items are scoped server-side by
  `domain.work_orders.can_view_work_order`; out-of-scope/archived/unknown
  surface as 404. Supervisors see the shared unassigned pickup queue, rows
  routed to themselves, and rows where they are assigned to perform technician
  work; creator identity alone does not grant visibility after a row is routed
  elsewhere. A routing edit may target an active Admin or Supervisor. The
  editor sends its original `supervisor_id`; the service locks the row and
  returns a named 409 conflict if another request assigned it first. Notes,
  adding materials, and the assignment-checked start/complete walkthrough are
  Technician+; operational routing/general status/mode, labor, and material
  corrections are Supervisor+; Review adds the Completed + second-person gate;
  imported/legacy metadata and close/archive are Admin+; archive accepts any
  live status.

Mass staging:

- Stage status moves only `planning -> loading -> completed`.
- Slots/items are editable only in `planning`; loading/returning only in
  `loading`.
- Only one active non-completed stage per `(community, building_name)`.
- A stage references work orders through `mass_stage_work_orders` slots; adding
  one enforces the work order's community/building match the stage.
- Stage loading writes real per-slot `dispense` transactions carrying the slot's
  work order (and shows them on that work order's materials list); returns
  reverse-fill across slots, write no ledger row, and walk the work order's line
  back so it reflects net consumption.
- DB column names kept: `mass_stages.building_name` holds the building *number*.

Barcode:

- Primary item barcode and every additional barcode must be globally unique
  across both `items.barcode` and `item_barcodes.code`.
- Barcode lookup resolves primary or additional code to one live item.
- Archived items are hidden from barcode lookup.

Frontend:

- No build step. HTML ids/classes are runtime contracts with JS modules.
- Static shell is assembled in `main.py` from `shell-head.html`,
  `static/pages/*.html`, and `shell-tail.html`.
- Live camera must stop on page leave/tab hide to release track/torch.

## Roles And Access

Role order:

```text
owner > admin > supervisor > technician
```

| Capability | Rule |
| --- | --- |
| Login/logout/me | login public; logout/me require session |
| Dispense | any authenticated role |
| Stock | supervisor+ |
| History | supervisor+ |
| Void transaction | supervisor+ for any actionable row; Technician may remove only their own work-order dispense |
| Edit item notes | supervisor+ |
| Create/edit/archive item | admin+ |
| Correct count | admin+ |
| View item price/product link | admin+; server redaction below admin |
| Set billing override | admin+ |
| List users | supervisor+ |
| Create/reset/archive/restore/delete user | actor must outrank target |
| Edit user name + username | self, or actor outranks target |
| Change a user's role | admin+ AND actor outranks both the current and the new role |
| Mass-stage page/API | supervisor+ |
| Work Orders list/get/items | any authenticated user, server-scoped (Technician: assigned; Supervisor: unassigned OR routed to self OR assigned as a worker; Admin/Owner: all) |
| Edit Work Order notes / add material | any authenticated in-scope user |
| Edit Work Order supervisor / technicians / status / entry mode / labor / logged-material quantity or removal | supervisor+ (scoped) |
| Edit imported Work Order metadata (Location, Service, Schedule Date, Output to, Vendor Contact, Symptom/Task) | admin+ (scoped) |
| Import work orders (CSV) | admin+ |
| Export work orders (CSV, full or For Client) | admin+, server-scoped |
| Preview/re-archive all live legacy work orders | owner exactly; server gate and service check |
| Admin Review page / receipt | admin+; lists every live Review work order |
| User Requests page / request status | admin+; list and resolve/reopen operational exceptions |
| Close/archive a work order | admin+ (scoped), any live status; UI action lives on expanded Work Orders cards and remains in Admin Review for Review rows |
| Set work-order line billing override | admin+ (scoped) |
| Scan-gate work-order cards | any authenticated user (scoped Created/Assigned/In-Progress list); In-Progress starts a batch, Assigned confirms an in-place start for Technician+, Created opens Work Orders for assignment |
| Tools: view list/lookup, return | any authenticated user |
| Tools: create, edit, archive, checkout | admin+ |

Tools UI nuance: Admin/Owner can search every active user and act on that
user's custody card. Supervisor/Technician are pinned to their own card. The
HTTP return route remains session-gated and accepts any `assigned_to_id`; this
self-scope is a frontend workflow boundary, not a backend authorization rule.

Scoping nuance:

- `GET /mass-stages/` list is scoped: supervisor sees own stages, admin/owner
  all. Direct stage-by-ID routes are supervisor+ gated but not additionally
  creator-scoped once the caller has a stage id.
- The `/work-orders` routes DO add real per-row assignment scope checks
  (`services.work_orders`), because technicians reach them. Unassigned rows are
  the shared Supervisor pickup queue; a routed row is visible only to its
  selected Supervisor and Admin/Owner. The service also
  enforces the edit matrix: Technician = notes/add material; Supervisor+ =
  operations/labor/material corrections; Admin+ = imported/legacy metadata.

## Data Model

Primary keys are UUIDs. Timestamps are timezone-aware.

### `users`

Fields: `id`, `username`, nullable `first_name`, nullable `last_name`,
`password_hash`, `role`, `created_at`, `archived_at`.

Relationships:

- one user to many transactions
- one user to many sessions

Rules:

- `archived_at = NULL` means active; a timestamp means archived (soft
  delete). An archived user cannot authenticate and is excluded from the
  default user list, but the row is retained so history still resolves
  their name.
- Archiving also deletes the user's sessions, so an active login ends
  immediately.
- `username` is the unique login/account-management identifier. Operational
  pages render `full_name` (derived from first + last) instead. New users require
  both names. The columns remain nullable only for accounts that predate
  `f3b5d7a9c1e2`; those accounts render `Name unavailable` and cannot auto-route
  a CSV work order until the Users-page Edit Details action records real values.
- `username` is editable after creation through that same Edit Details action
  (`PATCH /users/{id}/name`, self or a manageable subordinate); uniqueness is
  still the database's call, surfaced as a 400. The password is unaffected,
  and sessions survive because they key on the user id, not the login name.
- `role` is editable by Admin+ through `PATCH /users/{id}/role`, which revokes
  the target's sessions so the role-shaped frontend cannot outlive the change.
- Full names are not unique. Two active routing-eligible users (Admin or
  Supervisor) with the same normalized first + last name are intentionally
  ambiguous during CSV routing.

Password hash format: `scrypt$n$r$p$salt_hex$hash_hex`.

### `sessions`

Fields: `token_hash`, `user_id`, `created_at`, `expires_at`.

Rules:

- `token_hash` is the **SHA-256 hex digest** of the opaque cookie value, and the
  primary key. The raw token is generated in `services.auth.create_session`,
  returned once for the cookie, and never stored — so a read of this table
  cannot be replayed as a credential.
- `user_id` cascades on user delete.
- `expires_at` is NOT NULL: every session has a hard absolute cap of 12 hours
  (`SESSION_LIFETIME` / `REMEMBER_LIFETIME`, currently equal). Indexed for the
  sweep.
- "Remember this device" affects only cookie persistence (`max_age`), not
  server-side lifetime.
- There is no idle timeout and no per-request write.
- Expired rows are deleted on the read that presents them, plus a
  `sweep_expired_sessions` call on every login. No scheduler.
- Rows are deleted wholesale by `services.auth.revoke_user_sessions` on user
  archive, role change, and password reset.

### `login_attempts`

Fields: `id`, `scope`, `key`, `failure_count`, `first_failed_at`,
`last_failed_at`, `locked_until`.

Rules:

- Transient failed-login counters for the throttle, **not** an audit trail:
  deleted on a successful login and swept after
  `domain.login_throttle.ATTEMPT_TTL` (24h).
- `UNIQUE(scope, key)`. `scope="user_ip"` keys on
  `"<casefolded username>|<ip>"` and is always active; `scope="ip"` keys on the
  bare IP and is active only when `LOGIN_THROTTLE_PER_IP=true`.
- The key uses the **submitted** username string, never a resolved user id —
  `services.auth.authenticate` deliberately conflates "no such user" with "wrong
  password", and keying on an id would leak account existence back out through
  which attempts get throttled.
- `locked_until = NULL` means "counting failures, not currently locked".
- The backoff curve lives in `domain/login_throttle.py` (pure). A locked caller
  is refused even with correct credentials — that is the point of a throttle.

### `items`

Fields: `id`, `barcode`, `name`, `quantity`, `location`, `notes`, `price`,
`product_link`, `created_at`, `archived_at`.

Rules:

- `barcode` is canonical/display code.
- `notes` is JSONB with string keys and scalar values (`str`, `int`, `float`,
  `bool`).
- `archived_at` hides item from lists/lookups but keeps joins for history.
- `price` and `product_link` are cost-sensitive and server-redacted below
  Admin.

Update behavior:

- `PATCH /items/{id}` is a partial update keyed on Pydantic
  `model_fields_set`: any subset of `barcode`, `name`, `location`, `price`,
  `product_link` may be sent, and a price-only or product-link-only patch
  is accepted.
- An explicit `null` for the nullable `price` / `product_link` clears the
  stored value; `barcode` / `name` / `location` reject null or blank.
- Create Item UI still sends blank price as `0` (see Known Gaps).

### `item_barcodes`

Fields: `id`, `item_id`, `code`, `created_at`.

Rules:

- Additional package codes only; canonical code stays on `items.barcode`.
- `code` is unique inside this table.
- Services enforce cross-table uniqueness against primary barcodes.
- Child rows cascade if an item is truly hard-deleted. Normal item delete is
  archive, so cascade is not part of ordinary UI flow.

### `transactions`

Fields: `id`, `item_id`, `user_id`, `transaction_type`, `quantity`,
`unit_price`, `billable_quantity`, `work_order_number`, `work_order_id`,
`reason`, `affects_stock`, `created_at`, `voided_at`, `voided_by_id`.

Rules:

- `transaction_type`: `stock`, `dispense`, or `adjust`.
- Stock/dispense quantity is positive.
- Adjust quantity is signed delta.
- `reason` required for adjust.
- `work_order_id` is the FK link to the standalone work order;
  `work_order_number` is the denormalized snapshot kept for History (the router
  resolves both from a scanned card or by looking the free-text number up). The
  snapshot is what History filters on, so a work order's transactions stay
  searchable by number even after the work order is archived.
- `unit_price` snapshots `Item.price` when a stock/dispense row is written
  (NULL for `adjust` and pre-snapshot rows). For an **ad-hoc** (non-work-order)
  row History reads this snapshot (frozen), so editing an item price does not
  rewrite past line values -- EXCEPT a row snapshotted at 0, which falls back to
  the live `Item.price` (so a free item later given a real price reflects on its
  past rows); a NULL snapshot also falls back to live. For a **work-order** row
  (`work_order_id` set) History forces `item_price` NULL: that material bills via
  its `work_order_items` line, not the row (see Work orders invariants).
- `transactions.billable_quantity` is the per-transaction (ad-hoc) override:
  NULL bills the full recorded quantity, `0` records but does not charge, and it
  cannot exceed the recorded quantity or target an `adjust`. Work-order rows are
  not billed per-row, so their override lives on the line, not here.
- `voided_by_id` is a plain UUID, not a second FK to users.
- `affects_stock` defaults TRUE. FALSE marks a retroactive work-order entry
  that shows in History like a dispense but never moved on-hand; create and
  void both skip the stock change for it.

### `user_requests`

Fields: `id`, `request_type`, `status`, `message`, nullable `item_id`, unique
nullable `transaction_id`, nullable `work_order_id`, nullable `created_by_id`,
JSONB `details`, `created_at`, nullable `resolved_at`, nullable
`resolved_by_id`, nullable `resolution_note`.

Rules:

- The generic queue currently has `inventory_recount` and
  `missing_item_price` types; statuses are `open` and `resolved`.
- A short Scan / Stock dispense or Work Orders Add Item dispense creates the
  request atomically with the transaction. `details` freezes recorded-before,
  dispensed, shortage, and work order number values for Admin review.
- Adding a material whose price is NULL or non-positive (`$0.00` included) to
  any work order creates one open
  `missing_item_price` request per item. Repeated use does not duplicate the
  queue entry; `details.work_order_numbers` accumulates every affected work
  order. The request card saves Price + Product Link together through the item
  PATCH and stays open until a positive price and nonblank link both exist.
- Adding a positive price and product link anywhere through `update_item`
  auto-resolves that item's open missing-price requests in the same commit.
  Resolved history is retained with `Item price and product link added.`
- Requests are resolved/reopened, never deleted. Voiding a source Scan / Stock
  transaction or removing its Work Order material line auto-resolves the open
  transaction-linked request with `Source transaction removed.`
- `created_by_id`/`resolved_by_id` use `ON DELETE SET NULL`; item, transaction,
  and work-order context remains durable through the normal soft-archive flows.

### `work_orders`

Fields: `id`, `number`, `community`, `building_number`, `unit_number`,
`description`, `notes`, `status`, `entry_mode`, `assigned_to_id`, `created_by_id`,
`created_at`, `updated_at`, `completed_at`, `archived_at`, `location`,
`output_to`, `vendor_assignee`, `service_type`, `schedule_date`,
`supervisor_id`, `legacy`.

Rules:

- The standalone first-class entity. **Identity is `number`**, unique
  case-insensitively + trimmed via the functional index
  `uq_work_orders_number_ci` (`lower(btrim(number))`).
- **Import-only.** `POST /work-orders/import` →
  `services.work_orders.get_or_create_work_order` is the only path that creates a
  row. Every other surface (the Work Orders page, the scan gate, Mass Stage)
  resolves an existing number via `resolve_work_order` and gets a 404 for one
  that was never imported. There is no create endpoint or form anywhere.
- Live `status` values are `created`, `assigned`, `in_progress`, `on_hold`,
  `completed`, and `review`. Closed is `archived_at`, not a stored status value.
  On-Hold is stable during material/labor activity until Supervisor+ explicitly
  resumes or rolls it back. New imports
  default to Created; worker assignment derives Assigned, and the first
  material/labor activity derives In-Progress. Migration `f4c6e8a0b2d3` added
  the five-state lifecycle, while `f5d7f9b1c3e4` aligned existing pre-work rows
  with technician assignment.
- `entry_mode` (`dispense` / `retroactive`) is the default mode for newly logged
  materials.
- `notes` is an append-only plain-text log on the work order. Every nonblank
  Technician+ save is serialized under the Work Order row lock and appends
  `[h:mm AM/PM] [MMDDYY] [Full Name] note text`, using server time converted to
  `America/Chicago`. Pre-log free-form text remains intact; blank/null input
  cannot erase the history.
- `work_order_technicians` is the authoritative plural assignment relation.
  Active Technician and Supervisor accounts are eligible workers; membership
  drives Technician visibility and also preserves a working Supervisor's scope
  when a different Admin/Supervisor owns routing
  (`domain.work_orders.can_view_work_order`). `assigned_to_id` remains a
  compatibility mirror of the first selected worker for Mass Stage and older
  clients.
- Soft delete via `archived_at` is the Closed state; the number stays reserved
  and material lines are kept. Closing is Admin+ from any live status and is
  available on expanded Work Orders cards. A closed work order is invisible to list
  and detail loads, so it comes back only through explicit `restore_work_order`
  (`POST /work-orders/{id}/restore`, Supervisor+). CSV import and ordinary
  references leave it archived. `lookup_work_order` is the one read that reports a closed
  work order so History can offer restore.
- References fill blank attributes but never overwrite non-blank ones; explicit
  edits (`update_work_order`) overwrite. Reference/import merges lock the row;
  `supervisor_id` fills only when the locked value is NULL. Explicit routing
  locks the same row, validates an active Admin or Supervisor target, and can compare the
  caller's `expected_supervisor_id` to reject stale pickup attempts with 409.
- **CSV-import schema (the new default source of truth).** The mass work-order
  export is bulk-imported via `POST /work-orders/import` (Admin+). Its columns
  land on `location` (raw LOCATION string, deliberately unparsed), `output_to`,
  `vendor_assignee` (the raw "ASSIGNED TO" contact -- a vendor name, NOT a system
  user), `service_type`, `schedule_date` (raw; some rows carry a time), and
  `description` (SYMPTOM/TASK). Import funnels each live row through
  `get_or_create_work_order` by number. A blank/missing task becomes
  `https://system.netfacilities.com/tools/viewworkorders/<URL-encoded number>`.
  That exact generated URL is synthetic and replaceable by a later real CSV task;
  every real/manual task and other non-blank metadata remains authoritative under
  the normal fill-blanks merge. Notes, assignments, lifecycle, materials, labor,
  billing, and existing non-blank values remain untouched. Archived matches are counted
  as `closed` and skipped before routing or merge, so CSV import cannot restore
  or alter a closed work order.
- `supervisor_id` is the Admin/Supervisor a work order is routed to. Import sets it by
  matching the normalized `vendor_assignee` name to an active Admin or Supervisor's
  first + last name (`services.work_orders._supervisor_lookup`). Missing,
  unmatched, incomplete, archived, ineligible-role, or duplicate/ambiguous names
  import cleanly as unassigned (`NULL`); Supervisor+ can route one later via
  `update_work_order`. Supervisor routing does not change lifecycle status.
  The plural worker set advances a Created row to Assigned when non-empty
  and returns an Assigned row to Created when cleared, while later lifecycle
  states never rewind automatically. `supervisor_id` drives Supervisor
  visibility directly (see `can_view_work_order`): NULL is the shared pickup
  queue, a routed row is visible to that Supervisor, and an assigned Supervisor
  retains access as a worker even under different routing. Import and explicit
  routing lock the same row so import fills only NULL routing and a stale pickup
  cannot overwrite a winner.
- `legacy` marks a pre-import work order. The import migration
  (`f2a4c6b8d0e1`) set `legacy=true` on every then-existing row and NULLed its
  old descriptive attributes (`community`/`building_number`/`unit_number`/
  `description`), keeping only `number`, `status`, assignment, and its
  `work_order_items` -- so an already-priced-out work order stays fully
  searchable, just with empty new-schema fields. Unlike `archived_at`, `legacy`
  does NOT hide the row from lists/search.
- The Owner-only legacy re-archive action counts and soft-archives only rows
  where `legacy=true` and `archived_at IS NULL`. Its bulk update is atomic;
  already archived legacy rows and live current-schema rows are untouched.

### `work_order_items`

Fields: `id`, `work_order_id`, `item_id`, `quantity`, `billable_quantity`,
`mode`, `transaction_id`, `created_by_id`, `created_at`, `updated_at`.

Rules:

- The editable "materials actually used" list for a work order, separate from
  `mass_stage_items` (truck planning). One row per item per work order
  (`UNIQUE(work_order_id, item_id)`); re-logging an item ADDS to its row -- the
  line is the aggregate of that item's dispenses, written by every stock-out path
  via `attach_dispense_line`. The line is also the **billing unit**: the
  Admin/Owner charge is `effective_billable * current Item.price` (exposed as the
  response `unit_price`, redacted below Admin), so work-order-linked transaction
  rows carry no per-row charge in History.
- Every in-scope role may add a material. Editing an aggregate line quantity or
  removing a line requires Supervisor+; the UI therefore gives Technicians a
  read-only quantity plus only the Add Item workflow.
- `billable_quantity` is the per-line billing override: NULL bills the full
  `quantity`, `0` records but does not charge, a value <= `quantity` bills a
  partial count (`effective_billable` = override when set else `quantity`). Never
  moves stock; cleared automatically if a line edit lowers `quantity` below it.
- `mode` snapshots the work order's `entry_mode` at logging time (a stock-moving
  entry joining a `retroactive` line surfaces it as `dispense`).
- `transaction_id` references the most recent contributing `Transaction` (the
  line aggregates many, found by `(work_order_id, item_id)`); it may be NULL on a
  backfilled / self-healed line. `work_order_id` FK is `ON DELETE CASCADE`;
  `item_id` is plain.

### `work_order_technicians`

Fields: `work_order_id`, `technician_id`, `assigned_by_id`, `created_at`.

Rules:

- Composite primary key `(work_order_id, technician_id)` permits each work order
  to carry multiple unique workers. Active Technician and Supervisor accounts
  are eligible. Work-order deletion cascades; removing an assignment does not
  remove that worker's historical labor.
- Supervisor+ replaces the complete assignment set through
  `PATCH /work-orders/{id}` with `assigned_to_ids`. Every assigned Technician or
  Supervisor can list and act on the work order. The legacy singular request remains accepted
  for compatibility.

### `work_order_labor`

Fields: `id`, `work_order_id`, `technician_id`, `minutes`, `recorded_by_id`,
`created_at`, `updated_at`.

Rules:

- Each row records positive whole-minute actual labor attributed to a worker
  assigned to the work order. All labor create/edit/remove operations require
  Supervisor+ and may target any assigned Technician or Supervisor.
- Billing sums all actual minutes on the work order, rounds the combined total
  upward once to the next 30 minutes, then charges `$62.50/hour`. Rate and total
  are returned only to Admin/Owner; actual and billed durations are visible to
  every in-scope user.
- The first labor insert uses `status_after_activity`, advancing Created/Assigned
  to In-Progress while leaving On-Hold and later states unchanged. Editing or
  deleting labor never rolls lifecycle status backward.

### `tools`

Fields: `id`, `barcode`, `name`, `quantity`, `created_at`, `archived_at`.

Rules:

- Parallel to `items` but deliberately smaller: no `location`, `price`, or
  `product_link` (tools are not billed or shelved like consumable
  materials).
- `quantity` is the on-hand/available count -- identical semantics to
  `items.quantity`. A checkout decrements it, a return increments it, via
  the same `domain.quantity.apply_delta` items use.
- A row may represent one specific serialized unit (`quantity` effectively
  1, its own barcode) or an unserialized bulk batch (`quantity` > 1, one
  shared barcode, fungible units) -- both valid; there is no schema
  distinction. "Serializing" a batch later is a manual data-entry pattern
  (shrink the bulk row's quantity, create individual rows with their own
  barcode as units get labeled), not a conversion feature.
- `archived_at` hides the tool from `list_tools` / barcode lookup but keeps
  the row so `tool_transactions` history still resolves it, mirroring
  `Item.archived_at`. Archiving is rejected while any user has a positive
  outstanding custody balance for the tool.
- Barcode uniqueness is a **partial** unique index scoped to live rows
  (`archived_at IS NULL`), not a plain column UNIQUE like `items.barcode`
  -- an archived tool's barcode is simply free to reuse with no retire/
  confirm dance (unlike items' archived-barcode-conflict/override flow).

### `tool_transactions`

Fields: `id`, `tool_id`, `transaction_type`, `quantity`, `assigned_to_id`,
`performed_by_id`, `work_order_id`, `work_order_number`, `reason`,
`created_at`.

Rules:

- Append-only checkout/return/adjust ledger -- the custody-tracking
  analogue of `transactions`, kept as a separate table because the
  vocabulary and the custody field have no equivalent on `transactions`,
  which is tightly coupled to billing/work-order logic.
- `transaction_type`: `checkout`, `return`, or `adjust`. Checkout/return
  `quantity` is positive; `adjust` `quantity` is a **signed delta** (mirrors
  `transactions.quantity`'s convention for `adjust` rows).
- Carries two distinct user references: `assigned_to_id` (who has/had
  custody -- required for `checkout`/`return`; **NULL for `adjust`**, which
  has no custody holder) and `performed_by_id` (who was logged in and
  processed the action, nullable, mirrors `Transaction.user_id`).
  `assigned_to_id` and `performed_by_id` may differ -- an Admin can check a
  tool out to a technician.
- "Who currently has a tool" is **derived, not stored**: for a given
  `(tool_id, assigned_to_id)` pair, outstanding =
  Sum(checkout.quantity) - Sum(return.quantity), computed **only** over
  `checkout`/`return` rows (`services.tools.tool_custody` /
  `_outstanding_for_user` / `_custody_query`) -- an `adjust` row is
  explicitly excluded so a count correction never corrupts a custody
  balance. A bulk tool can be split across multiple holders.
- A return may never exceed that user's current outstanding balance for
  the tool (`domain.tools.validate_return`, raises
  `ToolReturnExceedsCheckedOutError`).
- A checkout target must be an active user. `checkout_tool` rejects an unknown
  or archived `assigned_to_id` before changing on-hand quantity or appending a
  ledger row.
- `services.tools.user_custody` derives one user's positive balances across all
  tool ledger rows, including any legacy archived tool, for the user-archive
  guard only. The frontend card instead inverts the existing
  `ToolResponse.custody` lists. User and tool archive operations both lock
  their primary row and reject the archive until every outstanding unit is
  checked in.
- `adjust` is the "Correct Count" action (`POST /tools/{id}/adjust`,
  Admin+, mirrors `POST /transactions/adjust`): the client sends the
  **absolute** new on-hand quantity, the service computes the signed delta
  under the row lock via `domain.quantity.apply_delta(qty, "adjust",
  delta)`, and `reason` is required (schema-validated non-blank). This is
  also how a bulk tool gets "restocked" -- there is no separate stock-in
  endpoint, a correction that raises the count serves both purposes.
- `work_order_id` / `work_order_number` are an optional, **never required**
  linkage on checkout/return -- unlike `transactions.work_order_id`, there
  is no find-or-create behavior; a free-text number is stored as-is,
  denormalized. Not applicable to `adjust`.
- No void/undo exists for a tool_transactions row in this phase (unlike
  `transactions.voided_at`) -- see Known Gaps.

### `mass_stages`

Fields: `id`, `community`, `building_name`, `status`, `created_by_id`,
`created_at`, `updated_at`, `completed_at`.

Rules:

- A building's truck-staging plan; it **references** work orders (does not own
  them). `community` is the top tree level; `building_name` holds the building
  *number* (column name kept). `status`: `planning`, `loading`, `completed`.
- Partial unique index `uq_mass_stages_active_community_building` permits only
  one active non-completed stage per `(community, building_name)`.

### `mass_stage_work_orders`

Fields: `id`, `stage_id`, `work_order_id`, `sort_order`, `created_at`.

Rules:

- A work order's ordered slot in a stage's truck plan (replaces the old
  `mass_stage_rooms`). `UNIQUE(stage_id, work_order_id)`. `sort_order` drives
  load allocation. `stage_id` FK is `ON DELETE CASCADE`; `work_order_id` is a
  plain FK (the work order is independent).
- Adding a work order enforces its community/building match the stage.

### `mass_stage_items`

Fields: `id`, `stage_work_order_id`, `item_id`, `planned_quantity`,
`loaded_quantity`, `returned_quantity`, `created_at`.

Rules:

- One planned item row per slot/item pair (`UNIQUE(stage_work_order_id, item_id)`).
  Truck-plan estimates, distinct from `work_order_items` actuals.
- Planning does not move stock.
- Loading increments `loaded_quantity` and writes per-slot dispenses carrying
  the slot's work order; Returning increments `returned_quantity` and silently
  adds stock back. Net consumed is `loaded_quantity - returned_quantity`.

## API Surface

All routes except `POST /auth/login` and `GET /` require authentication unless
specified.

### App

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| GET | `/` | public | assembled SPA shell |
| GET | `/healthz` | public | liveness probe: runs `SELECT 1`; `{"status":"ok"}` or 503 `Database unavailable.` Reports no database detail -- it is unauthenticated |
| GET | `/db-test` | admin+ | database/user probe |
| GET | `/docs`, `/redoc`, `/openapi.json` | public **locally only** | FastAPI's built-ins. Un-mounted entirely when `COOKIE_SECURE=true`, so production returns 404 (C4). Not counted among the 73 application operations |

### Auth

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| POST | `/auth/login` | public | authenticate, create session, set cookie; 401 on bad credentials, **429 + `Retry-After`** while throttled |
| POST | `/auth/logout` | session | delete session, clear cookie |
| GET | `/auth/me` | session | return username plus first/last/full display name, role, and profile timestamps |

### Items

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| POST | `/items/` | admin+ | create item |
| GET | `/items/` | session | list non-archived items newest-first; optional `q` performs case-insensitive literal substring search on name/primary barcode; blank `q` returns no rows |
| GET | `/items/{barcode}` | session | lookup live item by primary or additional barcode |
| PATCH | `/items/{item_id}` | admin+ | partial edit of barcode/name/location/price/product link; explicit null clears price/link |
| PATCH | `/items/{item_id}/notes` | supervisor+ | replace notes object |
| PATCH | `/items/{item_id}/barcodes` | admin+ | replace additional barcodes |
| DELETE | `/items/{item_id}` | admin+ | archive item |

### Users

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| POST | `/users/` | actor outranks target role | create user; username + first/last name required |
| GET | `/users/` | supervisor+ | list users; `include_archived` adds archived users |
| PATCH | `/users/{user_id}/name` | self or actor outranks target | replace required first + last name and, when supplied, the unique login username; legacy-account remediation |
| PATCH | `/users/{user_id}/role` | admin+ and actor outranks current + new role | change role and revoke the target's sessions |
| POST | `/users/{user_id}/reset-password` | actor outranks target | reset password |
| POST | `/users/{user_id}/archive` | actor outranks target | archive (soft delete) user; revokes sessions; optional `force_return_tools=true` checks in all held tools first |
| POST | `/users/{user_id}/restore` | actor outranks target | reactivate archived user |
| DELETE | `/users/{user_id}` | actor outranks target | hard delete unreferenced user |

### Transactions And History

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| POST | `/transactions/` | session plus direction rule | create stock/dispense; a short Scan/Stock dispense returns recount metadata and creates a User Request |
| POST | `/transactions/adjust` | admin+ | absolute count correction |
| PATCH | `/transactions/{transaction_id}/billing` | admin+ | set/clear billing override |
| DELETE | `/transactions/{transaction_id}` | session; Supervisor+ any row, Technician own work-order dispense only | void transaction, reverse stock/line, resolve linked recount request |
| GET | `/transactions/` | supervisor+ | paginated history, voided rows excluded |

History filters:

- `item_id`
- `user_id`
- `work_order_number`
- `date_from`, inclusive UTC calendar date
- `date_to`, inclusive UTC calendar date
- `page`, default 1
- `page_size`, default 10, max 100

Filter behavior:

- filters combine with AND
- work-order filter is case-sensitive substring match
- SQL `%`, `_`, and escape characters are escaped
- Admin/Owner rows include `item_price` and `billable_quantity`, EXCEPT
  work-order rows (`work_order_id` set) which null both -- that material bills
  via its work-order line, not the row
- Supervisor rows receive null for cost/billing fields
- every row carries `work_order_id` (NULL for ad-hoc / legacy number-only rows)
  so the client can resolve a row to its work order (e.g. the copy-table summary)

### Barcodes

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| POST | `/barcodes/decode` | session | decode uploaded image bytes, no persistence |

Readable image with no barcode returns `200 {"barcodes": []}`.
Unreadable image returns 400.
An image over **10 MB** returns 413 without being decoded (see *Upload size
caps*).

### User Requests

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| GET | `/user-requests/?status=open|resolved` | admin+ | list newest-first requests with item/work-order/user context plus current item price/link |
| PATCH | `/user-requests/{request_id}` | admin+ | resolve or reopen a durable request |

### Tools

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| POST | `/tools/` | admin+ | create tool |
| GET | `/tools/` | session | list live tools, each with current custody breakdown |
| GET | `/tools/{barcode}` | session | lookup live tool by barcode |
| PATCH | `/tools/{tool_id}` | admin+ | partial edit of barcode/name |
| DELETE | `/tools/{tool_id}` | admin+ | archive tool |
| POST | `/tools/{tool_id}/checkout` | admin+ | check out to `assigned_to_id`; decrements on-hand |
| POST | `/tools/{tool_id}/return` | session | return from `assigned_to_id`'s custody; increments on-hand |
| POST | `/tools/{tool_id}/adjust` | admin+ | "Correct Count": set on-hand to an absolute value with a required reason; no custody holder |

`work_order_id`/`work_order_number` on checkout/return are optional and
never required, with no find-or-create behavior (a free-text number is
stored as-is). Every response includes `custody: [{user_id, user_name,
quantity}]`, the tool's current outstanding balances (net > 0 only). Login
usernames are not present in this operational contract.

### Mass Stages

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| POST | `/mass-stages/` | supervisor+ | create planning stage (community + building) |
| GET | `/mass-stages/` | supervisor+ scoped | list stages, optional `status` |
| GET | `/mass-stages/{stage_id}` | supervisor+ | full stage detail (slots + planned items) |
| PATCH | `/mass-stages/{stage_id}` | supervisor+ | rename (community/building) and/or transition status |
| DELETE | `/mass-stages/{stage_id}` | supervisor+ | delete stage; does not reverse dispenses |
| POST | `/mass-stages/{stage_id}/reuse` | supervisor+ | fresh empty planning stage for the same building |
| POST | `/mass-stages/{stage_id}/work-orders` | supervisor+ | add an already-imported work order to the plan (resolve — 404 if unknown — + enforce match) |
| DELETE | `/mass-stages/{stage_id}/work-orders/{slot_id}` | supervisor+ | remove a work order from the plan |
| POST | `/mass-stages/{stage_id}/work-orders/{slot_id}/items` | supervisor+ | add/upsert planned item |
| PATCH | `/mass-stages/{stage_id}/work-orders/{slot_id}/items/{stage_item_id}` | supervisor+ | edit planned quantity |
| DELETE | `/mass-stages/{stage_id}/work-orders/{slot_id}/items/{stage_item_id}` | supervisor+ | remove planned item |
| POST | `/mass-stages/{stage_id}/load` | supervisor+ | load merged item as per-slot dispenses |
| POST | `/mass-stages/{stage_id}/return` | supervisor+ | return unused material silently to stock |

The old `/quick-room`, `/active-rooms`, and per-room assign/edit routes are gone:
the scan gate lists scoped Created/Assigned/In-Progress rows from `/work-orders/`;
assignment/edits live on the work order. Work orders are import-only and the
scan gate does not create them. Selecting In-Progress arms the batch; selecting
Assigned confirms the narrow in-place start action and arms the batch; selecting
Created can navigate to the expanded Work Order card for assignment first.

### Work Orders

List/get/items are open to any authenticated user but **server-scoped**: a
Technician sees/acts on only work orders assigned to them; a Supervisor sees
unassigned work orders, ones routed to them, and ones where they are assigned as
a worker; Admin/Owner see all.
Notes/add-material and the assigned-worker start/complete walkthrough are
Technician+; general operations/labor/material corrections and restore are
Supervisor+; metadata and closing are Admin+. Review additionally requires a
Completed row and a second, unassigned responsible user. Archive accepts every live status. Out-of-scope, closed, or
unknown work orders return 404. **There is no create route** — the CSV import is
the only way in.

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| GET | `/work-orders/` | session scoped | list live Created through Review work orders by scheduled date descending; joinable `status`, `service_type`, `supervisor_id`, `community`, `scheduled_date`, `q` filters plus `limit` |
| GET | `/work-orders/filter-options` | session scoped | distinct service types and routed supervisors from caller-visible live work orders plus stable community choices |
| GET | `/work-orders/legacy/archive` | owner exactly | count currently live legacy work orders (`legacy=true`, `archived_at IS NULL`) before confirmation; returns `{count}` |
| POST | `/work-orders/legacy/archive` | owner exactly | atomically soft-archive every currently live legacy work order and return the actual `{archived}` count |
| POST | `/work-orders/import` | admin+ | preflight a UTF-8 mass CSV with exactly one `WORK ORDER` header, then locked find-or-create; blank/missing task stores a replaceable NetFacilities URL, supervisor fills only while NULL, and archived matches are ignored; **the only path that creates a work order**; returns created/opened/closed/matched/skipped counts; a CSV over **25 MB** returns 413 before the parse (see *Upload size caps*) |
| GET | `/work-orders/export` | admin+ scoped | export `scope=all|archived|<live-status>` as `variant=full` (re-importable operational CSV; accepts the live page's service/supervisor/community/date/number filters) or `variant=client` (unchanged scope-only billing totals + fixed-width receipt) |
| GET | `/work-orders/lookup?number=` | supervisor+ scoped | does this number name a work order, and is it archived? the one read that reports an archived one, so History can offer a restore |
| GET | `/work-orders/{id}` | session scoped | work-order detail + append-only authored/timestamped note log + logged materials + labor totals |
| PATCH | `/work-orders/{id}` | session scoped; field-sensitive | a nonblank note appends a server-stamped/authored log entry at Technician+; supervisor/technicians/general status/entry mode = Supervisor+; imported/legacy metadata = Admin+; Review only from Completed by an unassigned routed Supervisor or Admin+; optional original supervisor precondition returns a named 409 on stale pickup |
| POST | `/work-orders/{id}/start` | session scoped; Technician+ | idempotently move Assigned to In-Progress; no general Technician status-edit permission |
| POST | `/work-orders/{id}/complete` | assigned worker | idempotently move In-Progress to Completed; rejects unassigned callers and grants no general status or Review permission |
| POST | `/work-orders/{id}/hold` | assigned worker | idempotently move In-Progress to On-Hold; rejects unassigned/non-In-Progress callers and grants no general status permission |
| POST | `/work-orders/{id}/resume` | assigned worker | idempotently move On-Hold to In-Progress; rejects unassigned/other-state callers and grants no general status permission |
| POST | `/work-orders/{id}/archive` | admin+ scoped | close a work order from any live status via soft archive (number reserved, lines kept, transactions untouched) |
| POST | `/work-orders/{id}/restore` | supervisor+ scoped | explicit un-archive; the only way to return a closed work order to live views |
| POST | `/work-orders/{id}/items` | Technician+ scoped | log/add a material (mode = work order's entry_mode); a dispense shortage may make expected stock negative and creates a linked recount request |
| PATCH | `/work-orders/{id}/items/{wo_item_id}` | supervisor+ scoped | edit a material's quantity (dispense lines auto-correct stock) |
| PATCH | `/work-orders/{id}/items/{wo_item_id}/billing` | admin+ scoped | set/clear the line's billing override (bill partial / zero / full). Its Admin+ gate is a dependency, so it answers **before** Pydantic: a request that is both malformed and unauthorized returns 403, not 422 (see below) |
| DELETE | `/work-orders/{id}/items/{wo_item_id}` | supervisor+ scoped | remove a material (dispense lines return stock; voids all contributing transactions and resolves their linked requests) |
| POST | `/work-orders/{id}/labor` | supervisor+ scoped | add positive whole-minute labor for an assigned technician |
| PATCH | `/work-orders/{id}/labor/{labor_id}` | supervisor+ scoped | replace actual minutes |
| DELETE | `/work-orders/{id}/labor/{labor_id}` | supervisor+ scoped | remove an entry; status does not rewind |

The `POST /transactions/` body now also accepts `work_order_id` (from a scanned
card); a free-text `work_order_number` from a Supervisor+ is *resolved* to an
already-imported work order, and 404s if there is none (it used to be
find-or-created).

**403-before-422 on the billing route** is the one observable behavior change
C1 made (2026-08-10). Its gate used to be `_can_see_price(user)` in the handler
body, which runs after Pydantic; as a dependency it runs first. So a caller who
is *both* below Admin *and* sending a malformed body now gets 403 where they
got 422. Unreachable from the SPA, which cannot send a malformed body, and no
test asserted 422 — recorded because it is a real change at a permission
boundary, not because anything is expected to notice.

## Frontend Feature Context

Top-level navbar buttons switch SPA sections through `views/nav.js::showPage`
without reloading the document. Every activation of Work Orders, Find Item, or
Mass Stage requests current server data. Work Orders and Mass Stage refresh both
their main lists and their item/user reference lists; Find Item clears prior
results and refreshes only its lightweight search index until the user chooses
Search or Load All. Dynamic authenticated list requests use `cache: "no-store"`.

### Login

Files: `views/auth.js`, `api.js`, `state.js`, `views/nav.js`,
`views/transactions.js`.

Behavior:

- Boot calls `/auth/me`.
- 401 shows login screen.
- Login success stores current user, applies nav visibility, resets any batch,
  and opens that role's landing page (`landingPageForRole` in `views/nav.js`):
  technician -> Transaction, supervisor -> Work Orders, admin/owner -> History.
  A resumed batch overrides the role default and opens Transaction so the
  operator can finish scanning. Unknown roles, or a landing page the role
  cannot reach, fall back to Transaction.
- Any later 401 triggers global return to login.
- Logout tries `/auth/logout`, then locally returns to login even if request
  fails.

### Find/Add Item

Files: `views/items.js`, `views/itemEditor.js`, `views/addBarcode.js`,
`views/notes.js`, `views/correction.js`, `pages/saved-items.html`,
`pages/create-item.html`.

Behavior:

- Add Item is Admin+.
- Find Item list is available to all roles.
- Opening Find Item makes no item request, shows a plain search field without a
  native suggestion popup, and renders no item cards. Typing alone does not
  query or render. Search/Enter calls `/items/?q=...` across the full live
  dataset; Load All Items calls the backward-compatible unfiltered `/items/`
  feed. `/items/search-index` was **deleted in X3** (2026-08-10) — it had no
  caller anywhere and returned every live name and barcode to any signed-in
  user.
- Technician item table is simplified: no actions/created column, quantity and
  location near name.
- Supervisor+ can edit notes.
- Admin+ can edit item details/barcodes, correct count, and archive item.
- Admin/Owner see price/link columns.
- Unknown scan on Find Item offers Admin+ Create Item and Add Barcode shortcuts.

### Scan / Stock

Files: `views/transactions.js`, `views/scan.js`, `pages/transaction.html`,
`views/nav.js`, `api.js`.

Behavior:

- Every role lands here after login.
- Gate requests the scoped live work-order list and renders only Created,
  Assigned, and In-Progress cards. Tapping In-Progress starts the batch on that
  work order (id + number). Tapping Assigned confirms `POST .../start`; Yes
  moves it to In-Progress and opens the scanner without leaving the page, while
  No leaves the gate unchanged. Created still confirms navigation to Work Orders
  so a Supervisor can assign it.
- Supervisor+ sees a compact work-order-number search card above the work-order
  cards. Typing is a debounced live filter through
  `/work-orders/?q=`; it only narrows the scoped ready cards and never creates a
  work order. Selecting a filtered In-Progress card starts the batch; Assigned
  uses the same in-place start confirmation. Stale request
  responses cannot overwrite a newer filter result.
- Technician sees only assigned cards and does not see the number filter.
  Work orders remain import-only; the old quick-add/free-text-start paths are
  gone.
- Each committed scan carries `work_order_id` (+ number) on the transaction.
- Batch starts with quantity `1`.
- Default flow is dispense-only for every role.
- A manual entry panel (search by name/barcode) is hidden until a work order is
  selected, then sits alongside the scanner for every role. Picking a result
  commits it into the active batch through the same `commitScannedItem` path a
  scan uses (same confirmation, same `work_order_id` attach). Supervisor+ can
  reveal an advanced mode that also toggles Add Stock/Take Out and lets an empty
  search browse the full item list.
- Live camera auto-starts only if permission is already granted.
- Scan resolves barcode, asks confirmation, then commits transaction.
- Every successful line has Remove. A Technician can remove only their own
  work-order dispense; Supervisor+ can remove any saved batch line. Removal
  voids the transaction, reverses stock and the aggregate work-order material,
  and resolves a recount request if one was raised.
- When a dispense exceeds recorded on-hand, it still commits, the count may go
  negative, and the normally green line is red with `Please re-count stock`.
  Admin/Owner see the linked request on the User Requests page and can resolve
  or reopen it.
- When the work-order item has no price, the same commit creates or updates one
  deduplicated missing-price request. Admin/Owner can enter Price and Product
  Link together on User Requests; the card leaves the open queue automatically
  only after a price greater than `$0.00` and a product link both exist.
  Work-order totals already use the item's live
  price, so they update immediately.
- Unknown barcode does not offer create-item shortcut in this flow.
- Continuous live scan uses dwell and same-barcode cooldown to prevent double
  commits.

### User Requests

Files: `views/userRequests.js`, `pages/user-requests.html`, `api.js`, backend
user-request router/service/schema/model, and item/work-order services.

Behavior:

- Admin/Owner can switch between the newest-first open and resolved queues.
- Inventory-recount cards show the frozen shortage context and expose manual
  Resolve/Reopen actions.
- An open missing-price card shows the item's current Price and Product Link in
  one form. Its price input has `min="0.01"`; Save rejects zero or negative
  values and requires a valid, nonblank link, sends one item PATCH, and
  disappears from the open queue after the item update atomically resolves it.
- Resolved missing-price cards are retained as read-only audit entries in the
  page. The generic request PATCH still supports reopening them for API clients.

### Mass Stage

Files: `views/massStage.js`, `pages/mass-stage.html`, `api.js`, backend
mass-stage router/service/domain/schema/model.

Behavior:

1. Create stage for community/building.
2. Add work orders (each a unit slot referencing a standalone work order;
   community/building come from the stage, optional unit + technician). The
   number must already have been imported — adding *resolves* the work order
   (404 if unknown; a stage cannot create one), fills its blank
   community/building/unit from the stage, and enforces a building match.
3. Add planned items and quantities per slot.
4. Save stage: `planning -> loading`.
5. Load merged item quantities. Loads split across slots by `sort_order` and
   create real dispense transactions carrying each slot's work order.
6. Return unused material. Returns add stock and update slot tables only.
7. Mark completed.
8. Stage again from completed: a fresh empty planning stage for the same
   community + building (no slots copied).

UI display (community tree):

- the list is a three-tier collapsing tree: Community -> Building -> Unit
- the create row is a Community dropdown (3 seeds + in-use names + "+ New
  community…") plus a Building # input
- each unit shows an "Open work order →" link that navigates to the Work Orders
  page for its work order (`focusWorkOrder` + `showPage`); planned items are
  still edited inline in planning
- completed stages are read-only and terminal

### Work Orders

Files: `views/workOrders.js`, `pages/work-orders.html`, `api.js`, backend
work-order router/service/domain/schema/model.

Behavior:

- Any authenticated role, server-scoped: a Technician sees any work order in
  their plural assignment set; a Supervisor sees the shared unassigned queue
  plus work routed to them; Admin/Owner sees all live rows. Reached via the nav
  button or a Unit click in the Mass Stage tree.
- Admin+ get an "Import work orders" section (file picker → `apiImportWorkOrders`
  → summary of processed/new/updated/closed/routed/skipped counts, then the list
  reloads). The closed count is always shown, including zero, and those rows are
  ignored without mutation. The
  file input accepts `.csv`; the button re-enables and clears after each run.
- The same section contains a hidden-by-default **Re-archive legacy work
  orders...** button revealed only when `getRole() === "owner"`. Clicking it
  fetches the live legacy count and opens the shared modal: zero uses a
  message-only dialog; a positive count asks for confirmation and explains that
  History can restore the rows. Confirmation posts the bulk action, reports the
  actual archived count (which can differ from the preview), refreshes filter
  options, and reloads the Work Orders list.
- **Import-only: there is no "New work order" form.** The CSV import is the only
  way a work order appears here or anywhere else.
- A card body opens on a read-only block of the work order's filled-in fields
  (location, service type, schedule, output-to, vendor contact, symptom/task,
  supervisor, technicians — blank ones are omitted), plus a "Legacy" tag on
  pre-import cards. A symptom/task whose complete value is an HTTP(S) URL renders
  as an escaped external link in a new tab; long URLs wrap within the card.
- Supervisor+ get a nested **Edit details** card beneath the read-only overview.
  It is collapsed by default and expands through its own summary instead of a
  separate button; the read-only block remains visible. For a Supervisor it
  contains only supervisor routing, multi-technician assignment, and status.
  The Supervisor selector lists active Admin and Supervisor accounts.
  The assignment control puts a name search at the top and shows no
  worker catalog until text is entered. Its local, case-insensitive results
  include active Technicians and Supervisors, exclude already selected workers,
  and choosing a result adds it to the
  assigned list beneath the search, and Remove drops it from that draft list.
  Save sends the complete remaining set as replacement `assigned_to_ids`; Cancel
  reloads the persisted detail. Admin/Owner additionally see Location, Service
  Type, Schedule Date, Output To, Vendor Contact, and Symptom/Task. Legacy community/building/
  unit and the work-order number stay read-only. The existing status selector
  offers In-Progress for Created/Assigned rows, making it the explicit
  Supervisor start control as well as the place to roll back or select On-Hold;
  a held row can resume to the appropriate non-Review step. Created/Assigned
  remains worker-assignment-derived. Review is read-only here and retains its existing
  Reopen action. Save details / Cancel persist or discard the draft, re-fetch the
  card, and return Edit details to its default collapsed state.
- Advanced filters cover status, dynamic service type, caller-visible assigned
  supervisor, derived community, exact scheduled date, and the existing
  debounced work-order number search. Every active value is sent in one request
  and combines with AND; Clear filters resets the complete search. Admin+ also
  sees Export filtered CSV in this card; it exports the same uncapped result set.
- For Admin/Owner, a work-order-number search that exactly identifies an
  archived row performs the archive-aware lookup after the live-list search and
  opens the shared modal with `Work Order has been closed.` plus **Restore** and
  **Close**. Close leaves the archive untouched. Restore clears `archived_at`
  through the existing restore endpoint and reloads the same search so the card
  appears. Substring-only matches, live rows, and lower roles do not prompt;
  stale lookup responses are ignored after the search text changes.
- The list is ordered by parsed scheduled date descending and shows only the
  first 10 by default; a "Show all" control drops the cap and "Show recent only"
  restores it. Blank/malformed schedule text sorts last, with creation time as a
  tiebreaker. Any active filter queries the complete matching set.
- Cards are collapsible and their full collapsed background communicates status:
  Created gray, Assigned red, In-Progress yellow, On-Hold orange, Completed blue,
  Review green, with contrasting text. Expanded bodies return to a white form surface. The
  body has a Supervisor+ mode selector and status-appropriate actions. An
  assigned Technician or Supervisor gets one walkthrough button: Set In-Progress
  while Assigned, then Mark Completed while In-Progress, then no Review button.
  Only while In-Progress, a second Place On-Hold button appears beside Mark
  Completed. While On-Hold, those controls are replaced by one Resume
  In-Progress button; it appears in no other state.
  A routed Supervisor who is not assigned, or any unassigned Admin+, sees Send to
  Review on Completed work; it still requires confirmation. An assigned
  Supervisor is deliberately excluded even when also routed, enforcing a second
  set of eyes. Supervisor+ retains Mark Completed for visible In-Progress work
  and Reopen as applicable, while the unchanged Edit details status dropdown
  remains the general start/rollback/On-Hold control. The Review transition
  places the row in final Admin Review. Material/labor activity still advances
  Created/Assigned automatically, and Scan/Stock retains its scoped Assigned
  start action. On-Hold explains that only a supervisor can resume or roll it
  back. The body also has collapsed-by-default nested cards for
  Supervisor+ Edit details, Notes, Materials, and Supervisor+ Labor. Opening
  Notes shows the accumulated plain-text log above an empty new-note textarea.
  Save note rejects blank input, appends a server-generated Central-time/date and
  authenticated full-name prefix, clears the textarea, and closes the card.
  Materials contains the logged rows, empty state, Admin totals, and add-item
  controls; it reopens after add/update/remove or billing refreshes so newly
  rendered data stays visible. Technicians can add items but see existing
  quantities read-only; Supervisor+ may update/remove lines. Labor likewise
  reopens after add/update/remove, and Supervisor+ may manage any assigned
  technician. Admin/Owner additionally receives a confirmed Archive action on
  every live-status card.
- Closing keeps the row, material lines, and transactions, but hides the work
  order from live views. `POST .../archive` requires Admin+ from any live status;
  Admin Review keeps its receipt-aware Review close flow. History can still find transactions by
  number and offers restore for a closed work order.
- Dispense entries move stock and show in History like a Scan/Stock dispense;
  retroactive entries show in History identically but move no stock.
- Each material line shows an Admin/Owner-only charge (`effective billable *
  current price`, plus the `+15%` mark-up): the line is the billing unit, so the
  customer cost lives here, not on the individual History rows (the backend
  redacts the line's `unit_price`/`billable_quantity` below Admin). An inline
  "Edit charge" editor (mirroring History's) bills a partial count or zero per
  line; a `materials_total` (base + mark-up) sums the card.
- Completed/Review work orders remain editable. Supervisor+ can roll Completed
  back through Edit details or use Reopen; rollback clears `completed_at`.

### Admin Review

Files: `views/adminReview.js`, `adminReviewReceipt.js`, `pricingText.js`,
`pages/admin-review.html`, `views/nav.js`, `views/history.js`, and `api.js`.

Behavior:

- Admin/Owner-only SPA page. On activation it requests every live Review work
  order with `apiListWorkOrders({status: "review"})` and renders green cards with
  the work-order number as the title.
- Selecting a card fetches `WorkOrderDetail` and opens one persistent read-only
  receipt textarea. Selecting another card overwrites the receipt; queue reloads,
  Close, and Return to In-Progress leave the current receipt visible.
- The copied receipt contains no work-order-number header. It begins with one
  authoritative material line per work-order item, using
  `billable_quantity ?? quantity`, current line price, and the fixed `+15%`
  material mark-up. A zero billing override remains visible as `$0.00`.
- Every receipt includes `[x] Labor Hours` where `x` is combined billed hours
  (`labor_billed_minutes / 60`, after IMP-006's one-time 30-minute rounding) and
  the right-aligned `labor_total`. Labor receives no additional mark-up. The
  final Total is marked-up materials plus labor.
- `pricingText.js` is shared with History, so each material, labor, and Total
  line uses the same 41-character maximum, sanitization, name truncation, and
  right-aligned amount behavior. The destination still hard-wraps at character
  42 and the textarea uses `wrap="off"`.
- A material with no price renders `NO PRICE`, labels the total incomplete, and
  disables Close while naming the affected items. Return to In-Progress remains
  available so the work order can be corrected.
- Return to In-Progress confirms, then PATCHes status to `in_progress`; Close
  confirms, then calls the shared any-live-status Admin+ archive endpoint. Either
  action removes the work order from this Review queue while preserving the
  receipt text for reference/copying.

### Tools

Files: `views/tools.js`, `views/toolCheckout.js`, `views/toolReturn.js`,
`pages/tools.html`, `pages/create-item.html`, `api.js`, backend tools
router/service/domain/schema/model.

Behavior:

- Add Tool is a second card ("Add Tool") on the Add Item page, below Add
  Item; Admin+ (inherits the page's gate). Barcode + name + quantity only
  -- no location/price/product-link.
- Tools page is reached via its own nav button (any authenticated role).
  Its default sub-view is **Custody**; Inventory and Scan remain secondary
  sub-views.
- Admin/Owner Custody starts with an active-user searchable combobox (up to
  eight matching full names, keyboard Arrow/Enter/Escape support). Selecting a
  user opens a profile card with full name, role, account-created date, active
  status, distinct holding count, and the user's derived tool balances.
  Archived users are excluded. Supervisor/Technician do not receive the user
  list for this page and instead see only a card for the `/auth/me` identity.
- Check-in starts on a holding row. Its fixed-user panel defaults to the full
  outstanding balance and caps the quantity to that balance. Checkout is
  Admin+ only and starts from the selected user's card: search available tools
  by name/barcode or choose "Scan Tool to Check Out," then confirm a fixed
  user/tool and quantity. A scan never commits automatically.
- Inventory columns remain Barcode, Name, On Hand, Checked Out (each custody
  entry as `full name: quantity`, one per line). Admin+ row actions are limited
  to Edit, Correct Count, and Archive; transactional Check Out/Check In actions
  live only on the Custody card.
- Correct Count (`views/toolCorrection.js`) sets the absolute on-hand
  quantity with a required reason -- mirrors Find Item's Correct Count
  exactly, just posting to `POST /tools/{id}/adjust`. This is also how a
  bulk tool's on-hand count is increased ("restocked") -- there is no
  separate stock-in action.
- Direct Scan-sub-nav use remains inventory lookup: it resolves through
  `apiGetToolByBarcode`, switches to Inventory, and filters to the barcode.
  Card-launched scanning carries checkout context, switches back to Custody,
  and opens checkout confirmation. There is no create-from-scan shortcut.
- Both transaction panels retain an optional free-text work-order-number field
  (no find-or-create; stored as-is). Saving reloads only tool data and rerenders
  the selected card; auth reset/logout clears page-local selected-user and scan
  context so custody state cannot leak between sessions.
- No new tool-custody endpoint or database migration was added: the page
  composes the existing `/tools/`, `/tools/{barcode}`, `/users/`, `/auth/me`,
  checkout, and return contracts, and custody remains ledger-derived.

### History

Files: `views/history.js`, `pages/history.html`, `services/history.py`,
`routers/transactions.py`, `schemas/transactions.py`.

Behavior:

- Supervisor+ only.
- Tabs: all, by item, by user.
- Work-order filter overlays all tabs and combines with tab filters. It matches
  on each transaction's own `work_order_number`, independent of the `work_orders`
  table, so a work order's transactions stay searchable here forever — including
  after the work order is archived, and regardless of the fact that work orders
  can no longer be re-created.
- When the typed number *exactly* names an **archived** work order
  (`apiLookupWorkOrder`), a confirm prompt offers to restore it
  (`apiRestoreWorkOrder`) and reports the result under the filter row. Declining
  changes nothing, and a declined number is not re-prompted for the rest of the
  session. This is the undo path for an accidental archive.
- Voided rows are hidden.
- Any row visible in History can be voided by the same role set.
- Admin/Owner Charge column shows base line value and `+15%` marked-up value
  for ad-hoc rows; a work-order-linked row shows no charge (`—`) because that
  material bills through its work-order line on the Work Orders page.
- Billing editor (partial / zero / clear override) appears only on ad-hoc
  stock/dispense rows; work-order rows have no per-row charge to edit.
- Copy table exports all matching rows, not just visible page.
- Export cap: 100 pages * 100 rows.
- Admin/Owner export includes billable qty, unit price, base value, marked-up
  value. Work-order rows suppress `item_price` on screen (charge lives on the
  line), so the export fills each work-order stock/dispense row's per-row pricing
  from the work order's line `unit_price` (fetched via `apiGetWorkOrder`); `adjust`
  corrections stay blank. This is export-only -- the on-screen History charge
  column is unchanged.
- Admin/Owner export also appends a "Work Order Summary" block: one line per
  distinct work order in the export with its authoritative total (`materials_total`,
  override-aware) and that total `+15%`. Sourced from the work order's line totals,
  not by summing rows. Work orders are resolved by `work_order_number` (always
  present on a row) via `apiListWorkOrders`, with the row's `work_order_id` as a
  fast path -- so legacy rows that carry only a number are covered too; the per-row
  fill uses `work_order_id`. Per-row figures can diverge from the summary when a
  line was edited or has a billing override -- the summary is authoritative.

### Users

Files: `views/users.js`, `pages/create-user.html`, `pages/saved-users.html`,
`roles.js`, backend users/auth/roles files.

Behavior:

- Supervisor+ can list users.
- Add User requires first name, last name, username, password, and a subordinate
  role. The Users table is the account-management surface that displays all
  three identity fields.
- Edit Name is available for the signed-in user's own row and manageable
  subordinate rows. The same modal can replace the login username. It writes
  through `PATCH /users/{id}/name`; this is how pre-migration accounts become
  eligible for full-name CSV routing and how mistyped login names are corrected.
- Admin/Owner rows expose Edit Role only for manageable subordinates. The role
  modal offers only roles the actor strictly outranks; a successful change
  revokes the target's sessions so their next login receives the correct UI.
- Create-user dropdown offers only subordinate roles.
- Row reset/archive/restore actions appear only for users the actor outranks.
- Password reset uses the app's modal and requires min length 4.
- The 🗑️ action archives (soft delete): the user can no longer log in but
  their history is kept and they can be restored. Archived rows render
  dimmed with an "(archived)" tag and a Restore action. If the server refuses
  archive because tools remain in custody, a second confirmation can check in
  every held tool and retry the archive atomically.
- The list loads with archived users included so the History "by user"
  filter can still select a departed user.

### Barcode Scanner

Files: `views/scan.js`, `scan/barcode-decoder.js`, `scan/frame-debouncer.js`,
`scan-test.html`, `scan-test.js`, `vendor/zxing-browser-*`, backend barcode
service/router/schema.

Behavior:

- Upload mode posts image bytes to `/barcodes/decode`.
- Live mode uses browser camera and ZXing directly, never `/barcodes/decode`.
- Live scanner requests environment camera, 1280x720 ideal, continuous focus
  best-effort.
- Torch button appears only if track reports torch capability.
- `scan-test.html` is an unauthenticated diagnostic harness, not part of SPA.

## Backend Feature Context

### Auth/Session

Files: `services/auth.py`, `routers/auth.py`, `auth_deps.py`,
`schemas/auth.py`, `models.py`.

Behavior:

- Login validates username/password against scrypt hash.
- Login/account creation/the Users table are the only UI surfaces that display a
  username. The authenticated header, History, work-order surfaces, Mass Stage,
  and Tools use the first + last display name from the response contract.
- `authenticate` rejects archived users (indistinguishable from bad
  credentials); `get_active_session_user` also filters archived users.
- Session token is random URL-safe string stored in `sessions`.
- Cookie is HttpOnly, SameSite=Lax, path `/`, Secure controlled by
  `COOKIE_SECURE`.
- Remembered login sets cookie max-age and server `expires_at` to 12 hours.
- Non-remembered login has no server cap and relies on browser session cookie.
- Expired remembered session is deleted on first request after expiry.

### Items

Files: `services/items.py`, `services/notes.py`, `routers/items.py`,
`schemas/items.py`, `models.py`.

Behavior:

- `list_items` returns live items only, newest-first, no pagination. Its optional
  search is a trimmed, case-insensitive literal substring across name and primary
  barcode; SQL wildcard/escape characters are escaped and a blank search returns
  no rows. Omitting search preserves the full-list contract for other views.
- `get_item_by_barcode` resolves primary or additional barcode for live items.
- `create_item` checks barcode across primary and additional code tables.
- `replace_barcodes` diffs child rows to avoid transient unique conflicts.
- `delete_item` archives by timestamp; hard delete is not normal path.
- `update_item` is a partial update via a `_UNSET` sentinel: only the
  fields the router forwards (`model_dump(exclude_unset=True)`) are
  written, and an explicit `None` clears nullable `price`/`product_link`. It
  locks the item row; once a positive price and a nonblank product link exist, it
  atomically resolves every open `missing_item_price` request for that item.
- `_item_response` flattens additional barcode objects to `list[str]` and
  redacts price/link below admin.

### Transactions/Billing/History

Files: `domain/quantity.py`, `domain/billing.py`, `services/transactions.py`,
`services/history.py`, `routers/transactions.py`, `schemas/transactions.py`.

Behavior:

- `apply_transaction` locks the item row and inserts the stock/dispense with
  `unit_price` snapshotted from the locked item. A short dispense is allowed to
  make the expected count negative and atomically stages an `inventory_recount`
  User Request; its response carries `recount_required` and the authoritative
  post-write `item_quantity` for the red scanner line.
- Its shared work-order line attachment also creates or extends the item's
  missing-price request when the locked item has a NULL or non-positive price.
  Work Orders direct
  adds and Mass Stage loads use the same attachment path.
- `apply_correction` locks item row, computes signed delta, inserts `adjust`
  (no `unit_price` snapshot).
- `void_transaction` locks transaction row then item row, enforces the
  Technician-own-work-order-dispense exception below Supervisor, reverses the
  effect, and resolves a linked recount request.
- `set_billable_quantity` validates override and updates row only.
- `list_history` joins transactions/items/users, filters voided rows, paginates.
- History cost/billing fields are populated only when router passes
  `include_price=True` for Admin/Owner; `item_price` is the row's frozen
  `unit_price` snapshot, falling back to the live `Item.price` only when the
  snapshot is NULL or 0 (so a price edit leaves real recorded prices intact
  but flows onto previously-free rows). A work-order-linked row
  (`work_order_id` set) is the exception: `item_price`/`billable_quantity` are
  forced NULL because that material bills through its work-order line, not the
  ledger row (avoids double-billing and the signed-`adjust` negative charge).

### Work Orders

Files: `domain/work_orders.py`, `services/work_orders.py`,
`routers/work_orders.py`, `schemas/work_orders.py`, `models.py`.

Behavior:

- `get_or_create_work_order` resolves a number (case-insensitive + trimmed) to
  the one row, creating it if new: fills blank attributes on a live match,
  returns an archived match untouched for the importer to count/ignore, and
  validates the assignee is an active Technician or Supervisor. **Reached only from the CSV
  import** — it is the single creation path in the system. Every new row starts
  Created; supervisor-name routing affects `supervisor_id`/visibility, not status.
- `resolve_work_order` is what every other surface (the free-text transaction
  gate, Mass Stage) uses: same fill-blanks merge, but a number that names nothing
  — or names an archived work order — raises `WorkOrderNotFoundError` (404) with a
  message saying which. Work orders are import-only, so a reference cannot create.
- `lookup_work_order` returns the scoped row *including an archived one* (the one
  read that sees through the archive); `restore_work_order` clears `archived_at`.
  Together they back History's archive prompt and Admin+'s exact-number Work
  Orders search prompt, which are the undo paths for archive now that nothing can
  re-create a work order.
- `list_work_orders` is scoped (technician/supervisor/admin), excludes archived,
  composes every advanced predicate with AND, filters scheduled date by parsed
  calendar day, and sorts scheduled date descending before applying `limit`.
- `update_work_order` checks field permissions before writing: notes require an
  in-scope Technician+; status/entry mode/supervisor/technicians require
  Supervisor+; imported and legacy metadata require Admin+. A nonblank note is
  appended under the existing row lock through the pure domain formatter, which
  adds Central time, `MMDDYY`, and `user.full_name`; a null leaves the log
  unchanged. Other supplied fields retain overwrite semantics. `assigned_to_ids`
  replaces the normalized assignment set while
  maintaining the singular compatibility mirror. Setting/clearing the plural
  set reconciles Created/Assigned;
  an explicit rollback to either pre-work value is normalized again after the
  assignment edit, so the pair cannot contradict technician presence.
  Supervisor routing is independent. A Review request is accepted only from
  Completed and only when the caller is an Admin+ or the routed Supervisor and
  is not one of the assigned workers. Completed and Review retain `completed_at`,
  while On-Hold/rollback/reopen clears it. A number collision raises 400.
- `start_work_order` is a separate idempotent Assigned -> In-Progress action for
  a visible Technician+ caller. It is intentionally narrower than the
  Supervisor+ general status patch.
- `complete_work_order` is the matching idempotent In-Progress -> Completed
  action, but requires the caller's ID in the current plural worker assignment.
  It cannot pause, roll back, or send the row to Review.
- `hold_work_order` is the separate idempotent In-Progress -> On-Hold action for
  a currently assigned worker. It grants no general status authority.
- `resume_work_order` is its assignment-checked idempotent inverse, On-Hold ->
  In-Progress, and likewise grants no other status authority.
- `archive_work_order` requires Admin+ in the service and sets `archived_at` from
  any live status. This is the stored Closed state.
- `count_live_legacy_work_orders` and `archive_live_legacy_work_orders` both
  require Owner exactly in the service. They select only `legacy=true` live
  rows; the archive function performs one bulk `UPDATE`, commits atomically, and
  returns the affected-row count.
- `add_work_order_item` permits an in-scope Technician or Supervisor to add a
  dispense-mode material even when recorded stock is insufficient. It locks the
  item row, permits the expected count to become negative, writes the
  `dispense` transaction and matching line, and creates a linked
  `inventory_recount` request in the same commit. The response carries the live
  `item_quantity`, allowing the Work Orders card to show the red
  `Please re-count stock` message. Retroactive mode remains stock-neutral. The
  shared line-attachment path advances a pre-work row to In-Progress and leaves
  On-Hold unchanged.
  `update_work_order_item` (Supervisor+) corrects stock by the delta
  and appends one reconciling `adjust` (the original scan rows stay intact -- it
  does NOT rewrite them); it clears a now-too-large `billable_quantity` override.
  `delete_work_order_item` (Supervisor+) returns the line's net units, voids its
  whole contributing transaction set, and resolves requests linked to those
  source transactions.
- `set_work_order_item_billable` sets/clears a line's `billable_quantity`
  override (validated by `domain.billing.validate_billable_value`); it never
  touches stock. The router builds `materials_total` (sum of
  `effective_billable * unit_price`) and per-line `unit_price`/`billable_quantity`
  for Admin/Owner, redacted below.
- `add_work_order_labor` requires Supervisor+ and a current technician
  assignment, stores actual whole minutes, and applies the shared
  activity-derived status transition. Update/delete are Supervisor+ as well.
  Response totals use `billed_labor_minutes` and `labor_charge`:
  sum first, round upward once to 30 minutes, then multiply by `$62.50/hour`.

### Tools

Files: `domain/tools.py`, `domain/quantity.py` (reused), `services/tools.py`,
`routers/tools.py`, `schemas/tools.py`, `models.py`.

Behavior:

- `create_tool` / `update_tool` check barcode uniqueness against **live**
  tools only (`services.tools._ensure_barcode_free`) -- no archived-
  conflict/override flow like items; an archived tool's barcode is simply
  free.
- `delete_tool` 🔒 locks the live `Tool` row and refuses to archive it while
  `tool_custody` reports any outstanding balance
  (`ToolHasOutstandingCustodyError`).
- `checkout_tool` first 🔒 locks and validates an active `User` target. An
  unknown or archived target raises `UserNotFoundError` before the tool is
  mutated or a ledger row is appended. `checkout_tool` / `return_tool` also
  🔒 lock the `Tool` row (mirrors
  `services.transactions.apply_transaction`) and reuse
  `domain.quantity.apply_delta` directly: checkout calls it with
  `"dispense"`, return with `"stock"`. No new arithmetic exists for tools.
- `return_tool` computes the target user's current outstanding balance
  (`_outstanding_for_user`, the same aggregate query as `tool_custody`
  scoped to one user) and calls `domain.tools.validate_return` before
  applying the quantity change, raising `ToolReturnExceedsCheckedOutError`
  if the return would exceed it.
- `adjust_tool_quantity` ("Correct Count") mirrors
  `services.transactions.apply_correction`: 🔒 lock the `Tool` row, compute
  `delta = new_quantity - current`, `NoChangeError` if 0, apply via
  `domain.quantity.apply_delta(qty, "adjust", delta)`, insert an `adjust`
  row with `assigned_to_id=None` and the required `reason`. This is also
  the only way to increase a bulk tool's on-hand count (no separate
  stock-in endpoint).
- `tool_custody` is the shared aggregate (`SUM` grouped by
  `assigned_to_id`, `HAVING net > 0`, **filtered to
  `transaction_type IN ('checkout', 'return')`**) both the router (for
  display) and `return_tool` (for the cap) use -- custody is always
  derived from `tool_transactions`, never stored, and an `adjust` row is
  explicitly excluded so a correction never corrupts a custody balance.
- `user_custody(assigned_to_id)` is the inverse aggregate across tools. It
  returns tool id/name/barcode/positive quantity rows without filtering
  archived tools, so legacy inconsistent rows cannot bypass the guard. It is
  used only by `services.users.archive_user` to reject archiving a user who
  still holds a tool (`UserHasCheckedOutToolsError`); the frontend card instead
  inverts each live `ToolResponse.custody` list.
- `_tool_response` (router) sets `custody` explicitly from `tool_custody`,
  the same pattern `routers/items.py::_item_response` uses for
  `barcodes`.

### Mass Staging

Files: `domain/mass_staging.py`, `services/mass_staging.py`,
`routers/mass_stages.py`, `schemas/mass_stages.py`, `models.py`.

Behavior:

- `create_stage` enforces one active stage per (community, building).
- `add_work_order_to_stage` enforce-matches the work order's community/building
  to the stage, *resolves* it via `services.work_orders.resolve_work_order`
  (404 if that number was never imported — a stage cannot create a work order),
  and links a slot.
- `list_stages` is scoped for supervisor vs admin/owner; `get_stage` is not
  additionally scoped beyond Supervisor+.
- `reuse_stage` requires a completed source and makes a fresh empty stage for
  the same community + building.
- `add_item` upserts planned quantity by slot/item.
- `load_item` locks the item, allocates across slot plans, writes dispense rows
  carrying each slot's `work_order_id` + number, increments loaded quantities.
- `return_item` locks the item, reverse-allocates returns, increments returned
  quantities, adds stock without transaction rows.

## Migration History

Alembic head: `faa2c4e6b8d0`.

| Revision | Meaning |
| --- | --- |
| `4f0a7ce7d1ac` | initial users/items/transactions |
| `9a2c5d4e8b11` | item JSONB attributes |
| `4c1e7f3a9b22` | item location, attributes -> notes |
| `a1b2c3d4e5f6` | auth password hashes, roles, sessions |
| `b2d3e4f5a6c7` | restrict transaction FKs |
| `c3d4e5f6a7b8` | transaction reason |
| `d4e5f6a7b8c9` | transaction void metadata |
| `e5f67b8c9d0` | item price/product link |
| `f6b8c0d2e4a1` | item archived_at |
| `a7c9e1f3b5d2` | additional item barcodes |
| `b1f3d5a7c9e2` | mass-stage tables |
| `c7e9a1b3d5f8` | session expires_at remember-me |
| `c2e4f6a8d0b1` | room creator/assignee |
| `e7f9a1c3b5d2` | transaction billable_quantity |
| `d8b2f4a6c1e3` | transaction unit_price (historical price snapshot) |
| `f1a3c5e7b9d4` | user archived_at (soft delete) |
| `b3d5f7a9c1e4` | standalone `work_orders` (number identity) + `work_order_items` + transaction `affects_stock`/`work_order_id` + `mass_stages.community` + `mass_stage_work_orders` slots (replaces rooms) |
| `c4e6a8b0d2f5` | backfill `work_order_items` lines from existing linked dispenses |
| `a9d1f3b7c2e8` | `work_order_items.billable_quantity` (per-line billing override) |
| `d2f4b6a8c0e3` | `tools` + `tool_transactions` tables (tool custody tracking) |
| `e4a6c8b0d2f7` | `tool_transactions.reason` + nullable `assigned_to_id` (Correct Count / `adjust`) |
| `f2a4c6b8d0e1` | work-order CSV import fields + supervisor routing + legacy backfill |
| `f3b5d7a9c1e2` | nullable user first/last names for legacy-safe display and CSV routing |
| `f4c6e8a0b2d3` | work-order Created/Assigned default and five-state live lifecycle; existing statuses preserved |
| `f5d7f9b1c3e4` | reconcile Created/Assigned pre-work rows from technician assignment instead of supervisor routing |
| `f6e8a0b2d4f5` | nullable `work_orders.notes` text storage (now used as an append-only authored/timestamped log without another migration); On-Hold uses the existing application-validated text status column |
| `f7a9b1c3d5e6` | plural `work_order_technicians` assignments (backfilled from `assigned_to_id`) + per-technician `work_order_labor` minute entries |
| `f8a0c2e4b6d8` | durable generic `user_requests` queue; first producer is a linked Scan / Stock inventory-recount exception |
| `f9b1d3e5a7c9` | backfill one open missing-price/link request per unpriced item already present on a live work order |
| `faa2c4e6b8d0` | backfill missing-price/link requests for live work-order items whose recorded price is `$0.00` or otherwise non-positive; tag seeded rows with `details.migration_source` so downgrade removes only this migration's inserts |

## Test Map

Run all tests with the repo venv:

```powershell
backend\venv\Scripts\python.exe -m pytest backend\tests
```

The system Python may not have dependencies. The repo venv was verified to run
the suite.

Database-backed tests:

- use `backend/tests/conftest.py`
- require reachable Postgres through `DATABASE_URL`
- skip if DB is unreachable
- let services call `commit()` inside a rolled-back outer transaction

Coverage map:

| Test file | Covers |
| --- | --- |
| `test_auth_password.py` | scrypt password hashing/checking |
| `test_auth_session_lifetime.py` | remembered/non-remembered session lifecycle |
| `test_auth_profile_schema.py` | `/auth/me` response includes first/last/full name plus profile timestamps |
| `test_user_names.py` | required trimmed names, neutral legacy display, name persistence, and self/manager edit authorization |
| `test_user_role_edit.py` | Admin/Owner-only subordinate role changes, rank restrictions, session revocation, and UI/API contracts |
| `test_user_archive.py` | user archive blocks login, revokes sessions, list scoping, refuses archive with outstanding custody, and force-returns held tools atomically |
| `test_item_update_partial.py` | partial item PATCH + clear price/link to null |
| `test_history_price_snapshot.py` | frozen `unit_price` snapshot; non-zero rows unchanged by price edits; snapshot 0 / NULL falls back to live price |
| `test_roles.py` | role hierarchy and transaction/user-management rules |
| `test_route_role_gates.py` | important route minimum-role gates |
| `test_user_requests.py` | DB-backed recount lifecycle; Technician own-scan removal boundaries; deduplicated missing-price requests across work orders; NULL/`$0.00` price detection; positive-price+link automatic resolution; simultaneous recount + missing-price creation; Admin resolve/reopen lifecycle |
| `test_barcodes.py` | backend image decode and supported formats |
| `test_item_barcodes.py` | additional barcode uniqueness/lookup/update |
| `test_archived_barcode_reuse.py` | reusing a barcode held by an archived item (with confirmation) |
| `test_item_search.py` | Find Item literal name/barcode search, blank-query guard, archived exclusion, lightweight index projection, and unchanged unfiltered list |
| `test_item_price_gating.py` | item price/link server redaction |
| `test_billing_validation.py` | pure billable quantity rules (per-transaction `validate_billable_quantity` + type-agnostic `validate_billable_value` for lines) |
| `test_history_wo_filter.py` | work-order history filter escaping/combination |
| `test_quantity_reverse.py` | stock delta reversal for voids |
| `test_mass_staging.py` | pure mass-stage allocation/lifecycle rules |
| `test_mass_stages_api.py` | schemas, route gates, response builders |
| `test_mass_staging_load.py` | DB-backed slot load/return, add-work-order enforce-match + refusal of an unimported number, Technician/Supervisor worker assignment, reuse |
| `test_work_orders_domain.py` | pure number normalization, six live statuses including stable On-Hold, community-filter vocabulary/validation, plural worker-derived Created/Assigned state, activity-derived In-Progress, authored/timestamped note-log formatting, combined labor rounding/charge, fill-blanks, Technician/Supervisor worker visibility scope |
| `test_work_orders_service.py` | DB-backed find-or-create, resolve-only attach, plural Technician/Supervisor assignment/scope, Admin/Supervisor routing targets, assigned-worker start/completion/On-Hold/resume actions, Completed-only two-person Review handoff, Supervisor+-only per-worker labor writes, lifecycle/status/append-only authored notes/archive/materials, Technician/Supervisor zero-stock add with recount creation and Supervisor removal resolution, Owner-only live-legacy preview/re-archive selection, AND-composed advanced filters, community aliases/multi-membership/Academics fallback, scoped filter options, and list cap |
| `test_work_order_import.py` | CSV parsing/import, required-number-header and UTF-8 preflight, blank/missing-task NetFacilities fallback, generated-to-real replacement, duplicate-row precedence, manual-task preservation, full-name Admin/Supervisor routing independent of Created status, unmatched/ambiguous/archived/ineligible-role fallback, idempotence, closed-row count/no-mutation, and Admin gate |
| `test_work_order_name_responses.py` | work-order response exposes plural operational names, rounded labor detail/totals, and the note-log text while omitting login usernames |
| `test_work_order_line_sync.py` | line stays in sync across every stock-out path (scan/scan-and-go/load), accumulate, void walk-back, orphan self-heal |
| `test_work_order_billing.py` | line is the billing unit: work-order rows carry no per-row History charge (incl. the signed line-edit `adjust`); ad-hoc rows still billed; per-line override drives charge + `materials_total`, clears when quantity drops below it, redacts below Admin; history row exposes `work_order_id` |
| `test_work_order_export.py` | Admin+ scoped full/client CSV exports, joined operational filters (including date), unchanged client scope behavior, import-header compatibility including generated-task round-trip, billing totals, and receipt cells |
| `test_receipt.py` | backend fixed-width receipt output matches the frontend contract for markup, truncation, quantities, missing prices, and labor rounding |
| `test_tools_domain.py` | pure `domain.tools.validate_return` outstanding-balance cap |
| `test_tools_service.py` | DB-backed: create/duplicate-live-barcode, archived-barcode reuse, checkout/return round-trip incl. `apply_delta` reuse, active-target validation without stock/ledger mutation, checkout overdraft (`NegativeQuantityError`), return-beyond-outstanding (`ToolReturnExceedsCheckedOutError`), per-tool and per-user custody aggregates, multi-user custody split, archive guard until full return, Correct Count increase/decrease/no-op (`NoChangeError`), and the regression that an `adjust` row never enters a custody balance |

No frontend test harness exists. For UI behavior, run backend tests plus manual
browser checks for changed pages.

## Known Gaps

Do not "fix" these accidentally unless the task asks for it.

- Notes saves replace the entire notes object; no partial merge.
- Create Item UI sends blank price as `0`.
- Mass-stage unused returns intentionally do not create transaction rows.
- Direct mass-stage detail/mutation routes are Supervisor+ gated but not
  creator/assignee scoped.
- Completed mass stages cannot be reopened.
- Stage deletion does not reverse load transactions already written.
- Frontend has no bundler/type checker; ID and module contract drift is manual.
- Editing a dispense-mode work-order line auto-corrects stock by the delta and
  appends one reconciling `adjust` transaction (signed stock delta; the original
  scan rows stay intact). That `adjust` is an inventory record only -- it is not
  billed, because work-order materials bill off the line total, not per-row (see
  Work orders invariants). Scoped to `work_order_items`-originated rows.
- The `b3d5f7a9c1e4` migration is a clean rebuild: it WIPES all prior
  mass-stage/work-order data (stages, slots, planned items, logged materials).
  Inventory `items` and historical `transactions` are preserved (old txns keep
  their `work_order_number` string with `work_order_id` NULL).
- Work-order numbers are a single global namespace, unique case-insensitively;
  there is no per-community/building number scoping.
- Work-order CSV import accepts the real header row first or Excel's optional
  UTF-8 BOM + `sep=,` dialect-hint preamble. Only that leading hint is ignored;
  the following row must contain exactly one `WORK ORDER` header. Other vendor
  columns remain optional; a missing `SYMPTOM/TASK` column uses the task fallback.
  Invalid UTF-8, an empty file, a wrong delimiter, or an absent/duplicate number
  header returns HTTP 400 before any work-order row is written. CSV records are
  materialized before row-level commits so parser errors also fail in preflight.
- A free-text work-order number on a transaction is *resolved* (never created,
  since work orders are import-only) and only for Supervisor+; a technician's
  scan must carry a `work_order_id` (from a card).
- Deferred work-order attributes not yet built: `priority`, `due_date`,
  `external_ref`/`source` (for future real-world WO integration).
- Tools: no void/undo for a checkout or return -- mis-clicks are not
  reversible (unlike `transactions.voided_at`).
- Tools: no cross-namespace barcode uniqueness check against
  `items.barcode` -- a tool and an item could theoretically share the same
  barcode string with no error (low risk, scanned on different pages).
- Tools: no dedicated history/ledger page -- `tool_transactions` rows are
  the audit trail, but only the current derived custody balance is
  exposed via the API, not the full event log.
- Tools: any authenticated user may submit a return for any
  `assigned_to_id` on any tool (no self-scope restriction) -- matches the
  confirmed "any role can return" rule, but means a technician could
  technically check in a tool on someone else's behalf.
- Password minimum is 4 characters, below NIST 800-63B rev 4's floor of 8.
  Raising it invalidates existing passwords, so it is a deliberate deferral
  rather than an oversight.
- The wider per-IP login throttle layer ships **disabled**
  (`LOGIN_THROTTLE_PER_IP`, default false). Enabling it before confirming that
  distinct client IPs actually reach the app would throttle the whole crew as a
  single client. `entrypoint.sh` passes uvicorn `--proxy-headers
  --forwarded-allow-ips='*'` so `request.client` is the real caller behind
  Render's proxy; that setting is safe only because the container is
  unreachable except through that proxy.
- A throttled login is refused even when the password is correct. Intended --
  otherwise the throttle would not stop a brute-force that guesses right -- but
  it means a user who mistypes six times waits out the (5-second) window.
- `login_attempts` is not an audit trail: rows are deleted on successful login
  and swept after 24h, so it cannot answer "who tried to get in last week".
  Pairs naturally with N1 (structured logging) if that is ever wanted.

## Documentation Policy

Keep this file optimized for technical execution:

- Prefer tables and routing maps over narrative.
- Keep source-of-truth statements tied to actual files.
- Document current behavior, not intended future behavior.
- Put implementation limitations in `Known Gaps`.
- Avoid reintroducing separate durable plan/spec/reference docs unless there is
  a temporary need and a cleanup date.
