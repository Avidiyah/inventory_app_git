# API Hardening Checklist

Audit date: 2026-08-07. Class A batch implemented and verified same day.

Source: code audit of `backend/app/` prompted by the question "what did we
commit to by building on FastAPI?" Extends the read-only grading pass recorded
at `Obsidian/.../reviews/app-grade-2026-08-06.md` (overall 7.0/10 — Scalability
6.5, Security 6.0, Professionalism 8.5).

Purpose: track framework-level and operational gaps that are *not* user-requested
features. Feature requests belong in `docs/improvement-tracker.md`; current
behavior lives in `docs/current-state.md` and `docs/project-summary.md`.

**Headline finding:** none of these are FastAPI limitations. Two were FastAPI
*idiom* errors that a more opinionated framework would not have permitted. The
rest are framework-independent and would exist identically in Django, Flask, or
Express.

## How this list is ordered

Items are grouped by **observability**, not by effort. The governing constraint
for this work is that no UI/UX behavior and no database schema may change, so
"can a user tell?" is the only ordering that matters.

- **Class A** — provably invisible. No reachable code path behaves differently.
- **Class B** — identical on the happy path; a new failure mode past a threshold.
- **Class C** — genuinely changes something observable. Needs a deliberate decision.
- **Excluded** — violates the no-schema / no-UX constraint. Not in scope.

Every item names the file and line. Tick items as they ship and record the
verification evidence inline, the way `improvement-tracker.md` notes do. Delete
items once shipped and verified rather than letting this drift into a stale
wishlist.

---

## Class A — Provably invisible

**Status: shipped 2026-08-07.** Verification evidence at the bottom of this
section.

- [x] **A1. Remove `async` from the two blocking upload routes**

  `backend/app/routers/barcodes.py:32` and
  `backend/app/routers/work_orders.py:269` were the only two `async def` routes
  in the app (the other 87 handlers were already correctly sync). Both did
  synchronous, blocking work directly on the event loop:

  - `decode_barcode` calls `barcodes_service.decode_image`
    (`services/barcodes.py:79-85`) — Pillow decode plus `pyzbar.decode` across
    every symbology, CPU-bound native work.
  - `import_work_orders` calls `wo_service.import_work_orders`, one long
    synchronous SQLAlchemy transaction over the whole CSV.

  While either ran, the server served **no other request**. The tell in both was
  `db: Session = Depends(get_db)` — a sync session — inside `async def`.

  Changed: dropped `async`, replaced `await file.read()` with `file.file.read()`
  on the same spooled upload. FastAPI now runs both in its threadpool.

  Why invisible: the only `await` in either handler was the file read. Request
  signature, parsed body, response model, status codes, `to_http` translation,
  and transaction boundary are all untouched.

  Test-harness follow-on: `tests/test_work_order_import.py` called the handler
  directly via `asyncio.run(...)`. Both call sites now call it directly and the
  unused `import asyncio` is gone. This is a calling-convention fix, not a
  behavior change — the failing run still produced the correct
  `WorkOrderImportResult(total=1, created=1, ...)`.

- [x] **A2. Configure the SQLAlchemy connection pool**

  `backend/app/database.py:50` created the engine with only `connect_timeout`.
  Added `pool_pre_ping=True` and `pool_recycle=300`.

  Render's free tier spins the service down when idle and the managed Postgres
  closes idle connections server-side, so a stale pooled connection surfaced as
  a user-facing error on the first request after a quiet period. Likely the
  cause of intermittent "first request after a while fails".

  Why invisible: connection-layer only. Changes which physical connection runs a
  query, never the query or its result.

- [x] **A3. Declare the TestClient HTTP dependency**

  Added `httpx2==2.9.1` to `backend/requirements-dev.txt`.

  **Correction to the 2026-08-06 grading doc's framing and to an earlier
  pass of this document.** The facts, verified:

  - `backend/venv` does **not** have an HTTP client installed. The grading doc
    was right that the dev environment lacks it. (An earlier revision of this
    file claimed the opposite; that check hit the *system* Python, not the venv.)
  - Starlette 1.2.1 requires **`httpx2`**, not the older `httpx` package.
    Importing `fastapi.testclient` without it raises
    `"requires the httpx2 package"`.
  - **No test imports TestClient.** The 478-test suite calls routers and
    services directly, which is why it passes without any HTTP client. So this
    was never blocking the suite — declaring it is what makes the first
    HTTP-level test possible without a detour.

  Installed into `backend/venv` to verify the pin (`pip install httpx2==2.9.1`,
  pulls `httpcore2`, `truststore`). Dev-only; not in the container, which copies
  `requirements.txt` alone.

