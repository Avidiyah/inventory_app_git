# API Hardening Archive — shipped items

Every hardening item that has shipped, with its decision record and
verification evidence intact. **Split out of `docs/api-hardening-checklist.md`
on 2026-08-10**, when the archive had grown to 79% of that file and was sitting
between the reader and the queue.

Nothing here was edited in the move. This is the record, not the plan:

- for what is **open**, see `docs/open-work.md` (the index) or
  `docs/api-hardening-checklist.md` (the owning doc);
- for **current behavior and contracts**, `docs/current-state.md` is the only
  authority.

Entries are in the order they were written to the Shipped section, newest
first, which is roughly reverse-chronological by ship date.

---

## Shipped

Kept with verification evidence intact. These no longer occupy a priority slot.

### X3 — Bound the unbounded list endpoints

- [x] **Class X** · **shipped 2026-08-10** · *promoted from "Not in scope" the
  same day* · **shipped as a ceiling, not as pagination**

Six list endpoints returned their entire table; only `GET /work-orders/` took a
`limit`, and it was `Query(None, ge=1)` — no upper bound, no default. Now every
list is capped at **`MAX_LIST_ROWS = 5000`**, with truncation reported as an N1
line. New pure policy in `domain/list_limits.py`, applied through
`services/_list_cap.py`. **No frontend file changed.**

**The item asked for pagination and pagination is deliberately not what
shipped.** Two things found by measuring first:

1. **The symptom is not occurring.** The owner confirmed production holds
   *hundreds* of rows. The item's premise came from reading code, exactly as
   C2's "200 tools = 201 queries" did.
2. **`/items/` and `/users/` are not merely list views.** They are bulk
   reference-data loads backing *client-side* search: `transactions.js:140`
   (Scan/Stock manual entry) and `history.js:387` each fetch every item once
   per session and filter locally on each keystroke, and `massStage.js`,
   `workOrders.js` and `tools.js` do the same for items/users. Paginating them
   would have meant rewriting core field workflow — to fix a problem nobody
   has.

So the ceiling is set far above anything real and does two things no caller
notices: it bounds the blast radius of a runaway query or a bad import, and it
**emits a trigger**. `event=list.truncated list=<name> cap=5000` is the signal
that real pagination is finally needed, and it names *which* list fired so the
work is scoped by evidence rather than doing all six at once.

Five decisions worth not re-deriving:

- **Fetch `CAP + 1`, not `CAP`.** B1's `read_capped` established this: the
  extra row is what distinguishes "exactly at the ceiling" from "more than the
  ceiling", so truncation is detectable without a second `COUNT(*)`. It also
  means the five SQL paths bound the **database work**, not just the response.
- **Exactly `MAX_LIST_ROWS` is not truncation.** That is a complete result
  sitting on the boundary; reporting it would cry wolf and train people to
  ignore the one signal this item produces.
- **`GET /work-orders/` caps differently and cannot be made uniform.** Its
  ordering is decided in Python because `schedule_date` is raw text (X2), so
  the ceiling bounds the response, not the query. Its omitted-`limit` call also
  no longer takes a separate uncapped branch — it now runs A6's
  rank-then-hydrate path universally. Same rows, same order, strictly less
  loading, pinned by
  `test_omitting_limit_still_returns_every_matching_row_in_the_same_order`.
- **A caller's own smaller `limit` is never reported as truncation.** The Work
  Orders page asking for 10 cards and getting 10 is not the ceiling biting.
- **The Admin+ CSV export is exempt, deliberately.** `current-state.md`
  documents it as the uncapped filtered set, and a CSV silently missing rows
  while looking complete is a records problem, not a performance one. The
  exemption carries a comment saying so, because it looks like an oversight.

**`GET /items/search-index` was deleted rather than capped** — route, schema,
service function and its test assertions. `grep` over `backend/static/` found
zero callers; it returned every live item name and barcode to any signed-in user
and served nothing. **OpenAPI 73 → 72.** The cheapest fix for an unbounded
endpoint is not having one.

`MAX_LIST_ROWS` is a **chosen** number, not a fitted one — same status as B3's
60/s. Roughly 10–50× current headroom.

#### Verification evidence (X3, 2026-08-10)

