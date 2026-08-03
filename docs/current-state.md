# Inventory App Current State

Last reviewed: 2026-08-02

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
the change.

## Fast Orientation

The app is a self-hosted inventory and work-order staging system for physical
materials tracked by barcode.

Runtime shape:

- FastAPI API and static SPA in one process.
- PostgreSQL persistence through SQLAlchemy and Alembic.
- Static no-build frontend under `backend/static`.
- Barcode upload decoding through backend `pyzbar`.
- Live camera scanning through vendored `@zxing/browser`.
- Render deployment: one Docker web service plus one managed Postgres.

Core workflows:

- Find/create/edit inventory items by barcode.
- Stock, dispense, correct, void, and bill transaction rows.
- Scan items into work-order batches.
- Create/assign/log standalone work orders (identity = number); dispense or
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
| Auth/session/login/logout | `app/auth_deps.py`, `routers/auth.py`, `services/auth.py`, `schemas/auth.py`, `static/views/auth.js`, `static/api.js` | `test_auth_password.py`, `test_auth_session_lifetime.py` |
| Roles/permissions/user management | `domain/roles.py`, `routers/users.py`, `services/users.py`, `schemas/users.py`, `static/roles.js`, `static/views/users.js`, `static/views/nav.js` | `test_roles.py`, `test_route_role_gates.py` |
| Item CRUD/lookup/archive | `routers/items.py`, `services/items.py`, `schemas/items.py`, `models.py`, `static/views/items.js`, `static/views/itemEditor.js`, `static/api.js` | `test_item_barcodes.py`, `test_item_price_gating.py`, route-gate tests |
| Item notes | `domain/notes_validation.py`, `services/notes.py`, `schemas/items.py`, `routers/items.py`, `static/views/notes.js` | add/extend focused tests if behavior changes |
| Alternate barcodes | `models.py`, `services/items.py`, `schemas/items.py`, `routers/items.py`, `static/views/itemEditor.js`, `static/views/addBarcode.js` | `test_item_barcodes.py` |
| Stock/dispense/correction/void | `domain/quantity.py`, `services/transactions.py`, `routers/transactions.py`, `schemas/transactions.py`, `static/views/transactions.js`, `static/views/correction.js` | `test_quantity_reverse.py`, route-gate tests |
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
backend/tests/test_mass_staging*.py
backend/tests/conftest.py
```

## Runtime And Stack

| Area | Current implementation |
| --- | --- |
| Python | 3.12 in Docker; local venv currently Python 3.13.7 |
| Web/API | FastAPI 0.136.3, Starlette 1.2.1, Uvicorn 0.48.0 |
| ORM/database | SQLAlchemy 2.0.50, psycopg 3.3.4, PostgreSQL |
| Migrations | Alembic 1.18.4 |
| Validation | Pydantic 2.13.4 |
| Env/config | python-dotenv 1.2.2 |
| Uploads | python-multipart 0.0.32 |
| Upload barcode decode | pyzbar 0.1.9, Pillow 12.2.0, native zbar |
| Live barcode decode | vendored `@zxing/browser` UMD 0.2.0 |
| Tests | pytest 9.0.3 |
| Fixture generation only | python-barcode 0.16.1 |

Deployment:

- Docker image: `python:3.12-slim`.
- Native package: Debian `libzbar0`.
- Entrypoint: `alembic upgrade head`, then Uvicorn on `${PORT:-8124}`.
- Render blueprint: `render.yaml`.
- Required env: `DATABASE_URL`.
- Production env should set `COOKIE_SECURE=true` and `SQL_ECHO=false`.
- Static assets are served with `Cache-Control: no-cache`.
- App sends `Permissions-Policy: camera=(self)`.
- Windows local pyzbar may need Visual C++ 2013 runtime (`msvcr120.dll`).

## Hard Invariants

These are the constraints most likely to break real behavior if missed.

Inventory/transactions:

- Quantities and prices use `Decimal`/`Numeric`, not floats in backend logic.
- Stock/dispense/correction/void operations lock the item row before changing
  quantity.
- Dispense cannot make on-hand quantity negative.
- Transactions are append-only. Corrections are new `adjust` rows with a
  required reason.
- Voiding is a soft delete: set `voided_at`/`voided_by_id`, hide from history,
  reverse stock effect.
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
- Sessions are server-side rows and carried by an HttpOnly `session` cookie.
- Passwords are case-sensitive, not stripped, minimum 4 characters.
- User management requires strict subordinate authority: actor rank must be
  greater than target role rank.
- Owner is bootstrap-only; API users cannot manage an owner.
- Admin/Owner cost fields are redacted server-side for lower roles.

Work orders:

- A work order is a standalone entity; **identity is its `number`**, unique
  case-insensitively + trimmed.
- **Work orders are import-only.** The CSV import
  (`services.work_orders.get_or_create_work_order`) is the only path that creates
  one; there is no create endpoint and no "new work order" form. Every other
  surface calls `resolve_work_order`, which attaches to an existing number and
  404s on one no import has brought in. References still fill blank attributes
  but never overwrite non-blank ones.
- The same Admin+ card exports them back out: `GET /work-orders/export?scope=`
  writes one CSV row per work order, filtered to `all` (live), `archived`
  (closed), or one live status, and scoped to the caller like the list. Two
  variants share that filter:
  - `variant=full` (the "Export to CSV" button) leads with the seven import
    headers and then adds what the vendor CSV does not carry (status,
    technicians, supervisor, billing totals, timestamps), so a downloaded file
    re-imports as the idempotent fill-blanks path.
  - `variant=client` (the "For Client" button) is the billing sheet: `WORK
    ORDER`, `MATERIAL TOTAL`, `LABOR TOTAL`, `RECEIPT`. Both totals are the
    billed figures — materials carry the 15% mark-up, labor is the labor charge
    — so they add up to the receipt's own Total rather than disagreeing with the
    document next to them. `RECEIPT` holds the full Admin Review receipt text.
- The receipt has two implementations: `static/adminReviewReceipt.js` renders it
  for the Admin Review copy box, and `app/domain/receipt.py` renders the same
  characters for the client export. They must stay identical — the mark-up rate,
  the 41-character line width, name truncation, `NO PRICE` /
  `Total (incomplete)`, and money/quantity formatting all match, pinned by
  `tests/test_receipt.py`. Change one and the other has to move with it.
- Live status is `created` → `assigned` → `in_progress` → `completed` →
  `review`, with `on_hold` as a Supervisor-controlled pause state. Every new
  import starts Created. Assigning one or more technicians advances a
  pre-work row to Assigned, and clearing every technician returns an Assigned
  row to Created; later states never rewind automatically. The first committed
  material or labor activity advances Created/Assigned to In-Progress through
  the same domain transition, and an in-scope technician or supervisor can set
  it In-Progress explicitly from the Work Order card. Selecting a non-In-Progress
  Scan/Stock card does not start a batch: a confirmation offers to open that Work
  Order so the user can set it In-Progress. A technician or supervisor can mark
  In-Progress work Completed; only
  Supervisor+ can manually roll a status back from Completed or an earlier step,
  place it On-Hold, resume it, or send Completed work to Review after confirming
  it is ready. Manual pre-work rollback still derives Created/Assigned from the
  technician field. Material/labor activity does not resume On-Hold. `completed_at`
  is retained through Review and cleared by rollback/reopen. Closed is not a
  stored status: it is `archived_at`.
- Closing requires Admin+ and a Review work order, and the ordinary Work Orders
  page intentionally exposes no close action; Admin Review is the sole intended
  UI entry point. The row and lines remain, the number stays reserved, and it can
  return via `restore_work_order` or re-import. Closing never touches historical
  transactions, which retain their own `work_order_number`.
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
  surface as 404. Attribute edits are Supervisor+; close/archive is Admin+ and
  Review-only; an assignee must be a technician.

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
| Void transaction | supervisor+ |
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
| Work Orders list/get/items | any authenticated user, server-scoped (technician: assigned; supervisor: created OR routed via `supervisor_id`; admin/owner: all) |
| Edit Work Order notes / entry mode / Set In-Progress / Mark Completed | any authenticated in-scope user |
| Import work orders (CSV) | admin+ |
| Export work orders (CSV, full or For Client) | admin+, server-scoped |
| Edit work-order attributes / assign / rollback / On-Hold | supervisor+ (scoped); creation is import-only |
| Admin Review page / receipt | admin+; lists every live Review work order |
| Close/archive a work order | admin+ (scoped), Review status only; UI action lives in Admin Review |
| Set work-order line billing override | admin+ (scoped) |
| Scan-gate work-order cards | any authenticated user (scoped Created/Assigned/In-Progress list); In-Progress starts a batch, earlier states prompt to open Work Orders and set In-Progress |
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
- The `/work-orders` routes DO add real per-row creator/assignee scope checks
  (`services.work_orders`), because technicians reach them. A work order's
  `status`/`entry_mode`/materials are editable by any in-scope user; identity,
  location, and assignment edits require supervisor+.

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
- Full names are not unique. Two active supervisors with the same normalized
  first + last name are intentionally ambiguous during CSV routing.

Password hash format: `scrypt$n$r$p$salt_hex$hash_hex`.

### `sessions`

Fields: `token`, `user_id`, `created_at`, `expires_at`.

Rules:

- `token` is the opaque cookie value and primary key.
- `user_id` cascades on user delete.
- `expires_at = NULL` means browser-session lifetime.
- remembered sessions get a 12-hour absolute cap.
- there is no idle timeout.

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
  default to Created; technician assignment derives Assigned, and the first
  material/labor activity derives In-Progress. Migration `f4c6e8a0b2d3` added
  the five-state lifecycle, while `f5d7f9b1c3e4` aligned existing pre-work rows
  with technician assignment.
- `entry_mode` (`dispense` / `retroactive`) is the default mode for newly logged
  materials.
- `notes` is nullable free-form text on the work order. Blank saves normalize to
  NULL; any in-scope user may replace or clear it from the expanded card.
- `work_order_technicians` is the authoritative plural assignment relation and
  drives technician visibility (`domain.work_orders.can_view_work_order`).
  `assigned_to_id` remains a compatibility mirror of the first selected
  technician for Mass Stage and older clients.
- Soft delete via `archived_at` is the Closed state; the number stays reserved
  and material lines are kept. Closing is Admin+, requires Review, and is absent
  from the ordinary Work Orders page. A closed work order is invisible to list
  and detail loads, so it comes back only through `restore_work_order`
  (`POST /work-orders/{id}/restore`, Supervisor+) or re-import — referencing it
  no longer revives it. `lookup_work_order` is the one read that reports a closed
  work order so History can offer restore.
- References fill blank attributes but never overwrite non-blank ones; explicit
  edits (`update_work_order`) overwrite.
- **CSV-import schema (the new default source of truth).** The mass work-order
  export is bulk-imported via `POST /work-orders/import` (Admin+). Its columns
  land on `location` (raw LOCATION string, deliberately unparsed), `output_to`,
  `vendor_assignee` (the raw "ASSIGNED TO" contact -- a vendor name, NOT a system
  user), `service_type`, `schedule_date` (raw; some rows carry a time), and
  `description` (SYMPTOM/TASK). All nullable; a hand-created work order leaves
  them empty. Import funnels each row through `get_or_create_work_order` by
  number, so a re-upload is idempotent (fill-blanks -- never duplicates, never
  clobbers a manual edit).
- `supervisor_id` is the supervisor a work order is routed to. Import sets it by
  matching the normalized `vendor_assignee` name to an active supervisor's
  first + last name (`services.work_orders._supervisor_lookup`). Missing,
  unmatched, incomplete, archived, non-supervisor, or duplicate/ambiguous names
  import cleanly as unassigned (`NULL`); an Admin can route one later via
  `update_work_order`. Supervisor routing does not change lifecycle status.
  The plural technician set advances a Created row to Assigned when non-empty
  and returns an Assigned row to Created when cleared, while later lifecycle
  states never rewind automatically. `supervisor_id` drives
  visibility additively with `created_by_id` (see
  `can_view_work_order`): a supervisor sees work orders they created OR are
  routed to them.
- `legacy` marks a pre-import work order. The import migration
  (`f2a4c6b8d0e1`) set `legacy=true` on every then-existing row and NULLed its
  old descriptive attributes (`community`/`building_number`/`unit_number`/
  `description`), keeping only `number`, `status`, assignment, and its
  `work_order_items` -- so an already-priced-out work order stays fully
  searchable, just with empty new-schema fields. Unlike `archived_at`, `legacy`
  does NOT hide the row from lists/search.

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
  to carry multiple unique technicians. Work-order deletion cascades; removing
  an assignment does not remove that technician's historical labor.
- Supervisor+ replaces the complete assignment set through
  `PATCH /work-orders/{id}` with `assigned_to_ids`. Every assigned technician can
  list and act on the work order. The legacy singular request remains accepted
  for compatibility.

### `work_order_labor`

Fields: `id`, `work_order_id`, `technician_id`, `minutes`, `recorded_by_id`,
`created_at`, `updated_at`.

Rules:

- Each row records positive whole-minute actual labor attributed to a technician
  assigned to the work order. Technicians may add/edit/remove only their own
  entries; Supervisor+ may manage entries for any assigned technician.
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
| GET | `/db-test` | admin+ | database/user probe |

### Auth

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| POST | `/auth/login` | public | authenticate, create session, set cookie |
| POST | `/auth/logout` | session | delete session, clear cookie |
| GET | `/auth/me` | session | return username plus first/last/full display name, role, and profile timestamps |

### Items

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| POST | `/items/` | admin+ | create item |
| GET | `/items/` | session | list non-archived items newest-first; optional `q` performs case-insensitive literal substring search on name/primary barcode; blank `q` returns no rows |
| GET | `/items/search-index` | session | lightweight live-item projection containing only name and primary barcode, ordered by name/barcode |
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
| PATCH | `/users/{user_id}/name` | self or actor outranks target | replace required first + last name; legacy-account remediation |
| POST | `/users/{user_id}/reset-password` | actor outranks target | reset password |
| POST | `/users/{user_id}/archive` | actor outranks target | archive (soft delete) user; revokes sessions |
| POST | `/users/{user_id}/restore` | actor outranks target | reactivate archived user |
| DELETE | `/users/{user_id}` | actor outranks target | hard delete unreferenced user |

### Transactions And History

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| POST | `/transactions/` | session plus direction rule | create stock/dispense |
| POST | `/transactions/adjust` | admin+ | absolute count correction |
| PATCH | `/transactions/{transaction_id}/billing` | admin+ | set/clear billing override |
| DELETE | `/transactions/{transaction_id}` | supervisor+ | void transaction and reverse stock effect |
| GET | `/transactions/` | supervisor+ | paginated history, voided rows excluded |

History filters:

- `item_id`
- `user_id`
- `work_order_number`
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
Created/Assigned shows a confirmation and can navigate to the expanded Work
Order card so the user can set it In-Progress first.

### Work Orders

List/get/items are open to any authenticated user but **server-scoped**: a
technician sees/acts on only work orders assigned to them, a supervisor only
ones they created or routed to them, admin/owner all. Attribute edits / restore
are Supervisor+; closing is Admin+ and Review-only. Out-of-scope, closed, or
unknown work orders return 404. **There is no create route** — the CSV import is
the only way in.

| Method | Path | Gate | Behavior |
| --- | --- | --- | --- |
| GET | `/work-orders/` | session scoped | list live Created through Review work orders; `status`, `q` (WO# search), `limit` (cap to N newest) filters |
| POST | `/work-orders/import` | admin+ | bulk-import the mass CSV export (multipart); find-or-create per number; **the only path that creates a work order**; returns created/opened/matched/skipped counts |
| GET | `/work-orders/lookup?number=` | supervisor+ scoped | does this number name a work order, and is it archived? the one read that reports an archived one, so History can offer a restore |
| GET | `/work-orders/{id}` | session scoped | work-order detail + free-form notes + logged materials + labor totals |
| PATCH | `/work-orders/{id}` | session scoped; attr/assignee/manual rollback edits supervisor+ | save notes/entry mode, Set In-Progress, Mark Completed, or write Supervisor+ rollback/On-Hold/details edits |
| POST | `/work-orders/{id}/archive` | admin+ scoped | close a Review work order via soft archive (number reserved, lines kept, transactions untouched) |
| POST | `/work-orders/{id}/restore` | supervisor+ scoped | un-archive; the undo for archive, and the only way back short of a re-import |
| POST | `/work-orders/{id}/items` | session scoped | log a material (mode = work order's entry_mode); upsert by item |
| PATCH | `/work-orders/{id}/items/{wo_item_id}` | session scoped | edit a material's quantity (dispense lines auto-correct stock) |
| PATCH | `/work-orders/{id}/items/{wo_item_id}/billing` | admin+ scoped | set/clear the line's billing override (bill partial / zero / full) |
| DELETE | `/work-orders/{id}/items/{wo_item_id}` | session scoped | remove a material (dispense lines return stock; voids the linked txn) |
| POST | `/work-orders/{id}/labor` | session scoped | add positive whole-minute labor for an assigned technician; technicians are self-only |
| PATCH | `/work-orders/{id}/labor/{labor_id}` | session scoped | replace actual minutes; technicians are self-only |
| DELETE | `/work-orders/{id}/labor/{labor_id}` | session scoped | remove an entry; technicians are self-only; status does not rewind |

The `POST /transactions/` body now also accepts `work_order_id` (from a scanned
card); a free-text `work_order_number` from a Supervisor+ is *resolved* to an
already-imported work order, and 404s if there is none (it used to be
find-or-created).

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
- Opening Find Item loads only `/items/search-index` (name + primary barcode)
  for input suggestions and renders no item cards. Typing alone does not query
  or render. Search/Enter calls `/items/?q=...` across the full live dataset;
  Load All Items calls the backward-compatible unfiltered `/items/` feed.
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
  work order (id + number). Tapping Created/Assigned shows a confirmation; accept
  navigates to and expands that Work Order so the user can click Set In-Progress,
  while cancel leaves the gate unchanged.
- Supervisor+ sees a compact work-order-number search card above the work-order
  cards. Typing is a debounced live filter through
  `/work-orders/?q=`; it only narrows the scoped ready cards and never creates a
  work order. Selecting a filtered In-Progress card starts the batch; an earlier
  state uses the same redirect prompt. Stale request
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
- Unknown barcode does not offer create-item shortcut in this flow.
- Continuous live scan uses dwell and same-barcode cooldown to prevent double
  commits.

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

- Any authenticated role, server-scoped (technician sees assigned, supervisor
  created, admin/owner all). Reached via the nav button or a Unit click in the
  Mass Stage tree.
- Admin+ get an "Import work orders" section (file picker → `apiImportWorkOrders`
  → summary of created/updated/routed/skipped counts, then the list reloads). The
  file input accepts `.csv`; the button re-enables and clears after each run.
- **Import-only: there is no "New work order" form.** The CSV import is the only
  way a work order appears here or anywhere else.
- A card body opens on a read-only block of the work order's filled-in fields
  (location, service type, schedule, output-to, vendor contact, symptom/task,
  supervisor, technicians — blank ones are omitted), plus a "Legacy" tag on
  pre-import cards.
- Supervisor+ get an **"Edit details"** button in the card's control row. The
  editor is hidden until it is clicked, and opening it hides the read-only block,
  so a card stays a compact summary until an edit is actually intended. It edits
  the imported fields (location, service type, schedule date, output to, vendor
  contact, symptom/task), routing (supervisor select + multi-technician
  checkboxes), and
  a status selector. For Created through Completed it offers only the current or
  earlier lifecycle steps plus On-Hold; an On-Hold row can resume to the
  appropriate non-Review step. Created/Assigned remains technician-derived.
  Review is read-only here and retains its existing Reopen action. Save details /
  Cancel persist or discard the editor; "Close editor" only hides the panel.
  Community/building/unit inputs appear only on a work order that still carries
  those legacy values. The **number is not editable** — it is what the import
  matches on, so renaming it would split the work order in two on the next
  import.
- Filter by status (All / Created / Assigned / In-Progress / On-Hold / Completed / Review),
  then search by number.
- The list shows only the 10 most-recently-created work orders by default (keeps
  the page fast as the archive grows); a "Show all" control drops the cap and a
  "Show recent only" control restores it. A search always queries the full set, and
  a status-filter change resets to the capped browse (the cap is browse-only).
- Cards are collapsible and their full collapsed background communicates status:
  Created gray, Assigned red, In-Progress yellow, On-Hold orange, Completed blue,
  Review green, with contrasting text. Expanded bodies return to a white form surface. The
  body has a mode selector and status-appropriate actions: an in-scope user sees
  Set In-Progress on Created/Assigned and can Mark completed from In-Progress;
  only Supervisor+ sees Send to Review on Completed after reviewing the work and
  must confirm readiness in a pop-up; that transition places it in the final
  Admin Review queue. Supervisor+ can
  also Reopen. Created/Assigned note that material/labor activity also starts
  work automatically; On-Hold explains that only a supervisor can resume or roll it back. The
  body also has the Supervisor+ "Edit details" toggle, a free-form Notes section
  with Save notes for every in-scope role, and logged materials. Directly below
  material selection is per-technician labor tracking: actual hours are stored
  as whole minutes, the combined duration displays its rounded 30-minute billing
  total, technicians manage only their own rows, and Supervisor+ can select any
  assigned technician. There is
  deliberately no close/archive action on this page.
- Closing keeps the row, material lines, and transactions, but hides the work
  order from live views. `POST .../archive` requires Admin+ and Review; the
  Admin Review page owns this action. History can still find transactions by
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
  confirms, then calls the existing Review-only Admin+ archive endpoint. Either
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
  subordinate rows. It writes through `PATCH /users/{id}/name`; this is how
  pre-migration accounts become eligible for full-name CSV routing.
- Create-user dropdown offers only subordinate roles.
- Row reset/archive/restore actions appear only for users the actor outranks.
- Password reset uses prompt and requires min length 4.
- The 🗑️ action archives (soft delete): the user can no longer log in but
  their history is kept and they can be restored. Archived rows render
  dimmed with an "(archived)" tag and a Restore action.
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
- `list_item_search_index` projects only live item names and primary barcodes,
  ordered by name/barcode, for Find Item suggestions.
- `get_item_by_barcode` resolves primary or additional barcode for live items.
- `create_item` checks barcode across primary and additional code tables.
- `replace_barcodes` diffs child rows to avoid transient unique conflicts.
- `delete_item` archives by timestamp; hard delete is not normal path.
- `update_item` is a partial update via a `_UNSET` sentinel: only the
  fields the router forwards (`model_dump(exclude_unset=True)`) are
  written, and an explicit `None` clears nullable `price`/`product_link`.
- `_item_response` flattens additional barcode objects to `list[str]` and
  redacts price/link below admin.

### Transactions/Billing/History

Files: `domain/quantity.py`, `domain/billing.py`, `services/transactions.py`,
`services/history.py`, `routers/transactions.py`, `schemas/transactions.py`.

Behavior:

- `apply_transaction` locks item row, applies stock/dispense, inserts row
  with `unit_price` snapshotted from the locked item.
- `apply_correction` locks item row, computes signed delta, inserts `adjust`
  (no `unit_price` snapshot).
- `void_transaction` locks transaction row then item row, reverses effect.
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
  the one row, creating it if new: fills blank attributes, restores an archived
  match, validates the assignee is a technician. **Reached only from the CSV
  import** — it is the single creation path in the system. Every new row starts
  Created; supervisor-name routing affects `supervisor_id`/visibility, not status.
- `resolve_work_order` is what every other surface (the free-text transaction
  gate, Mass Stage) uses: same fill-blanks merge, but a number that names nothing
  — or names an archived work order — raises `WorkOrderNotFoundError` (404) with a
  message saying which. Work orders are import-only, so a reference cannot create.
- `lookup_work_order` returns the scoped row *including an archived one* (the one
  read that sees through the archive); `restore_work_order` clears `archived_at`.
  Together they back History's "this number is archived — restore it?" prompt,
  which is the undo for archive now that nothing can re-create a work order.
- `list_work_orders` is scoped (technician/supervisor/admin), excludes archived,
  filters by status, and searches the number case-insensitively.
- `update_work_order` overwrites supplied fields, including nullable free-form
  `notes`. `assigned_to_ids` replaces the normalized assignment set while
  maintaining the singular compatibility mirror. Setting/clearing the plural
  set reconciles Created/Assigned;
  an explicit rollback to either pre-work value is normalized again after the
  assignment edit, so the pair cannot contradict technician presence.
  Supervisor routing is independent. Completed and Review retain `completed_at`,
  while On-Hold/rollback/reopen clears it. The router permits any in-scope user
  to save notes, change entry mode, set In-Progress, or mark Completed, but
  requires Supervisor+ for every other manual status change. A number collision
  raises 400.
- `archive_work_order` accepts only Review and sets `archived_at`; the router
  requires Admin+. This is the stored Closed state.
- `add_work_order_item` locks the item row, writes a `dispense` transaction
  (`affects_stock` per the work order's mode) and the matching line via
  `attach_dispense_line`. That shared line-attachment path advances a pre-work
  row to In-Progress; it leaves On-Hold unchanged.
  `update_work_order_item` corrects stock by the delta
  and appends one reconciling `adjust` (the original scan rows stay intact -- it
  does NOT rewrite them); it clears a now-too-large `billable_quantity` override.
  `delete_work_order_item` returns the line's net units and voids its whole
  contributing transaction set.
- `set_work_order_item_billable` sets/clears a line's `billable_quantity`
  override (validated by `domain.billing.validate_billable_value`); it never
  touches stock. The router builds `materials_total` (sum of
  `effective_billable * unit_price`) and per-line `unit_price`/`billable_quantity`
  for Admin/Owner, redacted below.
- `add_work_order_labor` requires a current technician assignment, restricts a
  technician to their own identity, stores actual whole minutes, and applies the
  shared activity-derived status transition. Update/delete keep the technician
  self-only rule. Response totals use `billed_labor_minutes` and `labor_charge`:
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

Alembic head: `f7a9b1c3d5e6`.

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
| `f6e8a0b2d4f5` | nullable free-form `work_orders.notes`; On-Hold uses the existing application-validated text status column |
| `f7a9b1c3d5e6` | plural `work_order_technicians` assignments (backfilled from `assigned_to_id`) + per-technician `work_order_labor` minute entries |

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
| `test_user_archive.py` | user archive blocks login, revokes sessions, list scoping, and refuses archive until outstanding tool custody is returned |
| `test_item_update_partial.py` | partial item PATCH + clear price/link to null |
| `test_history_price_snapshot.py` | frozen `unit_price` snapshot; non-zero rows unchanged by price edits; snapshot 0 / NULL falls back to live price |
| `test_roles.py` | role hierarchy and transaction/user-management rules |
| `test_route_role_gates.py` | important route minimum-role gates |
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
| `test_mass_staging_load.py` | DB-backed slot load/return, add-work-order enforce-match + refusal of an unimported number, reuse |
| `test_work_orders_domain.py` | pure number normalization, six live statuses including stable On-Hold, plural technician-derived Created/Assigned state, activity-derived In-Progress, combined labor rounding/charge, fill-blanks, visibility scope |
| `test_work_orders_service.py` | DB-backed find-or-create, resolve-only attach, plural assignment/scope, per-technician labor/self-only writes, assignment/activity lifecycle derivation, On-Hold stability, status rollback/completion timing, free-form notes, Review-only close, archived history/restore, materials, scoping, and list filters/cap |
| `test_work_order_import.py` | CSV parsing/import, full-name supervisor routing independent of Created status, unmatched/ambiguous/archived/non-supervisor fallback, idempotence, and Admin gate |
| `test_work_order_name_responses.py` | work-order response exposes plural operational names, rounded labor detail/totals, and free-form notes while omitting login usernames |
| `test_work_order_line_sync.py` | line stays in sync across every stock-out path (scan/scan-and-go/load), accumulate, void walk-back, orphan self-heal |
| `test_work_order_billing.py` | line is the billing unit: work-order rows carry no per-row History charge (incl. the signed line-edit `adjust`); ad-hoc rows still billed; per-line override drives charge + `materials_total`, clears when quantity drops below it, redacts below Admin; history row exposes `work_order_id` |
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

## Documentation Policy

Keep this file optimized for technical execution:

- Prefer tables and routing maps over narrative.
- Keep source-of-truth statements tied to actual files.
- Document current behavior, not intended future behavior.
- Put implementation limitations in `Known Gaps`.
- Avoid reintroducing separate durable plan/spec/reference docs unless there is
  a temporary need and a cleanup date.