- [x] **A4. Security response headers**

  `backend/app/main.py` — extended the existing `Permissions-Policy` middleware
  into `add_security_headers`, adding CSP, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, and HSTS gated on the
  existing `COOKIE_SECURE` flag (the signal the session cookie already uses to
  mean "this deployment is HTTPS"), so local http development is never sent an
  upgrade directive it cannot honour.

  **CSP was verified against the whole SPA before enabling.** This was the change
  most likely to break the UI; it does not. Measured across all frontend
  source, excluding `vendor/`:

  | Risk | Count |
  |---|---|
  | Inline `<script>` blocks | 0 — both tags in `shell-tail.html:103-104` use `src` |
  | Inline `on*` handlers | 0 |
  | Inline `style=` attributes | 0 |
  | `<style>` blocks | 0 |
  | `eval` / `new Function` | 0 |
  | `setAttribute("style")` / `cssText` / `insertRule` | 0 |
  | `<img>` tags / `.src =` assignments | 0 |
  | External resource loads | 0 |

  The live scanner is unaffected: it assigns a MediaStream to `video.srcObject`
  (`static/scan/barcode-decoder.js:113`), which CSP does not govern.

  **Known exception:** `static/scan-test.html:26` has a `<style>` block and
  `static/scan-test.js:23` an inline `style=`. That page is a standalone dev
  harness, not part of `SHELL_PARTS`, so CSP will affect it and nothing else.

- [x] **A5. Run the container as a non-root user**

  `backend/Dockerfile` — added `useradd --uid 10001 appuser`, `chown -R`, and
  `USER appuser` after the build steps.

  Verified nothing needs runtime write access: the app only reads `static/`,
  `PYTHONDONTWRITEBYTECODE=1` is already set, and `alembic upgrade head` writes
  to Postgres rather than to disk. Build-time steps still run as root.

- [x] **A6. Two-phase query for the capped work-order list**

  `backend/app/services/work_orders.py` — replaces the discarded "move sorting
  into SQL" item (see Excluded X2 for why that one is impossible here).

  Previously, `list_work_orders` applied five eager loads (two `joinedload`,
  three `selectinload`, including `WorkOrder.items`) across **every** matching
  row, then sorted in Python and sliced to `limit`. The default Work Orders
  browse returns 10 cards but hydrated the entire matching set to do it.

  Now, when `limit` is set, the ordering runs on a lightweight
  `(id, schedule_date, created_at)` projection and only the surviving rows are
  hydrated. When `limit` is `None` the old single-query path runs unchanged.

  Why invisible: same predicates, same comparison keys, same order, same
  entities. `_filter_and_sort_by_schedule` reads only `.schedule_date` and
  `.created_at`, so it works identically on the projection rows.
  `_scoped_to_user` uses only `.filter()` with correlated `EXISTS` — and
  `get_work_order_filter_options:873` already calls it with a column-only query,
  which is the in-codebase precedent for this. Eager loads are named once in
  `_LIST_EAGER_LOADS` so the two paths cannot drift.

### Verification evidence (Class A, 2026-08-07)