| Check | Result |
|---|---|
| Full backend suite | **659 passed** (632 + 27 new) |
| New tests | 9 pure policy, 10 cap helper, 5 wiring (DB), 3 work-orders |
| OpenAPI operations | **72** — was 73; `/items/search-index` unmounted |
| Alembic head | `fbc4e6a8d0f2` — untouched, no migration |
| `git diff --check` / `compileall` | clean |
| Frontend changed | **none** — `git status backend/static/` empty |

The wiring tests **lower the ceiling to 1** rather than inserting 5,001 rows
(`_list_cap` and `fetch_limit` both read `MAX_LIST_ROWS` at call time), so they
are fast and stay valid if the number ever moves.

**Not yet deployed or browser-validated.** This entry records a local result
only.

### B3 — Rate limiting beyond the login route

- [x] **Class B** · **shipped 2026-08-10** · owner-specified cap

`POST /auth/login` was the only limited route in the app. A new `rate_limit`
middleware in `main.py` now caps **every non-exempt path at 60 requests per
second per caller**, returning 429 with `Retry-After: 1`. Policy in
`domain/rate_limit.py` (pure), counters in `services/rate_limit.py` (in memory).

**The cap and its scope were the owner's call, not a derived number.** The
original plan was to measure real volume from N1's `event=request` lines first
and possibly demote the item to a Tier 2 note. The owner specified 60/s per
user, API routes only, before that measurement was run. Recorded plainly because
the number is therefore a policy decision rather than a fitted one — anyone
tuning it later is changing a choice, not correcting an estimate.

**Measurement still changed the design, in the one place it mattered.** Driving
the ASGI stack showed that `/` and `/static/*` emit `event=request` lines
through the same middleware chain as the API, and that a cold SPA load is ~35
requests (33-module ES graph + `styles.css` + the 441 KB zxing bundle) fired
nearly at once. Two of those inside one second is 70. So:

- a **global** 60/s would have been tripped by two people refreshing at a shift
  change, serving a 429 for a JavaScript module — i.e. the blank page this app
  already has history with;
- `/`, `/static/*` and `/healthz` are therefore **exempt: neither counted nor
  refused**. Not counted, so page loads cannot spend the budget. Not refused, so
  an over-limit caller can still load the page that fixes it, and a busy caller
  cannot fail a deploy through `render.yaml`'s `healthCheckPath`.

Four decisions worth not re-deriving:

- **Keyed by session, not user id.** The middleware runs before route
  dependencies resolve, so `auth_deps.get_current_user` has not run and no user
  id exists yet; the session cookie is the only identity available that early.
  One person on a phone and a laptop gets two budgets, which is correct for
  catching a runaway *client*. The token is SHA-256'd before use as a dict key,
  for the reason X1 hashed it in the database.
- **In memory, where C3 used Postgres, and the asymmetry is the point.** A
  failed-login counter must survive a restart or an attacker resets it by
  waiting out a spin-down. This window is one second, so nothing older than that
  was worth keeping and a restart loses nothing. A Postgres write per request on
  `basic-256mb` would cost more than the runaway client it catches.
- **Refused requests are not counted.** Otherwise a client already looping holds
  its own window open and a one-second limit becomes an unbounded lockout.
  Pinned by `test_a_refused_request_is_not_counted`.
- **Registered *before* `add_security_headers`, making it innermost**, so a 429
  passes back out through both other middlewares and carries the CSP/HSTS
  headers and an `X-Request-ID` like any other response. A limiter whose
  rejections were invisible to the logs would be the hardest thing here to
  diagnose. Pinned by two ordering tests that fail if registration moves.

**C3's throttle machinery was read and deliberately not reused.** It counts
*failures* — `record_failure` fires on a failed login and `clear` wipes the
counter on success, because the thing being limited is guessing. This limits
*volume*, where every request counts and success is not a reset. The shape was
reused (pure domain policy, rejection with `Retry-After`, never sleeping); the
functions were not.

**Known limit, and it belongs to N3 rather than here:** counters are per
process. `entrypoint.sh` runs uvicorn with no `--workers`, so today that is
exact. A second worker or a second instance makes the effective cap 60/s *per
process* — added to N3's list rather than guarded against now, since guarding
for it means the Postgres write this design exists to avoid.

#### Verification evidence (B3, 2026-08-10)

