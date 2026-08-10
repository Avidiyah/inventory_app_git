# API Hardening Checklist

Audit date: 2026-08-07. Class A batch implemented and verified same day.
X1 + C3 (session token hashing, session expiry, login throttling) shipped
2026-08-09; the no-schema-change constraint was lifted deliberately for that
work. B2 (DB-aware health check) shipped the same day. N5 (free-Postgres
expiry) was closed the same day by upgrading the database to a paid plan —
**Tier 0 is now empty and the deadline is gone.** N2 (CI) shipped 2026-08-09
and, on its first run, produced a new item: **B4**, 23 known CVEs in `pillow`
and `starlette`. That is the gate doing its job before it had even been merged.
**B4 shipped the same day** and `pip-audit` is now blocking rather than
advisory. **N1 (structured logging) shipped 2026-08-09**, and **B1 (upload
size caps) shipped 2026-08-09** on top of it, so **Tier 1 now starts at C1.**

Re-reviewed 2026-08-09 against the promoted code graph at `d715545` (2,512 nodes
/ 5,790 edges), which covers structure the original file-by-file audit did not.
It surfaced four new items (B3, N5, N6, N7) and sharpened N2 and N4; it found
nothing that contradicts an existing entry. Note that the graph predates the
X1/C3 working-tree changes, so its view of `sessions` is the pre-hash schema —
the never-expiring-session defect it appears to show is the one X1 already fixed.

**Restructured 2026-08-09 into priority order** (was: grouped by observability
class). Every open item was re-verified against the working tree during that
pass; see *Re-verification, 2026-08-09* below. No item's substance changed —
only its position and one set of stale line numbers.

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

---

## How this list is ordered

Items are listed in the order they should be done. The top of this file is the
queue; read it top-down and take the first unticked item.

**Ranking criteria, applied in this order:**

1. **Irreversible loss outranks everything.** An item whose failure mode is
   *data gone* beats every item whose failure mode is *degraded*, and an item
   with an external clock beats one that will wait.
2. **Items that make other items safe to ship outrank the items they protect.**
   CI and logging are worth nothing on their own and are the precondition for
   trusting everything below them.
3. **Unauthenticated exposure outranks authenticated exposure.** A stranger
   reaching a code path is worse than a named, role-checked user with an audit
   trail reaching it.
4. **On a tie, cheaper first.** A 15-minute item does not queue behind a
   half-day item of equal value.

**Class tags are an attribute of an item, not its position.** The original
observability classes are preserved on each entry because they say what shipping
it costs, which is different from when to ship it:

- **Class A** — provably invisible. No reachable code path behaves differently.
- **Class B** — identical on the happy path; a new failure mode past a threshold.
- **Class C** — genuinely changes something observable. Needs a deliberate decision.
- **Class N** — no runtime effect at all. Safe to ship any time.
- **Class X** — was excluded under the original no-schema / no-UX constraint.

Item IDs (`B1`, `C1`, `N1`…) are stable and referenced from `docs/handoff.md`
and `docs/current-state.md`. They are **not** renumbered when priority changes;
the rank is the heading number, the ID is the identity.

Every item names the file and line. Tick items as they ship and record the
verification evidence inline, the way `improvement-tracker.md` notes do. Move
shipped items down to **Shipped** rather than leaving them in the queue.

### Re-verification, 2026-08-09

Every open item below was re-checked against the working tree during the
restructure. All still hold. One correction:

- **C1's line numbers had drifted ~7 lines** (279/315/365/563/630 → 286/322/372/
  570/636). The gates themselves are unchanged. Worth noting as evidence for the
  item: an in-body gate has no stable anchor, so it cannot be found except by
  reading the handler.

Spot-checks that returned exactly what the item claims: `import logging` /
logger / `print(` across `backend/app/` → **0 matches**; `.github/` → **absent**;
`render.yaml` → `plan: free` and `autoDeploy: true` both still set. **All three
`render.yaml`/`.github` facts were overtaken later the same day**: N5 moved the
database to a paid plan, and N2 created `.github/workflows/ci.yml` and set
`autoDeploy: false`. Both are recorded under *Shipped*. The zero-logging count
was N1's case and **that item has since shipped**, so it no longer holds.
`main.py:75` → `FastAPI(title="Inventory Management API")` with no URL overrides
(was `main.py:58` before N1 added the logging setup above it);
`services/work_orders.py` → **2,008 lines**, `views/workOrders.js` → 1,442,
`styles.css` → 2,489.

---

## Tier 0 — empty

N5 was the only item here and it is closed (see *Shipped*). Nothing on this list
now has an external clock; the queue below is ordered purely on merit.

---

## Tier 1 — Do next, in this order

### 1. C1 — Fold the five in-body 403 gates into `require_min_role`

- [ ] **Class C** · *~1 hr* · **response body is byte-identical**

41 endpoints use the declarative `Depends(require_min_role(...))`. Five gate
inside the handler body, all in `routers/work_orders.py` — lines **296, 333,
382, 580, 646**.

**These have now drifted twice in one day**: 279/315/365/563/630 originally,
then 286/322/372/570/636 at the restructure, then the numbers above once B1
added an import and a `responses={413: ...}` decorator argument above them. B1
did not touch a single one of the five gates. That is the item's argument
stated by the item's own line numbers: an in-body gate has no stable anchor, so
it cannot be located except by reading the handler, and any edit anywhere above
it moves it.

The in-body gate is invisible in the OpenAPI schema, runs after `get_db` opened
a session and the body was parsed, and is **opt-in** — so a new `work-orders`
endpoint inherits no protection by default.

