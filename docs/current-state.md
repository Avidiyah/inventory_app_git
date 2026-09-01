# Inventory App Current State

Last reviewed: 2026-08-31 · Soft word budget: 16,500 (CLAUDE.md → Documentation
conventions)

Contracts and invariants — **the authority**; enough current-state context to
make changes without rereading the repository. `docs/endpoint-map.md` owns the
endpoint trace, request/response contracts, and error catalog;
`docs/open-work.md` is the only backlog.

For implementation work: read `Fast Orientation`, `Architecture Rules`, and
`Hard Invariants`; pick files via `Task Routing Map`; run the focused tests in
`Test Map`; update this file when shipped behavior, schema, deployment, or
known gaps change. For review/debugging: `Data Model` + `Known Gaps` identify
the contract and the intentional limitations.

If this file conflicts with code, trust the code and update this file as part
of the change. Alembic head is **`a2c4e6b8d0f1`** (34 revisions). Operation
and test counts are volatile — verify via `app.openapi()` and
`pytest --collect-only` rather than trusting any quoted number.

## Fast Orientation

The app is a self-hosted inventory and work-order staging system for physical
materials tracked by barcode.

Runtime shape:

- FastAPI API and static SPA in one process.
- PostgreSQL persistence through SQLAlchemy and Alembic.
- Static no-build frontend under `backend/static`.
- Barcode upload decoding through backend `pyzbar`.
- Live camera scanning through vendored `@zxing/browser`.
- One same-origin `/ws` WebSocket per authenticated browser for cache
  invalidation only; REST remains the source of truth.