| Check | Result |
|---|---|
| Full backend suite | **632 passed** (585 + 47 new) |
| New tests | 13 pure policy, 18 service, 16 middleware |
| OpenAPI operations | **73** — unchanged; the limiter adds no route |
| Alembic head | `fbc4e6a8d0f2` — untouched, no migration |
| `git diff --check` | clean |
| `compileall backend/app` | clean |
| Exempt paths under load | 200 consecutive requests to `/`, `/healthz`, `/static/styles.css`, `/static/main.js` do not arm the limiter |
| Ordering | a 429 carries `Content-Security-Policy`, `X-Frame-Options: DENY`, and a 12-char `X-Request-ID` |

Middleware tests drive the ASGI stack directly with a stubbed clock — no server
started (per the project's browser-validation rule) and no sleeping, so the
sliding window is deterministic rather than raced.

**Deployed and owner-validated in the browser on 2026-08-10.** `11a0b42` +
`1c094de` went out in CI run **31421105913** — `==> Deployable changes
present.`, hook `dep-d9t1rke7bikc73afrm00`, `/healthz` 200 afterwards — and the
owner's browser pass against the live service came back clean. **B3 is closed.**

**What that pass does and does not establish, stated precisely because the two
halves came from different evidence.** A clean browser pass proves the limiter
does not **misfire** — ordinary field work does not approach 60/s, which was the
only real risk this change carried. It does not prove the limiter **fires**,
because nothing in ordinary use should ever reach the cap. That half rests on
the 47 local tests, 16 of which drive the real ASGI stack and assert the 429,
its `Retry-After`, the exemptions, and the middleware ordering.

Two direct probes of the deployed service (65 sequential requests, then 150 at
50-way concurrency, both to a non-exempt 404 path) returned no 429 and were
**deliberately not escalated** — separating "the requests never landed
60-within-one-second" from "the probe hit the old container" would have meant
load-testing production for a signal the browser pass provides for free. Worth
keeping as a general shape: *the last 5% of certainty is not always worth what
it costs to obtain*, and here the expensive half of the proof was the half the
tests already covered.

### C4 — Close `/docs`, `/redoc`, `/openapi.json` in production

- [x] **Class C** · **shipped 2026-08-10** · the last unauthenticated surface

`main.py` constructed `FastAPI(title="Inventory Management API")` with no URL
overrides, so FastAPI mounted **four** public, unauthenticated routes — `/docs`,
`/docs/oauth2-redirect`, `/redoc`, `/openapi.json`. New pure helper
`main._doc_urls(production=)` now returns `None` for all three URLs when
`COOKIE_SECURE` is true, which **un-mounts** the routes rather than hiding them:
there is nothing left to authenticate against. The oauth2-redirect route is
derived from `docs_url` and goes with it.

**Reused `COOKIE_SECURE` rather than inventing a production flag.** A4
established it as the "this deployment is HTTPS/production" signal when it gated
HSTS on it, and the HSTS header observed on the live service is direct evidence
it is set there. `render.yaml` needed no change — it already declares
`COOKIE_SECURE: "true"`. **No override was added**, deliberately: re-enabling in
production takes an edit and a deploy, so nothing can be switched on and
forgotten.

**The item's problem statement was wrong about two of its three routes, and the
correction is the interesting part.** It treated all three as equally exposed.
Measured against the real ASGI stack before changing anything:

| Route | Status | Size | Functional? |
|---|---|---|---|
| `/docs` | 200 | 1,023 B | **No** — 2 CDN assets, blocked by A4's CSP |
| `/redoc` | 200 | 905 B | **No** — 1 CDN asset, blocked |
| `/openapi.json` | 200 | **113,156 B** | **Yes** — plain JSON, no assets |

So the live exposure was `/openapi.json` alone: 73 operations, 63
request/response models with every field and validation rule, and — since C1 —
an explicit statement of the required role on eight gated routes. `/docs` and
`/redoc` had rendered blank everywhere, local included, since A4 shipped. Logged
as **N8**; the fix (vendoring `swagger-ui-dist`) was deliberately not bundled
into a security item.

Two consequences of that finding: the item's stated cost — "it removes URLs the
owner may use directly" — was **near zero**, because two of the three could not
be used by anyone; and the severity is reconnaissance, not breach. No rows, no
credentials, no auth bypass — every route still enforces its gate. That is why
this was Class C and 15 minutes rather than Tier 0.

**Interaction with C1 — and the window did open, briefly.** C1 added
`responses={403: ...}` to eight routes, so the schema now names the role each
one requires: exactly the developer-facing documentation C1 wanted, sitting on
a public endpoint. The two were planned as one push precisely so that state
would never reach production. **They did not ship together** — C1 was pushed on
its own (CI run 31402048099, deploy `dep-d9suk4p42hec73bo2ov0`) while C4 was
still being written, so the live `/openapi.json` carried the role annotations
until C4 landed.

Recorded rather than smoothed over, because the failure is instructive: the
batching existed only as an intention written in the hand-off, and an ordinary
`git push` defeated it without anyone deciding to. Two items that must ship
together need that enforced by the work — one branch or one commit — not by a
note. The exposure itself was reconnaissance-grade and bounded to the interval
between the two pushes.

**The verification coverage survives, and this was the one thing that could have
made a cheap item expensive.** Closing `/openapi.json` removes the *route*, not
the schema: `app.openapi()` still returns the full dict, so every "OpenAPI
operations = 73" assertion in this file and C1's
`test_every_gated_work_order_route_documents_its_403` keep working. Pinned by
`test_the_schema_is_still_generated_when_the_route_is_closed`.

#### Verification evidence (C4, 2026-08-10)

Driven through the real ASGI stack in two separate processes, because
`COOKIE_SECURE` is read at import time:

| Path | `COOKIE_SECURE=true` | unset |
|---|---|---|
| `/docs` | **404** | 200, 1,023 B |
| `/docs/oauth2-redirect` | **404** | 200, 3,012 B |
| `/redoc` | **404** | 200, 905 B |
| `/openapi.json` | **404** | 200, 113,156 B |
| `/healthz` | **200** | 200 |
| `/` | **200, 55,505 B** | 200, 55,505 B |

The last row is the control: 55,505 bytes is the same figure the Class A batch
recorded for the SPA shell, so nothing outside the doc routes moved.

| Check | Expected | Result |
|---|---|---|
| Backend test suite | 575 + new | **583 passed in 42.94s**, zero skips |
| OpenAPI operation count | 73 (unchanged) | **73** |
| C1's 403 documentation | still readable from the schema | **8 / 8** |
| Doc routes mounted, production | 0 of 4 | **0** |
| Doc routes mounted, local | 4 of 4 | **4** |
| Alembic head | unchanged, no migration | **`fbc4e6a8d0f2 (head)`**, 0 files |
| Files touched under `backend/static/` | zero | **zero** |
| Frontend references to the doc URLs | 0 | **0**, pinned by a test |
| `render.yaml` | unchanged by C4 | **unchanged** |
| Python compile | clean | clean (exit 0) |
| Deployed CI run | all jobs green, hook fired | **31415331711** — `583 passed in 21.42s`, `==> Deployable changes present.`, `dep-d9t0rl8n74is739jo6ig` |

#### Confirmed on the live service (C4, 2026-08-10)

The check that needs no login, run against
`https://inventory-app-gb1c.onrender.com` after the deploy landed:

| Path | Before | After |
|---|---|---|
| `/openapi.json` | 200, 113,156 B | **404** |
| `/docs` | 200, 1,023 B | **404** |
| `/redoc` | 200, 905 B | **404** |
| `/docs/oauth2-redirect` | 200 | **404** |
| `/healthz` | 200 | **200** |
| `/` | 200 | **200** |

All four doc routes are gone from production and the app is unaffected. **C4 is
closed.**

**One number in this file needed correcting as a result.** The Class A table
records `GET /` as "200, 55,505 bytes", and C4's local control reproduced it —
but production serves **54,866**. That is not a discrepancy to chase: the shell
fragments are CRLF in the Windows working copy and LF in the container after
checkout, and `_assemble_index` reads bytes verbatim. 55,505 − 639 CRLF pairs =
54,866 exactly. So **55,505 is a local-Windows figure and 54,866 is the
production one**; using the former as a production control would look like a
regression that is not there.

### C1 — Fold the five in-body 403 gates into `require_min_role`

- [x] **Class C** · **shipped 2026-08-10** · response body byte-identical, roles
  unchanged

Five role checks lived inside handler bodies in `routers/work_orders.py` as
`if not roles.role_at_least(...): raise HTTPException(403, ...)`, while the
app's other 41 gated endpoints used the declarative dependency. All five are now
`Depends(require_min_role(...))`:

| Was line | Route | Gate |
|---|---|---|
| 296 | `POST /work-orders/import` | `require_min_role(admin)` |
| 333 | `GET /work-orders/export` | `require_min_role(admin)` |
| 382 | `GET /work-orders/lookup` | `require_min_role(supervisor)` |
| 580 | `POST /work-orders/{id}/restore` | `require_min_role(supervisor)` |
| 646 | `PATCH /work-orders/{id}/items/{wid}/billing` | `require_min_role(admin)` |

`routers/work_orders.py` now contains **zero** `status_code=403`. App-wide the
string survives in exactly two places: `auth_deps.py:73`, its single home, and
`transactions.py:57` — see the correction below.

**Four decisions worth keeping:**

1. **`responses={403: ...}` was added, because moving the gate does not
   document it.** The item argued the in-body gate is "invisible in the OpenAPI
   schema," but a dependency is *equally* invisible — FastAPI does not infer a
   403 from a dependency merely capable of raising one. Without the explicit
   declaration, half of what C1 argued for would not have shipped. Declared
   through one `_forbidden(minimum)` helper so eight routes cannot drift into
   describing the same status differently, following B1's `responses={413}`
   precedent.
2. **Eight routes, not five.** `archive_work_order` and the two Owner-only
   `legacy/archive` routes were already declarative but undocumented. Five of
   eight documented would have read as an oversight rather than a boundary.
3. **The billing route's gate was `_can_see_price(user)`** — the price
   *redaction* predicate doing authorization work because the two happen to
   share a rank. It is now `require_min_role(admin)`; `_can_see_price` stays for
   its real callers. This is the distinction the item drew when it said to leave
   `items.py:51` and `transactions.py:80,213` alone: those shape data, this one
   gated.
4. **The 422 → 403 change was accepted deliberately and pinned.** On the billing
   route a dependency resolves before Pydantic, so a request that is both
   malformed **and** unauthorized now answers 403 where it answered 422. The SPA
   cannot produce that combination and no test asserted 422, so it is
   unreachable in practice — but it is a real change at a permission boundary,
   and `test_billing_gate_answers_before_the_body_is_validated` exists so it
   stays deliberate rather than becoming folklore.

**Correction to this item's own framing: the in-body 403 gates were not "all in
`routers/work_orders.py`."** There is a sixth, `routers/transactions.py:55`,
raising the identical detail string. It gates on
`roles.can_transact(user.role, payload.transaction_type)` — it needs the *parsed
body* to know whether the request is a stock or a dispense, so it **cannot** be
a static dependency and is correctly written in the body. It was considered and
deliberately left; `test_create_transaction_has_no_static_min_role` already pins
it. The item named `transactions.py:80,213` as leave-alone but never mentioned
`:55`, which left no way to tell whether it had been missed.

**The blast radius was three tests, not one, and the near-miss is the lesson.**
A directly-called handler never resolves its dependencies, so every test that
proved a gate by calling the handler with a below-rank user silently stops
testing the gate — and two of the three would have kept *passing* against a
different code path rather than failing. They were
`test_the_role_gate_still_runs_before_the_size_check`
(`test_upload_limits.py`), `test_import_route_requires_admin`
(`test_work_order_import.py`), and `test_route_rejects_below_admin`
(`test_work_order_export.py`). All three are replaced by route-level assertions
in `test_route_role_gates.py`, and each old site keeps a pointer comment so the
reasoning is not orphaned. The first two were found only by running the suite:
an initial grep looked clean because its output had been truncated at the head
limit, which is worth remembering as a way to be confidently wrong about a
blast radius.

**B1's ordering property is preserved but is now the framework's, not ours.**
The import route's 403 still beats its 413. It used to be provable by statement
order; it is now the pairing of a dependency gate with a body param, since
FastAPI solves declared dependencies before it reads the form body. The test
asserts that pairing rather than an observed status — the honest limit of a
unit test here, stated in the test's own comment.

#### Verification evidence (C1, 2026-08-10)

| Check | Expected | Result |
|---|---|---|
| Backend test suite | 562 − 3 removed + 16 new | **575 passed in 31.75s**, zero skips |
| OpenAPI operation count | 73 (no route added) | **73** |
| 403 documented | all 8 gated routes | **8 / 8** |
| Effective gate per route | unchanged roles | **admin, admin, supervisor, supervisor, admin** (+ admin, owner, owner) |
| `/work-orders/import` responses | 413 survives beside 403 | **`['200', '403', '413', '422']`** |
| `status_code=403` in `routers/work_orders.py` | 0 | **0** |
| `status_code=403` app-wide | `auth_deps.py` + `transactions.py` only | **exactly those two** |
| Alembic head | unchanged, no migration | **`fbc4e6a8d0f2 (head)`**, 0 migration files touched |
| Files touched under `backend/static/` | zero | **zero** |
| Non-vendor JS files | 32, untouched | **32** |
| Python compile | clean | clean (exit 0) |
| `git diff --check` | clean | clean (only the expected LF→CRLF warnings) |
| Deployed CI run | all jobs green, hook fired | **31402048099** — `==> Deployable changes present.`, `dep-d9suk4p42hec73bo2ov0` |
| Owner browser validation | all 8 checks against the live service | **passed 2026-08-10** |

**Owner browser validation passed 2026-08-10, against the deployed service.**
All five converted routes were exercised through the UI that reaches them, plus
the two boundaries that would expose a wrong minimum:

| # | Check | Route under test |
|---|---|---|
| 1 | Admin: CSV import of an existing number (`created: 0`, `opened: 1`) | `POST /work-orders/import` |
| 2 | Admin: Export filtered CSV | `GET /work-orders/export` |
| 3 | Admin: For Client export | `GET /work-orders/export` (client variant) |
| 4 | Admin: exact archived-number search → Restore | `GET /work-orders/lookup`, `POST /{id}/restore` |
| 5 | Admin: Edit charge on a material line | `PATCH /{id}/items/{wid}/billing` |
| 6 | Supervisor: import/export absent | negative |
| 7 | **Supervisor: History archived-number prompt still works** | `GET /work-orders/lookup` at its real minimum |
| 8 | Technician: notes and add-material unchanged | no regression |

Check 7 is the one that mattered most: `lookup` is the only one of the five a
Supervisor is *supposed* to reach, so it is where a copy-paste of the wrong
`ROLE_` constant would have surfaced. **C1 is closed with nothing outstanding.**

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
  production **from a git push**. It is not the only path overall — a Manual
  Deploy or Blueprint sync from the Render dashboard rebuilds the branch tip and
  runs nothing. Observed 2026-08-10, 33 minutes after the last CI run; harmless
  that time because the tip had already passed CI. See `docs/handoff.md` →
  *CI is not the only path to production*.

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

**Superseded by the 2026-08-10 database cutover, and re-verified on the new
target the same day.** Production runs on the existing Render Postgres instance
`inventory-db-copy` via `fromDatabase.name` in `render.yaml`; the original
`inventory-db` is no longer declared by the Blueprint. The evidence above was
recorded for `inventory-db`, so it was re-checked in the Render dashboard rather
than assumed to transfer:

| Property | `inventory-db-copy` | Verdict |
|---|---|---|
| Plan | **`basic-256mb`** — 256 MB RAM, 0.1 CPU, **1 GB storage** | paid, so **no 90-day expiry clock** |
| Point-in-time recovery | **available, up to 3 days** | same guarantee N5 closed on |
| `inventory-app` binding | confirmed bound to the copy, and intended to stay | not in flux |

**N5's conclusion therefore holds for the active production database**, not just
for the instance it was written about. Nothing here reopens.

**Note the one figure that had never been recorded anywhere: 1 GB of storage.**
It is not a near-term concern and the reason is structural rather than a guess —
**this app persists no binary data at all.** `POST /barcodes/decode` decodes
uploaded image bytes and stores nothing, the CSV import stores parsed rows and
discards the file, and there is no attachment or document feature. Growth is
therefore rows only: `transactions` is the append-only table that grows forever,
`sessions` is bounded by the 12h cap plus the login sweep, and `login_attempts`
is swept after 24h. At this app's scale that ceiling is years away.

It is still a hard ceiling with **no monitoring behind it**, and the blueprint no
longer declares the database at all, so nothing in this repo would notice it
being approached. Recorded here because that is now the only place it is written
down. Worth revisiting if the app ever stores files, or if bulk imports become
routine rather than occasional.

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
| `GET /` still serves the shell | 200 | **200, 55,505 bytes, `Cache-Control: no-cache` preserved** (local/CRLF; production serves **54,866** with LF — see C4) |
| HSTS with `COOKIE_SECURE=false` | absent | **absent** |

Rows 3 and 5 are the direct guarantees against the two stated constraints of
that batch: no schema change, no UI change.