**The response body is byte-identical.** `auth_deps.py:71-74` raises
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

**Interaction with B1**, which just shipped: the import route's gate is one of
the five, and B1 recorded and tested that it runs *before* that route's upload
size check. A dependency preserves that ordering — FastAPI solves declared
dependencies before it parses body parameters — but
`test_the_role_gate_still_runs_before_the_size_check` calls the handler
directly, so it has to move to the route level along with the gate rather than
be deleted as broken.

Safety net: `tests/test_route_role_gates.py`.

### 2. C4 — Close `/docs`, `/redoc`, `/openapi.json` in production

- [ ] **Class C** · *~15 min* · **decided 2026-08-10: close all three**

`main.py:75` constructs `FastAPI(title="Inventory Management API")` with no
`docs_url` / `redoc_url` / `openapi_url` override, so all three are public and
unauthenticated. Nothing in the codebase references them, so gating them behind
an env flag breaks no code — but it removes URLs the owner may use directly.

**The decision this item was waiting on has been made.** The owner chose to
**close all three in production**, gated on an env flag so they stay available
locally. This is no longer an open question; the item is now ordinary
implementation work sitting at #2 behind C1.

Two things to get right when it ships. **Pick the existing signal rather than
inventing one** — `COOKIE_SECURE` is already the flag that means "this
deployment is HTTPS/production" and A4 reused it for HSTS on exactly that
reasoning; adding a second, differently-named production flag would give the
codebase two answers to one question. And **the operation-count check survives, verified rather than assumed**: every
verification table in this file asserts "OpenAPI operations = 73" by calling
`app.openapi()`, and that still returns the full schema dict when `openapi_url`
is `None` — only the three *routes* disappear from `app.routes`. Checked
directly on 2026-08-10 against this venv's FastAPI. So closing C4 costs nothing
in verification coverage, which was the one thing that could have made a
15-minute item expensive.

**Why it ranks above C2** (criteria 3 and 4): it is the only remaining item that
exposes anything to an *unauthenticated* caller, and it is 15 minutes against
C2's half day.

### 3. C2 — Eliminate the tool-custody N+1

- [ ] **Class C** · *~half day* · **one-time visible reshuffle**

`routers/tools.py:73` calls `_tool_response` per tool, and each invocation runs
`_custody_query` (`services/tools.py:161-191`), a `GROUP BY` aggregate over
`tool_transactions`. `list_tools` is unbounded, so 200 tools = **201 queries per
page load.**

**Riskier than a pure optimization.** `_custody_query` ends at `.having(net > 0)`
with **no `ORDER BY`**, so the order of custody rows within a tool is whatever
Postgres returns from the `GROUP BY`. Consolidating into one grouped query will
very likely produce a different row order, which is visible in the Tools page
custody list.

Corollary: because there is no `ORDER BY` today, that order is *already*
unspecified and could shift on its own after a vacuum or plan change. Fixing the
N+1 means choosing an explicit order (user name), which is a one-time visible
reshuffle that then stays stable forever. Not safe as a silent change; fine as a
deliberate one.

### 4. B3 — No rate limiting outside the login route

- [ ] **Class B** · *logged 2026-08-09* · **authenticated callers only**

C3 shipped per-IP throttling on `POST /auth/login` and stopped there, correctly
— that was the credential-stuffing surface. But it is the only limited route in
the app: the two upload endpoints, every unbounded collection endpoint (X3), and
the CSV import all accept unlimited authenticated request volume.

**Why it ranks last in Tier 1** (criterion 3): an authenticated caller is
already a known, named, role-checked user with an audit trail, so the realistic
failure here is an accidental loop or a double-submit rather than an attack —
and B1's size cap bounds the expensive half of it more cheaply.

Worth revisiting if the API ever gains a non-SPA client (see the versioning note
under *Verified as non-issues* — the same trigger applies to both).

---

## Tier 2 — Standing notes

Not scheduled work. Each is a real property of the system with a named trigger
that would promote it into Tier 1. Recorded so the trigger is recognized when it
arrives rather than rediscovered.

### N3 — Decide the multi-instance story before scaling horizontally

- [ ] **Class N** · **trigger: adding a second instance**

`backend/entrypoint.sh` runs `alembic upgrade head` on every cold start; its own
comment acknowledges this cannot race on a single instance and must be revisited
before adding a second. `render.yaml` is explicitly one free instance.

Note that neither X1's session sweep nor C3's throttle inherits this problem:
both are DB-backed and driven by login traffic rather than by a scheduler, which
was a deliberate design choice at the time.

### N4 — Reconsider serving the SPA from the API process

- [ ] **Class N** · **trigger: introducing a CDN** · *deferred, by design*

`main.py:84` mounts `NoCacheStaticFiles` with `Cache-Control: no-cache` on every
asset, and `main.py:114-122` re-reads and concatenates 13 HTML fragments from
disk on **every** request to `/`. Both are deliberate and solve the real
blank-page stale-cache failure. The cost: every asset request is a Python
round-trip, no CDN, no content hashing. Fine at current scale — the first thing
to change if a CDN is ever introduced.

Scale note: `static/styles.css` is 2,489 lines, unminified, and re-fetched on
every navigation because of the blanket `no-cache`. That is the concrete cost of
this deliberate trade, and the number to watch.

### N6 — `services/work_orders.py` is 2,008 lines / 59 functions

- [ ] **Class N** · **trigger: none — this is a boundary rule, not a refactor**