| Check | Expected | Result |
|---|---|---|
| Backend test suite | 478 pass | **478 passed** |
| OpenAPI operation count | 72 (unchanged) | **72** |
| Alembic head | `faa2c4e6b8d0`, no new revision | **`faa2c4e6b8d0 (head)`**, 0 migration files touched |
| JS syntax (`node --check`) | all pass | **32 non-vendor files, 0 failures** |
| Files touched under `backend/static/` | zero | **zero** |
| `async` routes remaining in app code | 0 | **0** (4 remaining are FastAPI's own `/docs`, `/redoc`, `/openapi.json` routes) |
| `GET /` still serves the shell | 200 | **200, 55,505 bytes, `Cache-Control: no-cache` preserved** |
| HSTS with `COOKIE_SECURE=false` | absent | **absent** |

Rows 3 and 5 are the direct guarantees against the two stated constraints: no
schema change, no UI change.

---

## Class B — New failure mode past a threshold

- [ ] **B1. Cap upload size on both upload routes** — *~30 min*

  No size limit exists anywhere in `backend/app/`. Both routes read the entire
  upload into memory unbounded.

  Below the cap: byte-identical behavior. Above it: a new 413. `api.js:35-41`
  surfaces `body.detail` to `format.formatError`, so a 413 carrying a `detail`
  string renders through the existing error path with no new UI code. Set the
  cap well above any real file (10 MB image / 25 MB CSV) and no user reaches it.

  This is a genuine new failure mode — small, bounded, and it replaces a worse
  one (unbounded memory plus a stalled server). Now that A1 has shipped, the
  stall half is already gone.

- [ ] **B2. Unauthenticated, DB-aware health check** — *~20 min*

  `render.yaml` sets `healthCheckPath: /`, which serves the SPA shell — a pure
  filesystem read (`main.py:125-128`). **Render reports the service healthy while
  Postgres is completely unreachable.** The existing DB probe `/db-test`
  (`main.py:131`) is Admin-gated and cannot serve this purpose.

  The endpoint itself is additive and invisible. Repointing `healthCheckPath` is
  not: deploys that previously "succeeded" while broken will now fail loudly.
  That is the fix, but it is a visible change in deploy behavior.

---

## Class C — Changes something observable

- [ ] **C1. Fold the five in-body 403 gates into `require_min_role`** — *~1 hr*

  41 endpoints use the declarative `Depends(require_min_role(...))`. Five gate
  inside the handler body, all in `routers/work_orders.py` (lines 279, 315, 365,
  563, 630). The in-body gate is invisible in the OpenAPI schema, runs after
  `get_db` opened a session and the body was parsed, and is opt-in — so a new
  `work-orders` endpoint inherits no protection by default.

  **The response body is byte-identical.** `auth_deps.py:63-66` raises
  `HTTPException(403, detail="You do not have permission to perform this
  action.")` — the exact string the inline gates use, verbatim. `api.js` surfaces
  the same message, so the UI copy is unchanged.

  **The one real difference:** as a dependency the role check runs *before*
  Pydantic validates the body, so a request that is both malformed **and**
  unauthorized returns 403 where it returns 422 today. No test in the suite
  asserts 422 anywhere, and the SPA never sends malformed bodies, so this is
  unreachable in practice — but it is a real semantic change.

  Leave `items.py:51` and `transactions.py:80,213` alone: those call
  `role_at_least` for price redaction (data shaping), not gating.

  Safety net: `tests/test_route_role_gates.py`.

- [ ] **C2. Eliminate the tool-custody N+1** — *~half day*

  `routers/tools.py:66-73` calls `_tool_response` per tool, and each invocation
  runs `_custody_query` (`services/tools.py:161-191`), a `GROUP BY` aggregate
  over `tool_transactions`. `list_tools` is unbounded, so 200 tools = 201
  queries per page load.

  **Riskier than a pure optimization.** `_custody_query` ends at
  `.having(net > 0)` with **no `ORDER BY`**, so the order of custody rows within
  a tool is whatever Postgres returns from the `GROUP BY`. Consolidating into one
  grouped query will very likely produce a different row order, which is visible
  in the Tools page custody list.

  Corollary: because there is no `ORDER BY` today, that order is *already*
  unspecified and could shift on its own after a vacuum or plan change. Fixing
  the N+1 means choosing an explicit order (user name), which is a one-time
  visible reshuffle that then stays stable forever. Not safe as a silent change;
  fine as a deliberate one.

- [ ] **C3. Login rate limiting** — *~half day*

  Zero references to rate limiting, throttling, or lockout in `backend/app/`.
  Combined with the four-character password minimum from the grading doc, login
  is unthrottled against weak credentials. Visibly locks users out by design —
  never bundle into an "invisible" batch.

- [ ] **C4. Close `/docs`, `/redoc`, `/openapi.json` in production** — *~15 min*

  `main.py:55` constructs `FastAPI(title=...)` with no `docs_url`/`redoc_url`/
  `openapi_url` override, so all three are public. Nothing in the codebase
  references them, so gating them behind an env flag breaks no code — but it
  removes URLs the owner may use directly. Owner's call.

---

## Excluded — violates the stated constraints

- [ ] **X1. Hash session tokens and sweep expired sessions** — **schema change**

  `models.py:249` makes the raw bearer token the **primary key**
  (`token = Column(Text, primary_key=True)`), generated at `services/auth.py:112`
  and looked up by equality at `auth.py:137`. Stored unhashed, so any read of
  that table is a full session takeover. Separately, non-remembered sessions get
  `expires_at = NULL` (`auth.py:115`) and nothing ever deletes them — the table
  grows monotonically and every row is a permanently valid credential.

  Requires a migration, and every user is logged out on deploy. Out of scope
  under the no-schema-change rule. Revisit deliberately — this is the most
  significant *security* item on the list.

  Related: `services/users.py::reset_password` documents an idle timeout that
  does not exist (grading-doc documentation gap).

- [ ] **X2. Move work-order sorting into SQL** — **not safely possible**

  `parse_schedule_date` (`domain/work_orders.py:148-175`) does three things SQL
  cannot easily replicate: regex-matches `M/D/YYYY` **or** ISO with optional
  trailing time; expands two-digit years (`year < 100 → +2000`); and catches
  `ValueError` on invalid calendar dates so Feb 30 becomes `None` rather than an
  error. The third is the blocker — Postgres `make_date` *raises* instead of
  returning NULL, so replicating this needs a PL/pgSQL function or a generated
  column. Both are schema changes, and `schedule_date` is deliberately raw text.

  **Superseded by A6**, which captures the available win (not hydrating the whole
  matching set to return 10 cards) with no behavior change at all.

- [ ] **X3. Paginate the unbounded collection endpoints** — **requires UI work**

  Only `work-orders` exposes a `limit`, and it is `Query(None, ge=1)` — no upper
  bound, no default. Items, tools, users, stages, and requests return everything.
  Changing what the API returns requires matching frontend work, so this is a
  feature, not hardening. Log it in `improvement-tracker.md` if wanted.

---

## No runtime effect — safe any time

- [ ] **N1. Add structured logging** — *~half day*

  There is **not a single `import logging`, logger call, or `print()` in the
  entire `backend/app/` tree.** No request IDs, no error logging, no metrics, no
  tracing. The only production artifact when something fails is uvicorn's access
  log. The grading doc's "limited observability" understates this: it is zero.
  Additive; requires only the discipline not to log secrets.

- [ ] **N2. Add CI** — *~1 day*

  No `.github/`. No formatter, linter, type checker, coverage enforcement, or
  dependency audit — no `pyproject.toml`, `ruff.toml`, `setup.cfg`, or
  `mypy.ini`. No `package.json`, so no frontend test harness.

  Wire pytest, `node --check`, Python compilation, Alembic head validation, and
  `pip-audit`. A3 unblocks any HTTP-level test this would run.

- [ ] **N3. Decide the multi-instance story before scaling horizontally**

  `backend/entrypoint.sh` runs `alembic upgrade head` on every cold start; its
  own comment acknowledges this cannot race on a single instance and must be
  revisited before adding a second. `render.yaml` is explicitly one free instance.

- [ ] **N4. Reconsider serving the SPA from the API process** — *deferred, by design*

  `main.py:84` mounts `NoCacheStaticFiles` with `Cache-Control: no-cache` on
  every asset, and `main.py:114-122` re-reads and concatenates 13 HTML fragments
  from disk on **every** request to `/`. Both are deliberate and solve the real
  blank-page stale-cache failure. The cost: every asset request is a Python
  round-trip, no CDN, no content hashing. Fine at current scale — the first thing
  to change if a CDN is ever introduced.

---

## Verified as non-issues

Recorded so these are not re-audited.

- **Pydantic v1→v2 migration debt** — none. `pydantic==2.13.4`, already current.
- **`BackgroundTasks` durability** — no usage anywhere, so no dropped-job
  exposure. (The CSV import is the workload that would normally live in a queue;
  it runs inline, now threadpooled rather than blocking the loop.)
- **Async correctness generally** — was 87 of 89 routes; now 89 of 89.
- **Error-translation consistency** — `to_http` used across every router
  (77 call sites). Not drifting.
- **API versioning** — routers mount at `/auth`, `/items`, `/work-orders` with no
  `/v1`. A non-issue while the SPA is the only client and ships in the same
  deploy. Becomes real the moment a mobile app or third-party integration
  consumes the API.
- **ORM and migrations** — SQLAlchemy 2.0, 31 Alembic revisions at head including
  data backfills. 15 indexes in `models.py`, including the functional unique
  index `uq_work_orders_number_ci`.
- **Concurrency** — `with_for_update()` row locking protects inventory and
  custody mutations.
- **Password hashing** — scrypt with `hmac.compare_digest`, no third-party
  dependency.
- **Layering** — `routers → services → domain → models` held consistently across
  nine resources. This is the discipline Django REST Framework would impose; it
  was imposed here by hand.

---

## Suggested next order

B2 → C1 → N1 → C2 → N2, then revisit X1 deliberately as its own piece of work
with a planned logout window. X1 is the highest-severity security item and the
only reason it is not first is the schema constraint.