- Read-only NetFacilities work-order enrichment through each user's own Steel
  cloud browser session, Admin-gated and disabled by default.
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
  TechFM OA and above search active users and check out available tools by search or
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
| Low stock alerts / page | `domain/low_stock.py`, `services/low_stock.py`, `routers/_low_stock.py`, `services/items.py`, `routers/items.py`, `domain/notifications.py`, `domain/realtime.py`, `static/views/lowStock.js`, `static/pages/low-stock.html` | `test_low_stock_domain.py`, `test_low_stock_buffer.py`, `test_low_stock_triggers.py`, `test_items_low_stock.py`, `test_low_stock_shell.py` |
| Item notes | `domain/notes_validation.py`, `services/notes.py`, `schemas/items.py`, `routers/items.py`, `static/views/notes.js` | add/extend focused tests if behavior changes |
| Alternate barcodes | `models.py`, `services/items.py`, `schemas/items.py`, `routers/items.py`, `static/views/itemEditor.js`, `static/views/addBarcode.js` | `test_item_barcodes.py` |
| Stock/dispense/correction/void | `domain/quantity.py`, `services/transactions.py`, `routers/transactions.py`, `schemas/transactions.py`, `static/views/transactions.js`, `static/views/correction.js` | `test_quantity_reverse.py`, `test_user_requests.py`, route-gate tests |
| User Requests / operational exceptions | `models.py`, `services/user_requests.py`, `routers/user_requests.py`, `schemas/user_requests.py`, `services/items.py`, `services/transactions.py`, `services/work_orders.py`, `static/views/userRequests.js`, `static/views/userRequestCards.js`, `static/views/itemRequest.js`, `static/pages/user-requests.html` | `test_user_requests.py`, `test_item_requests.py`, `test_route_role_gates.py` |
| Billing/charge override | `domain/billing.py`, `services/transactions.py`, `services/work_orders.py`, `services/history.py`, `routers/transactions.py`, `routers/work_orders.py`, `static/pricingText.js`, `static/adminReviewReceipt.js`, `static/views/history.js`, `static/views/workOrders.js`, `static/views/adminReview.js` | `test_billing_validation.py`, `test_work_order_billing.py`, `test_history_price_snapshot.py`, `test_item_price_gating.py` |
| History filters/export | `services/history.py`, `routers/transactions.py`, `schemas/transactions.py`, `static/views/history.js`, `static/api.js` | `test_history_wo_filter.py` |
| Barcode upload decode | `services/barcodes.py`, `routers/barcodes.py`, `schemas/barcodes.py`, `static/views/scan.js`, `static/api.js` | `test_barcodes.py` |
| Live camera scan | `static/scan/barcode-decoder.js`, `static/scan/frame-debouncer.js`, `static/views/scan.js`, `static/scan-test.html`, `static/scan-test.js` | manual browser/device check; unit tests cover backend decode only |
| Scan-and-go work-order batch | `static/views/transactions.js`, `static/views/scan.js`, `routers/transactions.py`, `services/transactions.py`, `static/pages/transaction.html` | transaction/domain tests plus manual UI check |
| Mass staging API/domain | `domain/mass_staging.py`, `services/mass_staging.py`, `routers/mass_stages.py`, `schemas/mass_stages.py`, `models.py` | `test_mass_staging.py`, `test_mass_staging_load.py`, `test_mass_stages_api.py` |
| Mass staging UI (community tree) | `static/views/massStage.js`, `static/pages/mass-stage.html`, `static/api.js`, then backend mass-stage files | mass-stage tests plus manual UI check |
| Work Orders API/domain | `domain/work_orders.py`, `services/work_orders.py`, `routers/work_orders.py`, `schemas/work_orders.py`, `models.py` | `test_work_orders_domain.py`, `test_work_orders_service.py`, `test_work_order_line_sync.py`, `test_work_order_billing.py`, `test_route_role_gates.py` |
| Work Orders UI | `static/views/workOrders.js`, `static/pages/work-orders.html`, `static/api.js`, then backend work-order files | work-order tests plus manual UI check |
| User Hub Graphs | `domain/hub.py`, `domain/work_orders.py`, `services/hub.py`, `schemas/hub.py`, `routers/hub.py`, `static/views/userHub.js`, `static/views/hubGraphs.js`, `static/views/workOrders.js`, `static/pages/user-hub.html`, `static/styles.css`, `static/tips.js`, `static/api.js` | `test_hub_graphs_domain.py`, hub service/router/gate/realtime tests; manual role/realtime checks. Aggregation semantics: endpoint-map → User Hub reads |
| User Hub Report (Admin daily report) | `services/work_order_report.py`, `services/work_orders.py` (`export_row`, `work_order_totals`), `schemas/hub.py`, `routers/hub.py`, `static/views/userHub.js`, `static/views/hubReport.js`, `static/views/workOrders.js` (`openWorkOrdersByNumberSearch`), `static/pages/user-hub.html`, `static/styles.css`, `static/api.js` | `test_work_order_report.py`, hub router + role-gate tests; manual role/click checks. **Admin-only** (the app's only Admin-floored routes, recorded in `test_route_role_gates.py`); a live view, not an archival record (`N-WO-STATUS-EVENTS`); contract in endpoint-map → `HubReportResponse` |
| NetFacilities enrichment | `integrations/netfacilities/`, `services/netfacilities.py`, `services/netfacilities_cloud_auth.py`, `services/netfacilities_cloud_crypto.py`, `services/netfacilities_jobs.py`, `routers/netfacilities.py`, `schemas/netfacilities.py`, `lifespan.py`, Work Orders import UI, priority migration/model/response plumbing | `test_netfacilities_*.py`; behavior under API Surface → NetFacilities |
| Admin Review / fixed-width receipt | `static/views/adminReview.js`, `static/adminReviewReceipt.js`, `static/pricingText.js`, `static/pages/admin-review.html`, `static/views/history.js`, `static/views/nav.js`, `static/api.js` | work-order billing/role tests, pure receipt assertions, served DOM/resource check, manual UI check |
| Real-time transport / invalidation | `domain/realtime.py`, `services/realtime.py`, `services/realtime_limits.py`, `routers/realtime.py`, `static/realtime.js`, `static/views/auth.js`, `static/views/nav.js`, emit-capable resource routers, `logging_config.py` | `test_realtime_*.py`, `test_logging.py`, all-JavaScript syntax check, manual browser check |
| Tools API/domain/service (custody) | `domain/tools.py`, `domain/quantity.py` (reused), `services/tools.py`, `routers/tools.py`, `schemas/tools.py`, `models.py` | `test_tools_domain.py`, `test_tools_service.py`, `test_route_role_gates.py` |
| Tools UI (Add Tool tab + Tools page) | `static/views/tools.js`, `static/views/toolCheckout.js`, `static/views/toolReturn.js`, `static/pages/tools.html`, `static/pages/create-item.html`, `static/api.js` | manual UI check (no frontend test harness) |
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
backend/app/integrations/netfacilities/*.py NetFacilities config/contracts/validation, Steel cloud adapter + concrete read-only boundary
backend/app/services/netfacilities_cloud_auth.py per-user cloud sign-in ceremony (start/poll/cancel), one row per user
backend/app/services/netfacilities_cloud_crypto.py Fernet encrypt/decrypt for a stored session
backend/app/services/netfacilities_jobs.py serialized cloud-session enrichment job coordinator
backend/app/routers/netfacilities.py Admin-only cloud sign-in/capability/start/poll routes
backend/app/services/netfacilities.py enrichment pass over live work-order candidates
backend/app/domain/realtime.py   pure envelope/audience rules + every policy constant
backend/app/services/realtime.py in-process connection registry, per-user cap, dispatch
backend/app/services/realtime_limits.py handshake-attempt and inbound-frame rate limits
backend/app/routers/realtime.py  the `/ws` handshake; NO app middleware runs here
backend/app/domain/push.py       pure Web Push policy: response classification + endpoint allowlist
backend/app/services/push.py     VAPID config, pywebpush send, subscription store, dead-row cleanup
backend/app/routers/push.py      config/subscribe/unsubscribe (any authenticated) + Owner-only test send
backend/app/domain/notifications.py  pure notification policy: recipient rules, actor suppression, lock-screen text
backend/app/services/notifications.py  resolves recipients against the DB, hands delivery to a background task
backend/app/logging_config.py    per-request id, JSON formatter, request context
backend/app/lifespan.py          composed realtime + NetFacilities task shutdown
backend/alembic/versions/*.py    migrations
backend/scripts/create_owner.py  owner bootstrap
backend/scripts/import_local_data.ps1 local data import helper
backend/scripts/generate_netfacilities_cloud_encryption_key.py one-time Fernet key generator
backend/scripts/generate_vapid_keys.py VAPID keypair generator; run once per environment
```

Frontend:

```text
backend/static/main.js           frontend composition root
backend/static/api.js            fetch wrappers for every backend route
backend/static/state.js          shared client state
backend/static/roles.js          frontend mirror of role hierarchy + labels
backend/static/format.js         display/error/safe-url helpers
backend/static/dom.js            DOM helpers and confirm dialog
backend/static/realtime.js       `/ws` transport + backoff; no DOM/view dependency
backend/static/service-worker.js push + notificationclick; served from ROOT, not /static (scope)
backend/static/manifest.json     PWA manifest; without it iOS offers no Home-Screen install
backend/static/views/push.js     opt-in button, iOS install instructions, Owner test trigger
backend/static/pricingText.js    shared price/redaction copy
backend/static/adminReviewReceipt.js frontend half of the 41-char receipt contract
backend/static/views/*.js        page/view modules
backend/static/views/workOrders.js Work Orders page view
backend/static/views/tools.js    Tools page (list/search/scan) + Add Tool form binding
backend/static/views/toolCheckout.js Tool checkout sub-flow (TechFM OA+)
backend/static/views/toolReturn.js Tool return sub-flow (any role)
backend/static/views/userRequests.js TechFM OA and above request queue
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
backend/tests/test_netfacilities_*.py
backend/tests/test_realtime_*.py
backend/tests/test_rate_limit*.py
backend/tests/test_login_throttle*.py
backend/tests/test_list_*.py
backend/tests/test_push_domain.py
backend/tests/test_push_subscriptions.py
backend/tests/test_vapid_keys.py
backend/tests/conftest.py
```

The `Test Map` section below carries the full per-file coverage table; this list
is a routing aid, not an inventory.

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
| NetFacilities integration | Playwright 1.62.0, Beautiful Soup 4.15.0 (runtime requirements; installed Chrome is used for local interactive sign-in and bundled Chromium performs isolated hosted document reads) |


Deployment:

- Docker image `python:3.12-slim` + Debian `libzbar0`; Playwright, bundled
  Chromium, and Beautiful Soup ship in the production image. Entrypoint:
  `alembic upgrade head`, then Uvicorn on `${PORT:-8124}`.
- Render blueprint `render.yaml`: service `inventory-app`, production database
  `inventory-db-copy` via `fromDatabase` internal connection string.
  **`render.yaml` declares no `databases:` block** — the DB plan
  (`basic-256mb`, 1 GB storage) and 3-day point-in-time recovery exist only in
  the Render dashboard; nothing in the repo can detect them changing. The
  dashboard is also the authority for the production hostname
  (`https://inventory-app-gb1c.onrender.com` when last recorded).
- The 1 GB ceiling is structurally distant: **no binary data is persisted
  anywhere** — decode stores nothing, imports discard the file, there is no
  attachment feature. Growth is rows only (`transactions` grows forever;
  `sessions` and `login_attempts` are swept). Revisit if files are ever stored.
- `healthCheckPath: /healthz` runs a real database query, so a deploy that
  cannot reach Postgres fails instead of going green; it does not keep a free
  instance awake. `/db-test` (TechFM OA+) verifies database identity;
  `/healthz` proves only reachability.
- Required env: `DATABASE_URL`. Production sets `COOKIE_SECURE=true`,
  `SQL_ECHO=false`, `LOG_LEVEL=INFO`.
- **`VAPID_PRIVATE_KEY` enables Web Push** — set in Render's Environment page
  (`sync: false`; deliberately not mirrored into the committed Dockerfile).
  Absent, push disables itself and `/push/config` / `/push/test` return 503.
  Rotating it invalidates every existing subscription.
- **`COOKIE_SECURE` controls three things** — the cookie `Secure` flag, HSTS,
  and whether FastAPI's docs endpoints exist at all; one flag so a deployment
  cannot be half production. When true, `/docs`, `/redoc`, and
  `/openapi.json` are **un-mounted** (plain 404) — `app.openapi()` still
  returns the schema, and re-enabling takes a code change. Where mounted they
  render blank anyway (CSP; see N8 in `docs/open-work.md`).
- Static assets are served `Cache-Control: no-cache`; the app sends
  `Permissions-Policy: camera=(self)` and `X-Request-ID: <12 hex>`. Windows
  local pyzbar may need the Visual C++ 2013 runtime (`msvcr120.dll`).

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

Real-time invalidation (`domain/realtime.py`, `services/realtime*.py`,
`routers/realtime.py`, `static/realtime.js`):

- The wire envelope is exactly `type`, `id`, `req` — no row data, no actor.
  **Three events**; the vocabulary, audiences, and pinned emitter sets live in
  `docs/endpoint-map.md` → Real-time, asserted by `test_realtime_emit.py`.
  Audience is a noise rule, not a security boundary — scoping happens on the
  client's REST refetch. Emission is non-blocking and best-effort, after the
  mutating service returns; REST remains the source of truth.
- The browser owns one same-origin `/ws` connection: connect after auth,
  disconnect on logout or any global 401, generation-guarded so an old
  socket's callbacks cannot reconnect over a cleared session. Failed
  connections retry with equal-jitter exponential backoff (0.5–1s doubling to
  15–30s); a successful **recovery** (never the first connect) notifies each
  handler once, since invalidations may have been missed.
- `static/realtime.js` has no DOM/view dependency; only explicitly subscribed
  views refresh, and only while their own page is active. No global reload,
  no actor suppression, no status UI, no client→server messages.
- Work Orders: an entity event for an on-screen card refetches that one work
  order and repaints in place; a 404 removes the row; an off-screen id is
  ignored; a null id or a reconnect refetches the full list. A card with any
  editor section open is **held** — no refresh touches it, it is flagged
  `data-missed-update` and catches up when its last editor closes, and a
  full-list refetch is deferred while any card is held. A filtered list is a
  snapshot refined by live badges: a row whose new status no longer matches
  the filter keeps its updated badge and stays until the next full load.
- Admin Review: socket-driven refreshes are silent and never replace the open
  receipt; queue requests carry a monotonic id so an older response cannot
  repaint newer cards.

Upload size caps (`app/routers/_uploads.py`): exactly two upload routes, both
capped — `POST /barcodes/decode` **10 MB**, `POST /work-orders/import`
**25 MB** — via `read_capped` (a third upload route should call it too). Over
the cap is 413 naming the limit; `api.js` surfaces `detail`, so it renders in
the existing error UI. Caps are constants, not env vars — an upload limit is
a contract. The cap bounds what is held in memory and reaches Pillow/CSV, not
what is transmitted (Starlette has already spooled the body). On the import
route the TechFM OA+ gate resolves before the body is read, so an
unauthorised oversized upload is 403. Refusals log
`event=upload.rejected_too_large`.

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
  - **The TechFM OA+ work-order CSV export is deliberately exempt** and remains the
    uncapped filtered set. A CSV that silently omits rows while looking complete
    is a records problem, not a performance one.
  - **Owner-validated in the browser on 2026-08-10** across all six capped lists
    and their consumers. Every list behaved exactly as before, which is the
    whole claim — the ceiling sits far above any real data.
- Both upload routes are size-capped (10 MB image / 25 MB CSV) and return 413
  above it; see *Upload size caps* under Runtime And Stack. On the import route
  the role gate runs first, so an unauthorised caller never reaches the check.
- User management requires strict subordinate authority: actor rank must be
  greater than target role rank.
- Owner is bootstrap-only; API users cannot manage an owner.
- TechFM OA and above cost fields are redacted server-side for lower roles.

Work orders:

- A work order is a standalone entity; **identity is its `number`**, unique
  case-insensitively + trimmed.
- **Cards are pages.** Clicking a work-order card navigates to
  `/workorder_card/<number>` and renders that one work order as a page rather
  than expanding it in-list: the filter and import sections hide and a Back
  control appears above the card. The card remains a `details.wo-card` inside
  `#work-orders-list` — moving it into another container would silently break
  the delegated action layer (~20 click branches, the technician picker, the
  billing editor) and the realtime subscriber's card lookup, with no error.
  `GET /workorder_card/{number}` (`main.py`) serves the same SPA shell as `/`
  so a refresh, bookmark, or pasted link resolves instead of 404ing. Deep links
  resolve number→id through the server-scoped list search
  (`apiListWorkOrders({ q })`), **not** `/work-orders/lookup`, which is
  Supervisor+ and would 403 a technician following a link to their own assigned
  work order. An archived and an out-of-scope number are therefore
  indistinguishable and both report "not available". The Mass Stage hand-off
  routes to the same card page via the existing `pendingFocusId` mechanism.
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
- Live status is `created` → `assigned` → `in_progress` → `ready_to_complete` →
  `completed` → `review`, with `on_hold` as the pause state. **On-Hold now means
  exactly one thing: nobody is on the clock.** Every new
  import starts Created. Assigning one or more technicians advances a
  pre-work row to Assigned, and clearing every technician returns an Assigned
  row to Created; later states never rewind automatically. The first committed
  material or labor activity advances Created/Assigned to In-Progress through
  the same domain transition.
  The Work Orders card walkthrough is built on **tracked time**, not on status
  buttons. `POST /work-orders/{id}/tracking/start` opens a labor session for the
  caller and, as a side effect, advances a pre-work row to In-Progress or
  resumes an On-Hold one — so "Set In-Progress" is no longer a button anyone has
  to find. `POST /work-orders/{id}/tracking/stop` closes it, and when it closes
  the **last** running session on an In-Progress row the work order moves itself
  to On-Hold. Both are idempotent, and both are open to assigned Technicians
  **and to Supervisor+ on any work order they can see** — a supervisor who does
  the work records it without joining the crew.
  The narrow `POST /work-orders/{id}/complete` action ("Notify Supervisor")
  finishes the job and stops every clock on it. **Where that finish
  lands is the caller's role** (`domain.work_orders.completion_target_status`):
  Supervisor+ reaches Completed, while a Technician's finish moves the row to
  **Ready to Complete** and appends the server-authored note `marked work ready
  to complete`. Ready to Complete is a real status rather than a note on an
  On-Hold row, so a supervisor's filter separates "the job is done and waiting
  on you" from "the crew is at lunch" without opening a card. From there
  Supervisor+ gets Approve — Mark Completed (`PATCH {status: "completed"}`) and
  Send Back (`PATCH {status: "in_progress"}`); no new endpoint. Send Back raises
  `work_order.sent_back` to the assignees and the routed supervisor. Completed is the
  billing state the Admin review queue reads, so it
  stays a supervisory decision even once the work itself is done. The rule keys
  on role rather than assignment because a Supervisor may also be an assigned
  worker and uses the same button. Idempotency compares against the caller's own
  target, so a double tap appends no second note.
  `POST /work-orders/{id}/start` survives unchanged for the Scan / Stock
  confirmation, which is a different surface with its own reasons.
  While In-Progress, the assigned worker also has a separate narrow `POST
  /work-orders/{id}/hold` action that places the row On-Hold and stops **every**
  clock on it. The assignment-checked `POST /work-orders/{id}/resume` returns the
  row to In-Progress and deliberately **starts no clock**: stopping a clock can
  only under-bill, while starting one bills somebody who may not be on site.
  Supervisor+ retains the unchanged general status controls as an additional
  management path; driving a row into `on_hold`, `ready_to_complete`, or
  `completed` by PATCH also stops every session.
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
- Closing requires TechFM OA+ and is valid from every live status. Each expanded Work
  Orders card exposes the confirmed Archive action to TechFM OA and above; Admin Review
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
  is `effective_billable * current Item.price` (TechFM OA and above only), where
  `effective_billable` is `work_order_items.billable_quantity` when set else the
  line `quantity`. Shown per line and summed into `materials_total` on the Work
  Orders page. Work-order-linked transaction rows (`work_order_id` set) are a pure
  inventory record -- History suppresses their per-row charge -- so editing a line
  never double-bills and a line-edit's signed `adjust` (the stock delta, e.g. `-6`
  when a line goes 2->8) is never billed as a negative. Ad-hoc (non-work-order)
  transactions keep their per-row History charge.
- `work_order_items.billable_quantity` is the per-line billing override
  (TechFM OA and above, `PATCH .../items/{id}/billing`): NULL bills the full `quantity`,
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
  adding materials, tracking their own time, and the assignment-checked
  start/finish/hold/resume walkthrough are Technician+ — but a Technician's
  finish lands Ready to Complete, not Completed (see the walkthrough rules
  below), and a Technician can no longer key labor hours by hand at all;
  operational routing/general status/mode, hand-entered labor, and material
  corrections are Supervisor+; Review adds the Completed + second-person gate;
  imported/legacy metadata and close/archive are TechFM OA+; archive accepts
  any live status.

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
owner > admin > techfm_oa > supervisor > technician
```

| Capability | Rule |
| --- | --- |
| Login/logout/me | login public; logout/me require session |
| Dispense | any authenticated role |
| Stock | supervisor+ |
| History | supervisor+ |
| Void transaction | supervisor+ for any actionable row; Technician may remove only their own work-order dispense |
| Edit item notes | supervisor+ |
| Create/edit/archive item | techfm_oa+ |
| Correct count | techfm_oa+ |
| View item price/product link | techfm_oa+; server redaction below techfm_oa |
| Set billing override | techfm_oa+ |
| List users | supervisor+ |
| Create/reset/archive/restore/delete user | actor must outrank target |
| Edit user name + username | self, or actor outranks target |
| Change a user's role | techfm_oa+ AND actor outranks both the current and the new role (so a TechFM OA can never touch an Admin or Owner, nor hand those roles out) |
| Mass-stage page/API | supervisor+ |
| Work Orders list/get/items | any authenticated user, server-scoped (Technician: assigned; Supervisor: unassigned OR routed to self OR assigned as a worker; TechFM OA+: all) |
| Edit Work Order notes / add material | any authenticated in-scope user |
| Start / stop time tracking | assigned Technician, or supervisor+ on any visible work order (no assignment needed) |
| Record labor by hand (any worker, or self when unassigned) | supervisor+ (scoped) — the correction route; a Technician's hours come from tracked sessions |
| Edit Work Order supervisor / technicians / status / entry mode / labor revision or removal / logged-material quantity or removal | supervisor+ (scoped) |
| Finish assigned work into Completed | supervisor+ (a Technician's finish lands Ready to Complete for review) |
| Approve / Send Back from Ready to Complete | supervisor+ (the existing status PATCH) |
| Edit imported Work Order metadata (Location, Service, Schedule Date, Output to, Vendor Contact, Symptom/Task) | techfm_oa+ (scoped) |
| Import work orders (CSV) | techfm_oa+ |
| Export work orders (CSV, full or For Client) | techfm_oa+, server-scoped |
| Preview/re-archive all live legacy work orders | owner exactly; server gate and service check |
| Undo the import's auto-close (last 24 hours, company-wide) | techfm_oa+ — the role that imports and the role that archives, deliberately not the Supervisor gate on single-work-order restore |
| Admin Review page / receipt | techfm_oa+; lists every live Review work order |
| Low Stock page / retune a threshold, edit an item, correct a count | techfm_oa+; lists items at or below their own threshold with 7-day usage, grouped by dispense recency |
| User Requests page / request status | techfm_oa+; list, edit, resolve/reopen, and fulfil operational exceptions |
| File an item request | any authenticated user, from an empty search on Work Orders or Find Item |
| Close/archive a work order | techfm_oa+ (scoped), any live status; UI action lives on expanded Work Orders cards and remains in Admin Review for Review rows |
| Set work-order line billing override | techfm_oa+ (scoped) |
| Send a Completed work order to Review | **admin+**, or the routed Supervisor when not also an assigned worker. The one capability an Admin holds that a TechFM OA does not — see the note below |
| Scan-gate work-order cards | any authenticated user (scoped Created/Assigned/In-Progress list); In-Progress starts a batch, Assigned confirms an in-place start for Technician+, Created opens Work Orders for assignment |
| Tools: view list/lookup, return | any authenticated user |
| Tools: create, edit, archive, checkout | techfm_oa+ |

TechFM OA nuance: the role sits between Supervisor and Admin (rank 2 of
`technician 0 < supervisor 1 < techfm_oa 2 < admin 3 < owner 4`) and carries the
whole Admin toolkit with two subtractions, both of which fall out of the rank
rather than any special case:

1. **It cannot send a work order to Review.** The handoff floor in
   `services.work_orders._require_review_handoff_permission` is the one
   `ROLE_ADMIN` left in `backend/app`; a TechFM OA fails it, and fails the
   routed-Supervisor branch too. A TechFM OA *is* a valid routing target, so
   they can own a work order operationally and still hand the final step to an
   Admin, the Owner, or another routed Supervisor. The Work Orders card shows
   them the button disabled with that reason rather than hiding it.
2. **It cannot re-role an Admin or Owner, or hand those roles out.**
   `can_manage` is false at equal rank and above. Admins keep full control of
   TechFM OA accounts and can create them, which is why the role got its own
   rank instead of sharing Admin's.

`tests/test_route_role_gates.py` asserts that no route gate is left at the Admin
floor, so a new route written with `ROLE_ADMIN` out of habit fails loudly
instead of silently locking TechFM OA out.

Tools UI nuance: TechFM OA and above can search every active user and act on that
user's custody card. Supervisor/Technician are pinned to their own card. The
HTTP return route remains session-gated and accepts any `assigned_to_id`; this
self-scope is a frontend workflow boundary, not a backend authorization rule.

Scoping nuance:

- `GET /mass-stages/` list is scoped: supervisor sees own stages, techfm_oa+
  all. Direct stage-by-ID routes are supervisor+ gated but not additionally
  creator-scoped once the caller has a stage id.
- The `/work-orders` routes DO add real per-row assignment scope checks
  (`services.work_orders`), because technicians reach them. Unassigned rows are
  the shared Supervisor pickup queue; a routed row is visible only to its
  selected Supervisor and TechFM OA and above. The service also
  enforces the edit matrix: Technician = notes/add material/own labor;
  Supervisor+ = operations/labor and material corrections/completion;
  TechFM OA+ = imported/legacy metadata.

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
- `role` is editable by TechFM OA+ through `PATCH /users/{id}/role`, which revokes
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

### `push_subscriptions`

Fields: `endpoint`, `user_id`, `p256dh`, `auth`, `created_at`.

Rules:

- **`endpoint` is the primary key.** A subscription belongs to a browser
  profile, not to an account: the browser mints one endpoint per device and
  hands the same one back to whoever is logged in. Keying on it makes a
  re-subscribe *reassign* the row, which is what stops a shared crew phone from
  receiving the previous user's notifications. A surrogate id keyed on
  `user_id` would leave both rows alive and deliver to the wrong person.
- `user_id` cascades on user delete, matching `sessions` — a removed account
  stops receiving as well as stops authenticating. Indexed, because the fan-out
  selects by recipient and the endpoint primary key does not serve that query.
- `p256dh` and `auth` are browser-generated payload-encryption material (RFC
  8291). Push payloads are encrypted end-to-end with them, so Apple relays
  ciphertext it cannot read. They are per-device secrets: never logged, never
  returned by any route.
- No expiry column and no sweep. A subscription dies when the push service says
  so — `services/push.py` deletes a row only on the 404/410 that
  `domain/push.py::classify_push_response` maps to `PUSH_DROP_SUBSCRIPTION` —
  or when the user logs out of that device.
- Archived users are filtered out of the audience at query time rather than
  having their rows deleted, so un-archiving restores their devices.

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

Fields: `id`, `barcode`, `name`, `quantity`, `low_stock_threshold`,
`location`, `notes`, `price`, `product_link`, `created_at`, `archived_at`.

Rules:

- `barcode` is canonical/display code.
- `notes` is JSONB with string keys and scalar values (`str`, `int`, `float`,
  `bool`).
- `archived_at` hides item from lists/lookups but keeps joins for history.
- `price` and `product_link` are cost-sensitive and server-redacted below
  Admin.
- `low_stock_threshold` is a whole number >= 1 (DB CHECK), default 6. An item
  at or below it is "low": it appears on the Low Stock page and a write that
  crosses it pushes to TechFM OA+ (`domain/low_stock.py`). Not redacted.

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
`supervisor_id`, `legacy`, `auto_closed_batch_id`, `auto_closed_at`.

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
  `ready_to_complete`, `completed`, and `review`, in that lifecycle order —
  which is also the order every dropdown and filter renders in. Closed is
  `archived_at`, not a stored status value.
  On-Hold is stable during material/labor activity until Supervisor+ explicitly
  resumes or rolls it back, or a technician taps Start Tracking (the tracking
  service performs that transition itself rather than widening
  `status_after_activity`). New imports
  default to Created; worker assignment derives Assigned, and the first
  material/labor activity derives In-Progress. Migration `f4c6e8a0b2d3` added
  the five-state lifecycle, while `f5d7f9b1c3e4` aligned existing pre-work rows
  with technician assignment. **`ready_to_complete` needed no migration**:
  `work_orders.status` is a plain `Text` column with no CHECK constraint, so
  adding a value is app-level only.
- `entry_mode` (`dispense` / `retroactive`) is the default mode for newly logged
  materials.
- `notes` is an append-only plain-text log on the work order. Every nonblank
  Technician+ save is serialized under the Work Order row lock and appends
  `MM/DD/YY hh:MM AM/PM Full Name note text`, using server time converted to
  `America/Chicago`. Pre-log free-form text and lines written in the earlier
  `[h:mm AM/PM] [MMDDYY] [Full Name]` shape remain intact and are never
  rewritten, so the two shapes coexist and age out; blank/null input cannot
  erase the history. Start Tracking, Stop Tracking, and Notify Supervisor each
  append a server-authored line through the same formatter, so the work
  timeline is public rather than buried in the sessions table.
- `work_order_technicians` is the authoritative plural assignment relation.
  Active Technician and Supervisor accounts are eligible workers; membership
  drives Technician visibility and also preserves a working Supervisor's scope
  when a different Admin/Supervisor owns routing
  (`domain.work_orders.can_view_work_order`). `assigned_to_id` remains a
  compatibility mirror of the first selected worker for Mass Stage and older
  clients.
- Soft delete via `archived_at` is the Closed state; the number stays reserved
  and material lines are kept. Closing is TechFM OA+ from any live status and is
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
  export is bulk-imported via `POST /work-orders/import` (TechFM OA+). Its columns
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
- **Import reconciliation.** The NetFacilities export is the full list of what
  is open upstream, so after each import's row loop one transaction closes every
  live non-`legacy` work order the CSV did not list, stamping
  `auto_closed_batch_id` (one uuid per import that closed anything) and
  `auto_closed_at`. Absence is the whole signal: nothing else ever takes a work
  order closed in NetFacilities out of this app's queues. The Admin report's
  Closed sections leave sweep closes out (endpoint-map → `HubReportResponse`). A CSV with no usable
  numbers sweeps nothing, which is what stops a header-only export from closing
  the company. `legacy` rows are excluded because they can never appear in any
  export — sweeping them would close all of them on every run.
- `archived_at` stays the only source of truth for closed/live; the two
  auto-close columns are provenance. They are set together by the sweep and
  cleared together by everything that un-archives a row — the undo, the reopen,
  and `restore_work_order` — so a live row never carries either, and a restored
  row stops counting as pending.
- A sweep-closed work order the *next* CSV lists again is un-archived and
  merged like any live row ("reopened"), which makes a partial or wrong export
  self-healing after the undo window lapses. A work order a **person** archived
  is still left alone by any import.
- `undo_auto_close` restores every sweep-closed row whose `auto_closed_at` is
  within 24 hours — every sweep in the window, not just the last import's — and
  each restore appends its own note. A restored row is eligible to be swept
  again by the next import: it is still absent upstream, and the remedy lives in
  NetFacilities. Labor sessions the sweep stopped do not restart.

### `work_order_items`

Fields: `id`, `work_order_id`, `item_id`, `quantity`, `billable_quantity`,
`mode`, `transaction_id`, `created_by_id`, `created_at`, `updated_at`.

Rules:

- The editable "materials actually used" list for a work order, separate from
  `mass_stage_items` (truck planning). One row per item per work order
  (`UNIQUE(work_order_id, item_id)`); re-logging an item ADDS to its row -- the
  line is the aggregate of that item's dispenses, written by every stock-out path
  via `attach_dispense_line`. The line is also the **billing unit**: the
  TechFM OA and above charge is `effective_billable * current Item.price` (exposed as the
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

- Each row records positive whole-minute actual labor attributed to a worker.
  **Most rows are produced by stopping a tracked session** (see
  `work_order_labor_sessions` below), not typed by anyone.
- Hand-entering, editing, and removing labor are all **Supervisor+**. A
  Technician cannot key a duration at all — their hours come from the clock, and
  a supervisor is the only one who can correct the result. That is what keeps
  the billed figure trustworthy: hours are never written, rewritten, or erased
  by the person they are attributed to. The direct cost is that a forgotten
  Start Tracking is unrecoverable by the technician who forgot it.
- The credited worker must be assigned to the work order **or** be the
  Supervisor recording themselves. That second case is a deliberate widening: a
  supervisor who does the work attaches billable labor without joining the crew.
  It is bounded by visibility and attributed by name, and the labor card already
  lists every row regardless of assignment, so it renders with no special case.
- Billing sums all actual minutes on the work order, rounds the combined total
  upward once to the next 30 minutes, then charges `$62.50/hour`. Rate and total
  are returned only to TechFM OA and above; actual and billed durations are visible to
  every in-scope user.
- The first labor insert uses `status_after_activity`, advancing Created/Assigned
  to In-Progress while leaving On-Hold and later states unchanged. Editing or
  deleting labor never rolls lifecycle status backward.

### `work_order_labor_sessions`

Fields: `id`, `work_order_id`, `technician_id`, `started_at`, `ended_at`,
`labor_id`, `auto_closed_at`, `created_at`, `updated_at`. Added by migration
`a2c4e6b8d0f1`.

Rules:

- A session is the record of **when** somebody worked. `ended_at IS NULL` means
  the clock is running. Stopping one computes minutes, creates a
  `work_order_labor` row, and links it through `labor_id`.
- **An open session contributes nothing to billing.** There is no labor row
  yet, so `labor_minutes`, `billed_labor_minutes`, the receipt, and the CSV
  export are exactly as correct for a job in progress as they were before
  tracking existed. This is the property that made the change additive rather
  than a rewrite of the billing path, and it is why sessions got their own
  table instead of nullable timestamps on `work_order_labor` — a running
  session has no duration, which would have forced `minutes` to become nullable
  and made every consumer of that column learn to skip NULLs.
- A **partial unique index** on `(technician_id) WHERE ended_at IS NULL`
  enforces one running clock per person across every work order, in the
  database rather than in a service check that races. Starting a clock while
  one is running elsewhere closes the other first — writing its labor row, its
  `stopped work` note, and running that work order's auto-hold. The abandoned
  row comes back through `services.work_orders.side_transitions` so its
  notification is not lost.
- **Stopping the last clock on an In-Progress row moves it to On-Hold** and
  fires `work_order.held`. A co-worker still tracking keeps it In-Progress, and
  an idempotent repeat closes nothing, so it neither transitions nor notifies.
- Sessions are stopped wherever work provably ended: Stop Tracking, `/hold`,
  Notify Supervisor, archive, and a Supervisor's PATCH into `on_hold` /
  `ready_to_complete` / `completed`. `/resume` starts none. Each closed session
  writes its own `stopped work` note authored by **its own technician**, not by
  whoever tapped.
- **The 12-hour cap** (`domain.work_orders.LABOR_SESSION_MAX_MINUTES`,
  `capped_session_minutes`) truncates a session that outran it, pulls
  `ended_at` back to the capped instant so the note agrees with the minutes
  billed, and sets `auto_closed_at`. It is applied **lazily** — on any read or
  tracking write — because the app has no periodic task runner and a cron would
  be new infrastructure for one rule; this follows the same pattern as
  `_heal_orphan_lines`. A session on a work order nobody opens therefore stays
  open past 12 hours until it is read, but still closes at the *correct* capped
  time, so only the flag is late. The cap deliberately does **not** auto-hold: a
  status change and a supervisor's phone buzzing as a side effect of somebody
  opening a card would be indefensible. Auto-closed entries are tagged
  "auto-stopped" on the labor card as a prompt to review, and nothing blocks
  them from billing.
- Because the cap writes its note at the capped time rather than the noticed
  time, an auto-closed line can appear **out of chronological order** in the
  log. Entries are appended in write order and never sorted; this is the one
  case where the two differ.

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
  TechFM OA+, mirrors `POST /transactions/adjust`): the client sends the
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

`docs/endpoint-map.md` owns the complete route table (method / path / gate /
service / tables / wrapper / views), the request/response contracts, and the
error catalog — go there for "what does this endpoint send/return/do". What
stays here is behavior that table cannot carry:

- All routes except `POST /auth/login`, `GET /`, `GET /workorder_card/*`, and
  `GET /healthz` require authentication.
- **NetFacilities.** Disabled by default; production enables it in both the
  Dockerfile and `render.yaml` (a Render deploy hook does not sync new
  `render.yaml` env declarations into an existing service). Auth is per-user
  Steel cloud sign-in only. Gated by `NETFACILITIES_CLOUD_AUTH_ENABLED` (plus
  base `NETFACILITIES_ENABLED`), `STEEL_API_KEY`, and
  `NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY` (Fernet, from
  `scripts.generate_netfacilities_cloud_encryption_key`), with optional
  timings: `..._LOGIN_TIMEOUT_SECONDS` / `..._BATCH_SESSION_SECONDS` (default
  840, under Steel's 15-minute cap), `..._SIGNED_IN_TIMEOUT_SECONDS` (600),
  `..._CAPTURE_POLL_SECONDS` (5), `..._ENRICHMENT_RETRY_SECONDS` (120). A
  captured session is **bearer-equivalent**: Fernet-encrypted one row per
  user, never committed, logged, returned, or placed in an env var; expiry is
  recovered by that user signing in again. The client **primes each context
  with one `GET /myhome`** before its first work-order read — NetFacilities
  serves a trimmed document (no Priority row) to an unprimed session — and
  re-primes + re-reads any document that lacks the `Priority Level` label, so
  a session going stale mid-batch cannot silently blank Priority. The value
  is server-rendered, so `NETFACILITIES_RENDER_DOCUMENT` defaults to `false`;
  `true` restores the rendered read for diagnosis (same-origin `GET`
  subresources only). Enrichment fills only the exact generated Task/Symptom
  fallback and a blank Priority, via compare-and-set; responses and logs
  never contain source values, storage state, cookies, or headers. **Not yet
  done:** the manual D5/D6 replay spike (IMP-040 in `open-work.md`).
- **`/ws` runs no application middleware** — the rate limiter, security
  headers, and request logger are `@app.middleware("http")` and the handshake
  is a `websocket` scope; the route does its own origin check and logging.
  Auth is the session cookie **revalidated every 60s**, so a logout or role
  change closes the socket. Refusals happen before `accept()` as plain HTTP
  401/429. Every policy constant lives in `domain/realtime.py`.
- **Web Push has two deliberately separate role floors**:
  `SUBSCRIBE_MIN_ROLE` (Technician) decides who is *offered* the opt-in
  button — `/push/subscribe` itself is not role-gated; holding a subscription
  grants no authority — and `TEST_AUDIENCE_MIN_ROLE` (Admin) is `/push/test`'s
  audience. Collapsing them into one constant is how the Owner's diagnostic
  starts buzzing the whole crew.
- **Notification triggers** are registered in `docs/notification-events.md`
  (updated in the same commit as any trigger change); adding one is the
  three-step procedure in `docs/adding-a-notification-trigger.md`. Mechanism
  rules for every trigger: the acting user is always suppressed by id;
  delivery is a `BackgroundTasks` handoff and `_deliver` opens its own
  session (a yield dependency is torn down before background tasks run); a
  transition notifies only when it actually happened (compared against the
  `previous_status` stamped on the returned row — idempotent repeats and
  re-saves send nothing); one PATCH can be several independently evaluated
  events; overlapping transitions resolve by pinned branch order; a rule that
  raises never fails the committed write; the CSV import's per-supervisor
  bulk send is the single batching exception.
- Web Push facts that are not obvious: iOS exposes push only to a
  Home-Screen-installed app (own cookie jar; no programmatic install offer
  exists); logout unsubscribes **this device only**; only a 404/410 deletes a
  subscription (`classify_push_response` — a bad VAPID key 401s for every
  device); the endpoint allowlist is re-checked on **every** send (a stored
  endpoint is otherwise an SSRF primitive); `/service-worker.js` is served
  from root, not `/static`, because a worker's scope is its serving
  directory.
- **403-before-422 on the line-billing route**: its TechFM OA+ gate is a
  dependency, so it answers before Pydantic — a malformed *and* unauthorized
  request returns 403.

## Frontend Feature Context

Navigation (`views/nav.js::showPage`): the bar is four task-domain groups —
Inventory (Add Item, Find Item, Tools), Field (Scan / Stock, Work Orders,
Mass Stage), People (Add User, Users), Review (Low Stock, User Requests,
Admin Review, History). Every page in `PAGE_ACCESS` belongs to exactly one group in
`shell-head.html` or it does not appear in the nav at all;
`applyRoleVisibility` hides buttons, then any group left empty. A role with
more than 5 visible pages gets each group collapsed into a popover toggle;
Technician (4 pages) renders flat. Icons are inline SVG
`stroke="currentColor"` (CSP forbids icon fonts). Activating Work Orders,
Find Item, or Mass Stage refetches current server data
(`cache: "no-store"`).

Login/landing: boot calls `/auth/me`; 401 shows login; any later 401 returns
to login globally. Landing is role-based (`landingPageForRole`): technician →
Transaction, supervisor → Work Orders, admin/owner → History; a resumed batch
overrides the default and opens Transaction.

Find/Add Item: Add Item (TechFM OA+) is Item/Tool sub-nav tabs, each with its
own scoped live-scan widget (a match warns the barcode is in use; a miss
prefills the field; `allowCreate: false`; page-leave stops both cameras).
Find Item renders nothing until explicit Search (`/items/?q=`) or Load All
Items; no-row states render the `#items-empty` panel carrying the
item-request prompt. Technicians get a simplified table; TechFM OA+ see
price/link columns and get Create Item / Add Barcode shortcuts on an unknown
scan.

Scan / Stock: the gate lists scoped Created/Assigned/In-Progress cards —
In-Progress arms the batch, Assigned confirms the in-place start, Created
offers navigation to Work Orders. Supervisor+ get a debounced number filter
and an advanced mode (Add Stock/Take Out toggle, browse-all on empty search);
Technicians see only assigned cards. Manual entry hides until a card is
selected and commits through the same `commitScannedItem` path a scan uses.
A short dispense still commits and renders red `Please re-count stock`; an
unpriced work-order item raises the deduplicated missing-price request. Live
scan uses dwell + same-barcode cooldown; the camera auto-starts only with
permission already granted.

User Requests: TechFM OA+ queue with open/resolved tabs and a client-side
type filter. Recount cards freeze the shortage snapshot — never editable (the
whitelist is `EDITABLE_DETAILS`; a rejected key is 409) — and take an inline
correction that resolves the request wherever the adjust is made. Item
requests (NULL `item_id` = "not in the app at all", distinct from a recount's
wrong count) are filed from the two empty states by any role; fulfilment
links an existing item or creates one, logs it on the originating work order
**always retroactively** (never moves stock — it calls `attach_dispense_line`
directly), warns-and-skips a closed work order recording the reason, and
cascades to admin-confirmed siblings matched on token-set equality. An open
missing-price card requires a price > 0 and a nonblank link together.

Mass Stage: create stage → add work orders (resolve-only; building must
match) → plan items → `planning→loading` → load (splits across slots by
`sort_order`, real per-slot dispenses) → return unused (silent stock add) →
complete → optionally Stage Again (fresh empty stage, nothing copied). The
UI is a Community → Building → Unit collapsing tree; each unit links to its
work order's card; completed stages are read-only and terminal.

Work Orders: **cards are pages** — clicking navigates to
`/workorder_card/<number>` (served the same SPA shell as `/`; deep links
resolve number→id via the scoped list search, **not** the Supervisor+
lookup, so an archived and an out-of-scope number are indistinguishable and
both report "not available"). The card must remain a `details.wo-card`
inside `#work-orders-list` — moving it into another container silently
breaks the delegated action layer (~20 click branches) and the realtime
card lookup. Collapsed card background encodes status: Created gray,
Assigned red, In-Progress yellow, On-Hold orange, Ready to Complete violet,
Completed blue, Review green. The technician ladder is built on the clock —
Start Tracking / Stop Tracking / Notify Supervisor / Place On-Hold / Resume
(rules in Hard Invariants); Ready to Complete shows Supervisor+
**Approve — Mark Completed** and **Send Back**, and a technician a hint with
no actions; the Edit-details status dropdown never offers
`ready_to_complete` or Review. Buttons that need assignment server-side are
gated on it client-side too. Nested collapsed cards: Edit details
(Supervisor sees routing/assignment/status; TechFM OA+ also imported
metadata; `number` never), Notes (append-only log; save clears and closes),
Materials (Technicians add-only, read-only quantities), Labor (Technician
fully read-only; the supervisor picker includes themselves "(not
assigned)"; entries show their session window, capped ones tagged
"auto-stopped"). TechFM OA+ get import (with summary counts), filtered/
client CSV export, Archive on any live card, and the exact-archived-number
restore prompt; the Owner additionally the hidden legacy re-archive button
(preview count → confirm → actual count). The list shows the newest 10 by
default ("Show all" lifts it); any active filter queries the complete
matching set.

Low Stock: TechFM OA+ reorder queue. Every live item at or below its own
`low_stock_threshold`, ordered by headroom (deepest below first), each card
showing on-hand, 7-day dispensed usage, and an inline threshold input that
commits on blur/Enter and reloads (a lowered threshold can clear the row).
Three mutually exclusive recency tabs (last 24h / 2-7 days / older or
never), bucketed client-side from `last_dispensed_at`; one fetch serves
all three. Each card expands to edit core fields, additional barcodes,
and to correct the count (`POST /transactions/adjust`); the threshold
control stays in the card header. Any save reloads the queue rather
than patching the card.
`item.low_stock.changed` refreshes it in place while it is the active page.

Admin Review: TechFM OA+ page over live Review rows; selecting a card opens
one persistent receipt textarea (shared `pricingText.js` 41-char lines,
`billable ?? quantity` × current price +15%, `[x] Labor Hours` +
`labor_total` with no second markup, no number header, `wrap="off"`).
`NO PRICE` marks the total incomplete and disables Close; Return to
In-Progress stays available. Close archives via the shared endpoint; either
action keeps the receipt visible for copying.

Tools: Add Tool is the Tool tab on Add Item (TechFM OA+; barcode + name +
quantity only). The Tools page defaults to **Custody**: TechFM OA+ search
active users into a profile card; Supervisor/Technician are pinned to their
own `/auth/me` card — a frontend workflow boundary, since the return route
accepts any `assigned_to_id`. Check-in starts from a holding row, defaulted
and capped to the outstanding balance; checkout is TechFM OA+ from the
selected user's card; a scan never commits automatically. Correct Count
mirrors items' (absolute value + required reason) and is the only restock
path. The page composes existing endpoints — no custody endpoint or
migration exists; custody stays ledger-derived. Auth reset clears page-local
selection/scan context.

History: Supervisor+; tabs all / by item / by user plus an overlay
work-order filter matching each row's own `work_order_number` — searchable
forever, including archived work orders. An exact archived number prompts
restore (a declined number is not re-prompted this session). Voided rows
hidden; any visible row can be voided by the same role set. Charge column
(TechFM OA+): ad-hoc rows show base and +15%; work-order rows show `—` and
have no billing editor (they bill via the line). Copy table exports all
matching rows (cap 100 pages × 100): the TechFM OA+ export fills work-order
rows' pricing from the line `unit_price` and appends the per-work-order
**Work Order Summary** block (`materials_total` + 15%) — per-row figures can
diverge from it; the summary is authoritative.

Users: Supervisor+ list, archived included (dimmed, restorable — keeps the
History by-user filter working). Add User requires username + both names +
password + a subordinate role. Edit Name (self or manageable subordinate)
also corrects login usernames and remediates legacy no-name accounts; Edit
Role offers only strictly outranked roles and revokes the target's sessions;
archive offers the force-return-tools second confirm.

Scanner: upload mode posts to `/barcodes/decode`; live mode is vendored
ZXing in the browser (environment camera, 1280×720 ideal, torch only if the
track reports it) and never calls the backend. `scan-test.html` is an
unauthenticated diagnostic harness outside the SPA.

## Backend Feature Context

Per-function service internals are code-owned — use codebase-memory-mcp
(`get_code_snippet`, `trace_path`) and `docs/endpoint-map.md` → Service
Invariants. Two facts worth pinning here: `authenticate` rejects archived
users indistinguishably from bad credentials (and
`get_active_session_user` filters them again), and only login, account
creation, and the Users table ever display a login username — every
operational surface renders the derived full name.

## Migration History

Alembic head: `a2c4e6b8d0f1`.

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
| `fbc4e6a8d0f2` | hash session tokens at rest (`sessions.token_hash` replaces the raw token) + `login_attempts` throttle counters |
| `0c1d2e3f4a5b` | nullable `work_orders.priority`; no default and no backfill, written only by NetFacilities enrichment |
| `1d2e3f4a5b6c` | `push_subscriptions` for Web Push opt-in, keyed on `endpoint` so a re-subscribe reassigns a shared device rather than duplicating it; nothing to backfill |
| `a2c4e6b8d0f1` | `work_order_labor_sessions` for tracked start/stop labor, with a partial unique index on `(technician_id) WHERE ended_at IS NULL` enforcing one running clock per person; nothing backfilled, so existing labor rows keep rendering as a bare duration. The new `ready_to_complete` status needed no migration — `work_orders.status` has no CHECK constraint |

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
| `test_user_role_edit.py` | TechFM OA and above-only subordinate role changes, rank restrictions, session revocation, and UI/API contracts |
| `test_user_archive.py` | user archive blocks login, revokes sessions, list scoping, refuses archive with outstanding custody, and force-returns held tools atomically |
| `test_item_update_partial.py` | partial item PATCH + clear price/link to null |
| `test_history_price_snapshot.py` | frozen `unit_price` snapshot; non-zero rows unchanged by price edits; snapshot 0 / NULL falls back to live price |
| `test_roles.py` | five-role hierarchy, TechFM OA's position and limits, labels, and transaction/user-management rules |
| `test_role_mirror_parity.py` | `static/roles.js` ranks/roles/labels match `app/domain/roles.py` |
| `test_work_order_status_parity.py` | the status vocabulary agrees across its four hand-edited homes — `ALL_STATUSES`, `statusLabel`, the page filter (values **and** lifecycle order), and the badge/accent/hover CSS — plus the `renderBody` action names matching their click handlers |
| `test_route_role_gates.py` | important route minimum-role gates, plus a guard that no route gate is left at the Admin floor |
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
| `test_work_orders_domain.py` | pure rules: number normalization, the seven-status lifecycle order, community vocabulary, worker-derived Created/Assigned, activity-derived In-Progress, note-log formatting, the 12-hour cap and 1-minute floor, combined labor rounding/charge, fill-blanks, visibility scope |
| `test_work_orders_service.py` | DB-backed service coverage: find-or-create/resolve-only, assignment/scope/routing, the walkthrough actions, tracked sessions (auto-hold on last clock-out, cross-work-order auto-stop with `side_transitions`, the partial unique index, the lazy cap, an open session billing nothing), the two-person Review handoff, labor rules incl. a supervisor crediting themselves, notes/archive/materials, zero-stock adds + recount lifecycle, Owner legacy re-archive, AND-composed filters, community aliases, list cap |
| `test_work_order_import.py` | CSV parsing/import, required-number-header and UTF-8 preflight, blank/missing-task NetFacilities fallback, generated-to-real replacement, duplicate-row precedence, manual-task preservation, full-name Admin/Supervisor routing independent of Created status, unmatched/ambiguous/archived/ineligible-role fallback, idempotence, closed-row count/no-mutation, and Admin gate |
| `test_work_order_name_responses.py` | work-order response exposes plural operational names, rounded labor detail/totals, and the note-log text while omitting login usernames |
| `test_work_order_line_sync.py` | line stays in sync across every stock-out path (scan/scan-and-go/load), accumulate, void walk-back, orphan self-heal |
| `test_work_order_billing.py` | line is the billing unit: work-order rows carry no per-row History charge (incl. the signed line-edit `adjust`); ad-hoc rows still billed; per-line override drives charge + `materials_total`, clears when quantity drops below it, redacts below Admin; history row exposes `work_order_id` |
| `test_work_order_export.py` | TechFM OA+ scoped full/client CSV exports, joined operational filters (including date), unchanged client scope behavior, import-header compatibility including generated-task round-trip, billing totals, and receipt cells |
| `test_netfacilities_parser.py` | sanitized server-rendered HTML parsing, identifier/status fail-closed checks, login-document detection, required fields, input validation, and safe Priority body-vs-script structure classification |
| `test_netfacilities_client.py` | one allowlisted authenticated GET, refusal to run without an injected browser context, rendered document routing with only same-origin `GET` subresources allowed, one-read diagnostic reuse, response metadata/size boundaries, auth redirect detection, and runtime browser placement |
| `test_netfacilities_config.py` | disabled default, timeout/render-flag validation, lazy imports, and production-safe startup |
| `test_netfacilities_service.py` | exact live candidate union, serial fake reads, pre-request progress ordering/validated-number filtering, two-field compare-and-set writes, idempotency/concurrent-edit protection, error counts, auth stop, timeout, and no-create behavior |
| `test_netfacilities_jobs.py` | cloud-session-only precondition (no session means sign in, never a silent fallback), owned client lifetime, serialized duplicate admission, shared in-flight current-number snapshots, terminal progress clearing, aggregate results, auth-loss state carrying the user to expire, and clean shutdown cancellation |
| `test_work_order_priority.py` | nullable ORM/response contract, generic-update exclusion, and read-only UI source contract |
| `test_receipt.py` | backend fixed-width receipt output matches the frontend contract for markup, truncation, quantities, missing prices, and labor rounding |
| `test_tools_domain.py` | pure `domain.tools.validate_return` outstanding-balance cap |
| `test_tools_service.py` | DB-backed: create/duplicate-live-barcode, archived-barcode reuse, checkout/return round-trip incl. `apply_delta` reuse, active-target validation without stock/ledger mutation, checkout overdraft (`NegativeQuantityError`), return-beyond-outstanding (`ToolReturnExceedsCheckedOutError`), per-tool and per-user custody aggregates, multi-user custody split, archive guard until full return, Correct Count increase/decrease/no-op (`NoChangeError`), and the regression that an `adjust` row never enters a custody balance |
| `test_item_requests.py` | item requests for material with no catalogue row at all, as distinct from a recount of an in-app item whose count is wrong |
| `test_history_date_filter.py` | pure `date_from`/`date_to` → half-open tz-aware UTC bounds builder used by `history.list_history` |
| `test_search_parity.py` | pins the two punctuation-insensitive search normalizers together — `services/items.py` (Find Item) and `static/format.js` (the client-filtered views) |
| `test_session_token_hashing.py` | X1: a read of `sessions` yields nothing replayable as a credential |
| `test_password_reset_revokes_sessions.py` | a reset signs the target out — there is no idle timeout to retire the old session (`c7e9a1b3d5f8` removed the sliding window) |
| `test_login_throttle.py` | pure backoff curve: a free window wide enough that ordinary mistyping is never punished, plus a bounded ceiling |
| `test_login_throttle_service.py` | DB-backed counting/locking, and the isolation properties that keep the throttle from becoming a DoS weapon against the crew |
| `test_rate_limit.py` | pure B3 policy: cap, window, and exemption list |
| `test_rate_limit_service.py` | in-memory sliding-window counters; `now` is an argument, so no sleeping and no flakiness |
| `test_rate_limit_middleware.py` | the limiter as actually wired, driven through the ASGI stack directly rather than a dev server |
| `test_list_limits.py` | pure X3 ceiling policy: the `+1` fetch and the exact truncation boundary |
| `test_list_cap_service.py` | the `event=list.truncated` early-warning signal — silent below the ceiling, exactly one line above it |
| `test_list_caps_applied.py` | the ceiling is actually wired into every list service; catches a new list endpoint that forgets the cap |
| `test_upload_limits.py` | `routers/_uploads.py` size caps and both call sites |
| `test_health_check.py` | `/healthz` liveness probe with the connection check monkeypatched |
| `test_docs_endpoints.py` | C4: `/docs`, `/redoc`, `/openapi.json` are un-mounted when `COOKIE_SECURE=true` |
| `test_logging.py` | `logging_config.py` and its three call sites: per-request id, JSON formatter, request context |
| `test_db_availability_guard.py` | stops CI reporting success over a half-skipped suite — DB-backed tests must not silently skip in CI |
| `test_realtime_dependency.py` | the WebSocket protocol library is actually installed — `TestClient` drives ASGI directly and would pass without it |
| `test_realtime_domain.py` | pure envelope/audience rules and policy constants; no sockets, clock, or DB |
| `test_realtime_registry.py` | connection registry, per-user cap, bounded handoff, and dispatch supervision |
| `test_realtime_endpoint.py` | handshake policy and connection lifecycle |
| `test_realtime_limits.py` | handshake-attempt and inbound-frame limits, in state and at the endpoint |
| `test_realtime_session_binding.py` | periodic re-resolution replacing the instant revocation a socket cannot get from a next request |
| `test_realtime_emit.py` | the **exact** emitter set: only commands that can change Review membership or card fields emit. Extend this assertion when adding one |
| `test_push_domain.py` | pure Web Push response classification and endpoint allowlist |
| `test_vapid_keys.py` | VAPID keypair interoperability (not cryptography) |
| `test_push_subscriptions.py` | Owner-only send gate, the two separate role floors, and the Admin-and-above test audience derived from rank; DB-backed endpoint reassignment on a shared device, caller-scoped delete, archived-user exclusion, delete-only-on-404/410, and the SSRF guard refusing a disallowed endpoint before any request — on both fan-out entry points. Its fan-out tests hide any subscription the developer's own database holds, inside the rolled-back transaction; without that a genuinely enrolled device joins every send under test |
| `test_notifications_domain.py` | pure recipient rules: actor suppression, dedup, dropping an unrouted supervisor, and that message text interpolates a work-order number or a count and nothing else. Every event is partitioned into a number event or a count event, so a new one cannot skip that decision |
| `test_notifications.py` | recipient resolution against the DB, that nothing is scheduled without recipients or without a VAPID key, and that delivery opens its own session and swallows failures |
| `test_work_orders_notifications.py` | every trigger at its route: right recipients, once per event across idempotent repeats, multi-event PATCHes, pinned overlap ordering, tracking-stop firing `held` only on the true auto-hold, the approve/send-back pair, routing notifying only the new supervisor, and a broken rule never failing the write |

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
- NetFacilities authentication is per-user Steel cloud sign-in only; the
  pre-Steel system was fully removed 2026-08-29 (see the Removed register).
  `NetFacilitiesClient` requires an injected browser context — only the Steel
  adapter can construct a working one. Browser-managed downloading, app-side
  credential/MFA handling, and secondary-data retrieval remain absent;
  default tests never make a live request. **Not yet done:** the manual
  D5/D6 replay spike, and deleting the unused
  `netfacilities-storage-state.json` secret file in Render's dashboard.
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
- Deferred work-order attributes not yet built: `due_date` and
  `external_ref`/`source`. Priority now exists as a nullable, source-owned,
  read-only field.
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

## Removed, Replaced, And Dormant

Kept so a removal is not re-proposed and a dormant file is not mistaken for a
working feature. Dormant is **currently empty**.

| What | When | Replaced by / why |
|---|---|---|
| `GET /items/search-index` | 2026-08-10 (X3) | no caller; `GET /items/?q=` covers it |
| `backend/static/index.html` | 2026-06-12 | runtime shell assembly in `main.py`, deliberately uncached |
| Sliding-window session idle timeout | `c7e9a1b3d5f8` | absolute `expires_at` + remember-me; consequence: a password reset must revoke sessions |
| Ten docs → four; NetFacilities/realtime/push plan docs, `handoff.md` | 2026-08-10 / 2026-08-16 | `open-work.md` is the only backlog; the archived docs survive in the vault under `archive/superpowers/` (N3 cites one) |
| Pre-Steel NetFacilities auth — local headed sign-in, shared secret file, five local routes, `services/netfacilities_auth.py` and siblings | 2026-08-29 | per-user Steel cloud auth (IMP-040) |

Still live — occasionally assumed dead: the **three** HTTP middleware layers
in `main.py` (`rate_limit`, `add_security_headers`, `log_request`;
registration order is the reverse of execution order, and `/ws` runs none of
them), and `static/scan-test.html` (deleted in `635fbd2`, restored — still an
unauthenticated diagnostic harness outside the SPA).

## Documentation Policy

House rules live in `CLAUDE.md` → Documentation conventions (current-truth
only, form rules, soft budgets). Specific to this file: prefer tables and
routing maps over narrative; tie source-of-truth statements to actual files;
document current behavior, never intended future behavior; put limitations in
`Known Gaps`.