Roughly 4× the next-largest service (`mass_staging.py`, 540) and larger than any
other file in the repo except `styles.css`. Its frontend counterpart
`static/views/workOrders.js` is 1,442 lines. Change risk in this codebase is
concentrated in these two files.

Not a defect — the layering it sits inside is sound, and the extraction target
already exists and already works: `domain/work_orders.py` (461 lines) holds the
pure rules, so the pattern is established rather than hypothetical.

This is a standing note that **further rule-shaped logic belongs behind that
boundary**, not a request to refactor the module wholesale. Splitting it for its
own sake would churn the highest-traffic file in the project for no behavior
change.

### N7 — `pyzbar` is the one dependency that can break a fresh environment

- [ ] **Class N** · **trigger: new dev machine, or a runtime/base-image change**

It wraps native `zbar`; the wheel bundles the DLLs but they need the Visual C++
2013 redistributable on Windows, and the failure surfaces as a missing
`libiconv.dll` on import — an error message that names neither `pyzbar` nor the
real cause.

Documented in `requirements.txt` and `docs/current-state.md`, noted here because
it is the only import in the tree that can fail for reasons outside pip's model,
and it takes down the **whole app at import time** rather than degrading barcode
decode alone. Containerized deploys are unaffected; this is a local-setup and
future-runtime-change hazard.

---

## Not in scope — violates the stated constraints

### X2 — Move work-order sorting into SQL — **not safely possible**

- [ ] **Class X** · **superseded by A6**

`parse_schedule_date` (`domain/work_orders.py:148-175`) does three things SQL
cannot easily replicate: regex-matches `M/D/YYYY` **or** ISO with optional
trailing time; expands two-digit years (`year < 100 → +2000`); and catches
`ValueError` on invalid calendar dates so Feb 30 becomes `None` rather than an
error. The third is the blocker — Postgres `make_date` *raises* instead of
returning NULL, so replicating this needs a PL/pgSQL function or a generated
column. Both are schema changes, and `schedule_date` is deliberately raw text.

**Superseded by A6**, which captures the available win (not hydrating the whole
matching set to return 10 cards) with no behavior change at all.

### X3 — Paginate the unbounded collection endpoints — **requires UI work**

- [ ] **Class X** · **this is a feature, not hardening**

Only `work-orders` exposes a `limit`, and it is `Query(None, ge=1)` — no upper
bound, no default. Items, tools, users, stages, and requests return everything.
Changing what the API returns requires matching frontend work, so this is a
feature, not hardening. Log it in `improvement-tracker.md` if wanted.

Referenced by B3, which names these endpoints as the unlimited-volume surface.

---

## Shipped

Kept with verification evidence intact. These no longer occupy a priority slot.

### B1 — Cap upload size on both upload routes

- [x] **Class B** · **shipped 2026-08-09** · closed an unbounded in-memory read

No size limit existed anywhere in `backend/app/`. Both upload routes did a bare
`file.file.read()` — `routers/barcodes.py:45` and `routers/work_orders.py:288`.
They now call `read_capped` from the new `app/routers/_uploads.py`, at **10 MB**
for the barcode image and **25 MB** for the work-order CSV. Below the cap the
behavior is byte-identical; above it, a 413 whose `detail` renders through the
existing frontend error path with **no UI change** — confirmed, zero files under
`backend/static/` were touched.

**The original item's framing was half wrong and the correction matters.** It
said both routes "read the entire upload into memory unbounded". By the time a
handler runs, Starlette's `MultiPartParser` has already received the whole body
and spooled the file part to a `SpooledTemporaryFile`, which switches to **disk**
past 1 MB. So receiving was bounded in memory already; it was unbounded on disk.
What was genuinely unbounded in memory is the `.read()` with no argument
materialising that spooled file as one `bytes` object and handing it to Pillow or
the CSV parser. That is what this closes.

**Consequence, stated plainly rather than left implied:** a client can still
*transmit* an arbitrarily large body, and this change cannot stop that — a
handler runs after the body is read. Refusing earlier would need a
`Content-Length` check in middleware, which was considered and **not** done: it
is a global interceptor with a misfire radius covering every route, against a
threat that is already bounded to disk. Logged here so the next reader does not
mistake the omission for an oversight.

**Four decisions worth keeping:**

1. **The size check is written twice, on purpose.** `UploadFile.size` is exact
   (the parser increments it as the part arrives) so an oversized upload is
   refused without reading anything — but it is `None` for any `UploadFile` not
   built by the multipart parser, so the bounded `read(limit + 1)` is the guard
   that cannot be bypassed. The first is an optimisation, the second is the
   guarantee. `test_an_upload_with_no_declared_size_is_still_capped` is what
   stops someone deleting the second as redundant.
2. **413 is raised directly, not through `to_http`.** An upload cap is a
   transport limit, not a business rule, and `domain/errors.py` is deliberately
   framework-agnostic — a byte count would be the first HTTP concept in a module
   whose entire point is not having any. `routers/work_orders.py` (403) and
   `routers/auth.py` (429) already raise directly for the same reason. The cost,
   accepted: this 413 is not in the `_STATUS_MAP` catalog, so
   `docs/endpoint-map.md` records it in the same trailing paragraph that already
   covers `auth_deps.py`'s 401/403.
3. **Constants, not env vars.** A cap that differs per environment is a cap
   nobody can reason about from the code. `LOG_LEVEL` set the opposite precedent
   one item earlier and was the right call there — verbosity is genuinely
   operational, an upload limit is a contract.
4. **Both routes declare `responses={413: ...}`**, so the new failure mode is
   visible in the OpenAPI schema. This is the same property C1 is about to
   argue for with the in-body 403 gates; adding a second undocumented in-body
   status while that item sits open would have been working against it.

**The role gate still runs first on the import route.** An unauthorised caller
gets 403 and learns nothing about the cap. That ordering is the one thing a
future edit could transpose silently, so
`test_the_role_gate_still_runs_before_the_size_check` pins it.

A rejection is logged (`event=upload.rejected_too_large`, with `size` and
`limit`). N1 shipping first is what made that a one-liner, and it is the reason
B1 ranked below N1 rather than above it: a 413 with no server-side trace leaves
"the scanner stopped working" with nothing behind it.

#### Verification evidence (B1, 2026-08-09)

| Check | Expected | Result |
|---|---|---|
| Backend test suite | 548 + new, zero failures | **562 passed in 42.97s** (548 existing + 14 new), zero skips |
| OpenAPI operation count | 73 (no route added) | **73** |
| 413 in the schema | documented on both upload routes | **both** present under `responses` |
| Alembic head | unchanged, no migration | **`fbc4e6a8d0f2 (head)`**, 0 migration files touched |
| Files touched under `backend/static/` | zero | **zero** — the 413 renders through `api.js::parseResponse` unchanged |
| Bytes held when rejecting | never more than `limit + 1` | **`read_sizes == [65]`** for a 64-byte cap; **`[]`** (no read at all) when the size is declared |
| Boundary | exactly `limit` accepted, `limit + 1` refused | **both** |
| Under-cap behavior | byte-identical payload reaches the service | **identical** on both routes |
| Role gate vs. size check order | 403 wins for a Technician | **403** |
| Python compile | clean | clean |
| `git diff --check` | clean | clean |
| Deployed CI run | all jobs green | **31389720697** — Static checks, Backend suite, Deploy to Render |
| Live `GET /healthz` after deploy | 200, DB reachable | **200 `{"status":"ok"}`**, `X-Request-ID: fec6d5fa1d68` |
| Owner browser validation | upload + import unchanged | **passed 2026-08-10** |

Verified by calling both handlers directly with constructed `UploadFile`s, per
the project's "the owner validates in the browser" rule.

**Owner browser validation passed 2026-08-10**, against the deployed service —
an ordinary barcode photo upload and an ordinary work-order CSV import both
behave as before. That closes B1 completely: the byte-identical-below-the-cap
claim is the one thing unit tests could assert but not *demonstrate* on real
files through the real multipart path, and it now has been.

### N1 — Add structured logging

- [x] **Class N** · **shipped 2026-08-09** · the diagnostic floor for everything
  else

`backend/app/` had **no `import logging`, logger call, or `print()` anywhere**.
It now has logfmt logging on stdout, a request id on every request, and
`user_id` on every authenticated one. New module: `app/logging_config.py`.

**One claim in the original item was slightly wrong and is worth correcting
rather than quietly dropping.** It said the only production artifact on failure
was uvicorn's access log. Starlette's `ServerErrorMiddleware` re-raises
(`middleware/errors.py:186`) and uvicorn's protocol logs `Exception in ASGI
application` with `exc_info` — so unhandled-500 tracebacks *did* reach Render,
just with no request id, user, or path. Everything **handled** was the genuinely
silent part: every `to_http` conversion, every 401/403/429, and `/healthz`'s 503.
The gap was correlation, not total darkness.

**Six decisions were the owner's, not defaults:**

1. **logfmt over JSON.** Render's log viewer is a plain text stream with
   substring search, and logfmt reads well there while staying greppable. The
   cost accepted: quoting/escaping is hand-rolled where `json.dumps` would be
   free and correct — which is why `_fmt_value` has its own parametrised test.
2. **Uvicorn's access log stays on.** Our `event=request` line is richer, but
   uvicorn's cannot fail: if the middleware breaks, it is the fallback that
   still shows traffic. Near-duplicate volume was judged the cheaper risk on a
   low-traffic service. `entrypoint.sh` is unchanged.
3. **A failed login logs the username only if the account exists**, else
   `user=unknown` (new `services.auth.username_exists`). Logging the submitted
   string verbatim would put a password in the logs, permanently, the first time
   a user types it into the username field. Accepted cost: a probe against a
   nonexistent username is logged as `unknown`, so the log shows the attempt and
   IP but not which invented names were tried.
4. **Infrastructure plus three call sites**, not a sweep of all 13 service
   modules — most of which would be guesswork before anything has needed
   debugging.
5. **`X-Request-ID` is echoed**, and an inbound one is never trusted.
6. **`LOG_LEVEL` env var**, default INFO, pinned in `render.yaml` beside
   `COOKIE_SECURE` / `SQL_ECHO`.

**Two implementation traps, both load-bearing:**

- **The context variable holds a mutable dict that is mutated in place.**
  Starlette's `BaseHTTPMiddleware` runs the downstream app in a separate anyio
  task, which receives a *copy* of the context — so `ContextVar.set()` inside
  `get_current_user` would never be visible to the middleware writing the
  completion line. Sharing one dict object is what makes `user_id=` appear
  there. `test_bind_user_mutates_in_place_rather_than_rebinding` guards it,
  because switching to `.set()` breaks nothing loudly; the id just vanishes.
- **The formatter reads the context variable directly instead of using a
  `logging.Filter`.** A filter on a handler is skipped by every other handler
  (pytest's `caplog` included); a filter on a logger does not run for records
  propagating up from child loggers. Reading at format time has neither hole.

#### Verification evidence (N1, 2026-08-09)

| Check | Expected | Result |
|---|---|---|
| Backend test suite | 523 + new, zero failures | **548 passed in 44.41s** (523 existing + 25 new) |
| OpenAPI operation count | 73 (no route added) | **73** |
| Alembic head | unchanged | **`fbc4e6a8d0f2 (head)`**, no migration |
| Middleware ordering | our scope outermost, security headers still applied | **both** — CSP and `X-Frame-Options` present on the probed response |
| `bind_user` across the anyio task boundary | `user_id` on the request line | **`user_id=99`** on the completion line |
| Application lines per request | exactly 1 | **1** |
| `X-Request-ID` header | present, matches the log | **`79e0eb074fff`**, identical in both |
| Query string in the log | absent | **absent** (`?secret=…` not emitted; path only) |
| Uvicorn `dictConfig` clobbering our handler | survives | **survives** — `LOGGING_CONFIG` has no `root` key, `disable_existing_loggers: False` |
| Uvicorn lines through our formatter | no (no double-print) | **no** — `uvicorn` sets `propagate=False` with its own handler |
| `/healthz` failure | driver detail logged, response still bare | **both** — `db.internal` in the log, absent from the 503 body |

Verified by driving the real ASGI stack directly rather than booting a server,
per the project's "the owner validates in the browser" rule.

### B4 — Upgrade `pillow` and `starlette` (23 known CVEs)

**Shipped 2026-08-09**, the same day N2's first `pip-audit` run created it — the
gate found it, and closing it was the first real use of what N2 built.

`pillow==12.2.0` → **12.3.0**, `starlette==1.2.1` → **1.3.1**. Pillow parses
attacker-supplied image data on the barcode upload path (`routers/barcodes.py`
→ `services/barcodes.py`) before `pyzbar` ever sees it, which is why this
outranked N1 on exposure; Starlette sits under every route in the app.

**Minimum fixing versions, not latest.** Starlette was already at 1.6.0
upstream. Three additional minors of ASGI-layer change buy no additional CVE
coverage on a Class B item, so the bump stops at the version that closes the
advisories. Pillow 12.3.0 happens to be both.

**The compatibility risk this item flagged did not materialize, and the reason
is worth recording.** The concern was that `fastapi==0.136.3` would pin a closed
Starlette range and fight the bump. It does not — its metadata declares
`starlette>=0.46.0` with **no upper bound**, so 1.3.1 is admissible. The related
A3 worry (`httpx2==2.9.1` pinned against Starlette 1.2.x for `TestClient`) is
also moot: **no test imports `TestClient`** — 0 matches across `backend/tests/`
— so that pin is declared but unexercised, exactly as A3 recorded.

**`pip-audit` is now blocking.** `continue-on-error: true` was removed from the
*Dependency audit* step in `.github/workflows/ci.yml`. It only ever shipped
advisory-only because gating on day one would have meant landing two dependency
upgrades inside the CI change itself. The baseline is triaged and clean, so any
new advisory is now a real regression and goes red.

#### Verification evidence (B4, 2026-08-09)

| Check | Expected | Result |
|---|---|---|
| `pip-audit` | 0 vulnerabilities | **"No known vulnerabilities found"** (was 23 across 2 packages) |
| Backend test suite | 523 passed, zero skips | **523 passed in 43.22s**, zero skips |
| Installed versions | pillow 12.3.0 / starlette 1.3.1 | **confirmed**, `fastapi` still 0.136.3 |
| Import smoke test | Pillow, pyzbar, starlette, fastapi | all import; `PIL.__version__` = 12.3.0, `pyzbar` OK |
| FastAPI ↔ Starlette constraint | no conflict | `fastapi` requires `starlette>=0.46.0`, **no upper bound** |
| Tests importing `TestClient` | 0 (so `httpx2` pin is moot) | **0** |
| OpenAPI operation count | 73 (unchanged) | **73**, `/healthz` present |
| Alembic head | unchanged, no new revision | **`fbc4e6a8d0f2 (head)`**, 0 migration files touched |
| Files touched under `backend/static/` | zero | **zero** |

Note the local venv left a locked `~il` directory in `site-packages` from the
Pillow replacement. Cosmetic and local only — `venv/` is gitignored and the
container installs fresh from `requirements.txt`, so nothing ships with it.

### N2 — Add CI

**Shipped 2026-08-09.** `render.yaml` set `autoDeploy: true` and there was no
`.github/`, so every push to `main` shipped to production having run
**nothing**. The 520-test suite was the largest asset in the repo and the only
thing that never executed on the path that mattered.

Shipped as `.github/workflows/ci.yml`, three jobs:

- **`backend`** — `postgres:16` service container, `alembic upgrade head`, then
  the full suite on **Python 3.12** (matching `Dockerfile:1`, not the 3.13 in
  the local venv — CI matches production, so local green is not automatically
  CI green).
- **`static`** — `node --check` across the non-vendor JS, `compileall` over
  `app/`, a single-Alembic-head assertion, a migration round-trip
  (`upgrade → downgrade -1 → upgrade`), and `pip-audit`.
- **`deploy`** — `needs: [backend, static]`, restricted to pushes on `main`,
  firing a Render deploy hook held in the `RENDER_DEPLOY_HOOK_URL` secret.
  `render.yaml` is now `autoDeploy: false`, so this hook is the only path to
  production.

  **Refined 2026-08-09:** the hook now fires only when `backend/**` or
  `render.yaml` changed, so docs and tooling commits no longer restart
  production. This is an allowlist of what `rootDir: backend` actually puts in
  the image, not a blocklist of doc paths — a blocklist would rot the first time
  a new top-level directory appeared. `paths-ignore` could not be used: it is a
  workflow-level trigger filter and would have skipped `backend` and `static`
  as well. Unclassifiable pushes deploy rather than skip, because a redundant
  deploy is cheaper than a silent production stall. The `needs:` gate is
  untouched.

**The defect this nearly shipped with.** Running the suite in CI is *not*
simply "run pytest". `tests/conftest.py` caught `OperationalError` and called
`pytest.skip`, and **244 of 425 test functions take the `db` fixture**. A
workflow with a syntactically valid but unreachable `DATABASE_URL` would have
gone green having exercised **43%** of the suite — automation that lies, which
is worse than the status quo of no automation that everyone knows about.

Fixed by `tests/_db_availability.py`: the skip now happens only outside CI, and
under `CI=true` an unreachable database raises. Local behavior is unchanged —
the contributor-without-Postgres path that motivated the skip still works.
Rejected alternative: asserting a minimum collected-test count, which encodes a
magic number that drifts every time a test is added.

**Two gates deliberately kept honest.** The JS-syntax step asserts the file
count is `> 0` rather than `== 32`: `xargs -r` skips `node` entirely on empty
input, so a broken `find` pattern would pass silently — but an exact count would
turn every new JS file red, reintroducing the same drifting-constant problem
rejected above. The Alembic head check asserts exactly `1`, because two heads
is never correct.

**Out of scope, deliberately:** no linter or formatter (introducing `ruff` here
produces a large mechanical diff that would bury the workflow), and `pip-audit`
runs `continue-on-error: true` until its baseline is triaged — see **B4**,
which that baseline created.

**N7 closed incidentally.** Installing `libzbar0` before `pip install` is the
first time the `pyzbar` native dependency has been handled outside a container
— exactly N7's named trigger ("a new dev machine, or a runtime/base-image
change"). Without it, `import app.main` fails and takes the whole suite down.

#### Two failure drills, one of which failed

Both gates were tested by breaking them on purpose rather than trusting them.

**The guard drill passed and was worth doing.** Overriding `DATABASE_URL` at the
*step* level (not the job level) left migrations working and isolated the
failure to the guard, producing `RuntimeError: Database unreachable in CI:
... database "wrong_db" does not exist` in the real runner. A job-level override
would have failed at `alembic upgrade head` one step earlier, proving the build
can go red but nothing about the guard.

**The deploy-gate drill was performed incorrectly and triggered a live deploy.**
To let `deploy` run on a pull request, its condition was temporarily changed to
`if: always()`. **`always()` overrides `needs`** — it means "run regardless of
whether the dependencies succeeded", the exact opposite of the property under
test. The run was cancelled, but `deploy` had already fired the hook
(`dep-d9shtqajnfac739h7jvg`). Because Render hooks build the branch configured
on the service, this deployed `main` at `873fef3` — already-verified code — and
the deploy came up healthy. Reverted in `0c35eb1`.

**Standing lesson, recorded because it generalizes:** any drill that requires
weakening the condition under test is not a drill of that condition. The deploy
gate is verified naturally on the first real red build, at no risk. `needs:`
with no `if` override is standard documented behavior; only `always()` defeats
it.

#### Verification evidence (N2, 2026-08-09)

| Check | Expected | Result |
|---|---|---|
| Suite in CI | 523 passed | **523 passed in 21.98s** |
| Suite locally | 523 passed (520 + 3 new), zero skips | **523 passed in 33.97s** |
| Guard fires on dead DB, `CI=true` | build fails | **`RuntimeError`, exit 1**, in the real runner |
| Guard still skips locally, no `CI` | skips, exit 0 | **7 skipped in 35.43s, exit 0** |
| Non-vendor JS files checked | 32 | **32**, `node --check` clean |
| Alembic heads | 1 (`fbc4e6a8d0f2`) | **1** |
| Migration round-trip | clean both ways | **clean** (`fbc4e6a8d0f2 → faa2c4e6b8d0 → head`) |
| `pip-audit` baseline | recorded + decision | **23 CVEs / 2 packages → logged as B4**, gate left advisory |
| Deploy gate, green path | `deploy` fires after both jobs pass | **confirmed on the merge to `main`** (run 31345792740 → `dep-d9si4efavr4c73bap2c0`, healthy) |
| Deploy gate, red path | red build cannot deploy | **not yet observed.** The merge proves `deploy` runs *after* success; it does not prove it is *blocked* by failure. That is the actual gate property and it is verified on the first real red build — deliberately not drilled, for the reason above. |

### N5 — Free-tier Postgres expiry — **resolved by upgrading to a paid plan**

**Closed 2026-08-09.** `inventory-db` is no longer on the free plan, so the
90-day expiry clock this item existed to track **no longer exists**. There is no
date left to log; the deadline was removed rather than met.

The item asked for two confirmations. Both are now satisfied, the second more
strongly than the item anticipated:

1. *Confirm the real expiry date.* Moot — a paid instance does not expire.
2. *Confirm a restorable backup exists.* **Point-in-time recovery is available
   to any moment within the last three days**, which is a stronger guarantee
   than the periodic dump the item had in mind: it covers partial corruption
   and bad migrations, not just total loss of the instance.

**What the 3-day window does and does not cover.** It is a recovery floor, not
an archive. Anything discovered more than three days after it happened is
outside it — a slow data-corruption bug, or a bad migration nobody noticed for a
week, is not recoverable this way. Worth knowing before treating PITR as a
general safety net; it is exactly the right protection for a bad deploy caught
the same day, which is the realistic failure mode here.

**Interaction with N2, which is now #1.** PITR is what makes `autoDeploy: true`
survivable today — a migration that corrupts data can be rolled back within the
window. That is a recovery path, not a gate: it bounds the damage after the fact
and costs a restore plus whatever writes happened in between. N2 is the item
that stops the bad deploy from shipping at all. The two are complements, and
having PITR does **not** reduce N2's priority.

**Still pinned as free:** the *web service* (`render.yaml:21`), which is a
latency characteristic (idle spin-down, ~30s cold start), already handled by
A2/B2 and never a data-loss risk. Only the database changed.

**Blueprint synced.** `render.yaml:13` now declares `plan: basic-256mb` on
`inventory-db` (was `plan: free` on line 9), so the checked-in blueprint matches
the live instance. Left drifting, the next blueprint sync would have been an
attempt to move a paid database back to a plan that expires.

**Superseded by the 2026-08-10 database cutover.** Production is now targeted at
the existing Render Postgres instance `inventory-db-copy` via
`fromDatabase.name` in `render.yaml`, and the original `inventory-db` is no
longer declared by the Blueprint. The paid-plan/PITR evidence above was recorded
for `inventory-db`; verify the copy's plan and recovery settings in the Render
dashboard before treating this N5 note as proof about the active production
database.

### X1 — Hash session tokens, cap every session, revoke on password reset

**Shipped 2026-08-09.** Was listed under *Excluded* because it needs a migration.
That exclusion was a property of the Class A batch's self-imposed constraint, not
of the item, and the constraint was lifted deliberately for this piece of work.

The defect: `models.py:249` made the raw bearer token the **primary key**
(`token = Column(Text, primary_key=True)`), stored unhashed, so any read of that
table was a full session takeover for every logged-in user. Worse, the *default*
login path (`remember=False`) set `expires_at = NULL` and nothing ever deleted
those rows — the table grew monotonically and every row was a permanently valid
credential, so the blast radius grew daily.

Shipped:

- `sessions.token` → `sessions.token_hash`, storing the **SHA-256** of the
  cookie value. SHA-256 rather than scrypt is deliberate: the token is 256 bits
  of CSPRNG output, so there is no guessable keyspace for a slow KDF to defend,
  and this hash runs on every authenticated request.
- `expires_at` is now **NOT NULL**. Every session has a 12h absolute cap;
  "remember this device" now changes only cookie persistence. Note the old
  behavior was inverted — ticking the box gave the *shorter*-lived credential.
- `sweep_expired_sessions` runs on every login. No scheduler, no background
  task, so this inherits none of N3's multi-instance coordination problem: rows
  can only accumulate at the rate of logins, and every login cleans up.
- `revoke_user_sessions` extracted and now also called by
  `services/users.py::reset_password`, which previously left sessions intact and
  justified it with an idle timeout that does not exist (migration
  `c7e9a1b3d5f8` removed the sliding window in June 2026). An admin resetting a
  compromised account's password now actually cuts off access.
- **No idle timeout was added.** That was considered and rejected: `c7e9a1b3d5f8`
  removed one deliberately, and the absolute cap alone fixes the immortal-session
  bug without re-litigating a settled decision or adding a per-request write.

**Correction to this document's earlier framing.** It claimed the migration
means "every user is logged out on deploy". That is true of the strategy chosen,
not inherent to the item — rewriting the existing tokens in place would have
preserved working cookies. Truncating was chosen *because* it is the only step
that destroys the accumulated backlog of never-expiring plaintext credentials.
The logout is the point, not the cost.

Still open and deliberately untouched: the four-character password minimum
(raising it invalidates existing passwords) and MFA.

### C3 — Login rate limiting

**Shipped 2026-08-09, with X1.** Was: zero references to rate limiting,
throttling, or lockout anywhere in `backend/app/`, against a four-character
password minimum.

Shipped as **exponential backoff, not account lockout**, keyed on
**(submitted username, client IP)**. The distinction is the whole design: a
hard per-username lockout is a denial-of-service weapon — anyone who knows the
crew's usernames could lock every one of them out at the start of a shift.
Including the IP means a remote attacker cannot delay the person standing in
the warehouse, and backoff means a real user who mistypes is never locked out
at all.

- `domain/login_throttle.py` — pure policy. 5 free attempts, then 5s doubling
  to a 15-minute ceiling (6th → 5s, 7th → 10s, 8th → 20s…), leaving a
  sustained attacker at roughly four guesses an hour.
- `services/login_throttle.py` + `LoginAttempt` — DB-backed counters, so the
  limit survives Render's idle spin-down and will work if a second instance
  ever appears (N3). Swept after 24h; deleted on successful login.
- Enforced by **429 + `Retry-After`**, never by sleeping — a sleeping handler
  holds a FastAPI threadpool slot (default 40), which would make the throttle
  itself a cheap resource-exhaustion lever.
- A wider per-IP layer exists but ships **disabled**
  (`LOGIN_THROTTLE_PER_IP`): it is the layer that would misfire into a
  crew-wide lockout if proxy headers were wrong. The (username, IP) layer is
  safe either way, because distinct usernames still get distinct counters.
- `entrypoint.sh` now passes `--proxy-headers --forwarded-allow-ips='*'` so
  `request.client` is the real caller rather than Render's proxy.

Frontend cost was one branch: `api.js` already surfaces `body.detail` for any
non-2xx, so `views/auth.js` only needed a `429` case beside its existing `401`.

The four-character password minimum is **not** addressed here — raising it
invalidates existing passwords, so it stays a deliberate deferral (recorded in
`docs/current-state.md` → Known Gaps).

#### Verification evidence (X1 + C3, 2026-08-09)

| Check | Expected | Result |
|---|---|---|
| Backend test suite | 478 prior + new | **514 passed** (36 new) |
| `test_user_archive.py` / `test_user_role_edit.py` | pass **unchanged** | pass, not edited |
| Alembic head | new revision | **`fbc4e6a8d0f2 (head)`** |
| Migration round-trip | `downgrade -1` then `upgrade head` | clean both ways |
| OpenAPI operation count | 72 (unchanged) | **72** |
| JS syntax (`node --check`) | all pass | **32 non-vendor files, 0 failures** |
| Python compile | clean | clean; `import app.main` OK (no import cycle) |
| `git diff --check` | clean | clean |
| Router smoke test | cookie set, raw token absent from table, 429 + `Retry-After` after the free window, other IP unaffected | all confirmed |
| Owner browser validation | all 7 manual checks | **passed 2026-08-09** |

Manual pass performed by the owner (browser click-through is owner-performed on
this project): plaintext token absent from `sessions`, remembered-cookie expiry,
server-side expiry deleting the row on read, password reset signing the target
out, throttle engaging with the correct copy, **a locked username not blocking a
different user** (the anti-DoS property), and the mid-batch resume path still
working across a forced session drop.

One behavior confirmed as intended rather than a defect: a throttled caller is
refused even with the correct password. The throttle would not stop a
brute-force that guesses right otherwise, and the wait at that point is 5
seconds.

### B2 — Unauthenticated, DB-aware health check

**Shipped 2026-08-09.** `render.yaml` pointed `healthCheckPath` at `/`, which
assembles the SPA shell from disk and never touches Postgres, so **Render
reported the service healthy while the database was completely unreachable.**
`/db-test` could not serve as the probe on two independent counts: it is
Admin-gated (a health checker sends no cookie, so it never gets past the 401 in
`get_current_user`), and it deliberately returns the database name and user.

Shipped:

- `database.check_connection()` — runs `SELECT 1` and returns **nothing**,
  beside `test_connection()` which returns `(database, user)`. The empty
  return is the point: this one's caller is unauthenticated. It goes through
  the pool, so it exercises the same path a real request takes; `pool_pre_ping`
  (A2) already issues a `SELECT 1` per checkout, so the marginal cost is
  negligible.
- `GET /healthz` in `main.py` — no dependencies, sync `def` (threadpooled, per
  A1, so a hung database cannot occupy the event loop). Returns
  `{"status": "ok"}` or **503 `Database unavailable.`**
- Catches `SQLAlchemyError`, **not** bare `Exception`, so a genuine bug in the
  handler still surfaces as a 500 rather than being laundered into a
  plausible-looking database outage.
- `render.yaml` repointed to `/healthz`. This is the visible half: deploys that
  previously went green while broken now fail loudly. That is the fix.

**Deliberately leaks nothing.** psycopg's `OperationalError` quotes the DSN
back — host, port, database, user — so the driver's message is caught and
discarded, never surfaced. Two of the six tests are regression guards rather
than behavior tests: one asserts no connection detail reaches the response
body, the other asserts the route's dependant tree is empty, so a future
"helpful" auth addition fails in the suite instead of silently breaking every
deploy's health check.

**Verified against Render's actual free-tier behavior:** its health polling
does not defeat idle spin-down (free services still sleep after ~15 min with
`healthCheckPath` set — that is why the external-ping workaround exists), and
nothing polls the container while it is asleep.

Direct follow-on: **N1**. The discarded driver exception is correct to withhold
from an unauthenticated caller, but it should be logged server-side, and today
there is nowhere for it to go.

#### Verification evidence (B2, 2026-08-09)

| Check | Expected | Result |
|---|---|---|
| Backend test suite | 514 prior + new | **520 passed** (6 new) |
| OpenAPI operation count | 73 (+1, intentional) | **73**, `/healthz` present in schema |
| Alembic head | unchanged, no new revision | **`fbc4e6a8d0f2 (head)`**, 0 migration files touched |
| Live call, database up | `{"status": "ok"}` | **`{'status': 'ok'}`** |
| Live call, database unreachable | 503, no leak | engine repointed at a dead port with a password in the DSN → **503 `Database unavailable.`**; `host`, `port`, `user`, `password`, and driver name all absent from the body |
| JS syntax (`node --check`) | all pass | **32 non-vendor files, 0 failures** |
| Files touched under `backend/static/` | zero | **zero** (`views/auth.js` shows modified from the X1+C3 batch, not this one) |
| Python compile | clean | clean |
| `git diff --check` | clean | clean |

### Class A batch (A1–A6) — provably invisible

**Shipped 2026-08-07.** All six were verified to have no reachable code path
that behaves differently.

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
  into SQL" item (see X2 for why that one is impossible here).

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

#### Verification evidence (Class A, 2026-08-07)

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

Rows 3 and 5 are the direct guarantees against the two stated constraints of
that batch: no schema change, no UI change.

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
  consumes the API — the same trigger as B3.
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
