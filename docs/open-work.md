# Open Work — every named improvement not yet implemented

**This is the only backlog file.** It owns the full write-up for every open
item; there is no other doc to consult and no index to keep in sync. If an item
is not here, it is not open.

Consolidated **2026-08-10** from six files (`improvement-tracker.md`,
`api-hardening-checklist.md`, `ux-review.md`, their two archives, and
`handoff.md`). Shipped history was dropped — git holds it. All figures below
were re-verified against the code during that consolidation.

The three files that remain beside this one describe **what the system is**, not
what is left to do:

| Doc | Holds |
|---|---|
| `docs/current-state.md` | contracts, invariants, data model, roles, known gaps — **the authority**; if it conflicts with code, trust the code |
| `docs/endpoint-map.md` | every endpoint traced DB↔view, request/response contracts, error catalog, service algorithms |
| `docs/project-summary.md` | what the app is, stack, architecture, verification baseline |

---

## The state of things

**Nothing is scheduled.** The 10 items below are real, but none is queued and
none has a date. Every item from the original hardening audit is shipped, a
standing note with a named trigger, or ruled out of scope.

**Do not invent work to fill the queue.** The last three items questioned before
being built — C2, B3, X3 — all described symptoms that were **not occurring**,
and all three got dramatically cheaper for being checked against data first:

- **C2** cited "200 tools = 201 queries" from reading the code. The owner
  confirmed the Tools page was fine. Half a day became five minutes.
- **B3** was to be sized from real request volume. The measurement that did get
  done — a cold SPA load is ~35 requests through the same middleware — ruled out
  a global cap that would have served 429s for JavaScript modules at shift
  change.
- **X3** was logged as *paginate six endpoints*, which implied a frontend
  rewrite. Row counts in the hundreds, plus the discovery that `/items/` and
  `/users/` back *client-side* search rather than list views, turned it into a
  backend-only ceiling.

**Ask what the number actually is before building what an item describes.**
#23 and #24 below are both visibly exposed to this.

The worked example of promotion is **#19 → IMP-033**, shipped 2026-08-10:
a Tier 3 observation became active work only after being logged as a tracked
feature request, and measurement corrected its premise on the way through.

---

## 1. Requested feature

User-requested behavior, not framework work. IMP-001–003 and IMP-005–033 are
implemented; IMP-004 is the only open request.

### IMP-004 — Mass Stage redesign

- **Logged** 2026-08-03 · **very low priority** (the owner's label, not an
  inherited guess) · *Mass Stage*

Make *New Mass Stage* a collapsible card, collapsed by default. Remove the
redundant Unit # field under Communities. Change the workflow so the user first
inputs/searches a work order **number** — the search queries only the number —
and loads the rest of the work-order data after a result is selected. Use mass
staging primarily to group work orders by Location: if a saved Community from
mass staging appears in a work order's Location field, display that work order
under the Communities cards.

Request logged only; no implementation yet.

---

## 2. Hardening — standing notes

None of these is scheduled work. Each is a real property of the system with a
**named trigger** that would promote it, written down so the trigger is
recognized when it arrives rather than rediscovered.

### N3 — Decide the multi-instance story before scaling horizontally

**Trigger: adding a second instance.**

`backend/entrypoint.sh` runs `alembic upgrade head` on every cold start; its own
comment acknowledges this cannot race on a single instance and must be revisited
before adding a second. `render.yaml` is explicitly one instance.

Neither X1's session sweep nor C3's throttle inherits this problem — both are
DB-backed and driven by login traffic rather than by a scheduler, which was a
deliberate design choice.

**B3's rate limiter does inherit it, and is the first thing here that does.**
`services/rate_limit.py` holds its counters in process memory, so a second
worker or instance makes the effective cap 60/s *per process* rather than per
caller. That was a deliberate trade — a one-second window makes persistence
worthless, and a Postgres write per request would cost more than the runaway
client it catches — but this note now has a concrete second item to revisit, not
just the Alembic race.

### N4 — Reconsider serving the SPA from the API process

**Trigger: introducing a CDN** · *deferred by design*

`main.py` mounts `NoCacheStaticFiles` with `Cache-Control: no-cache` on every
asset and re-reads/concatenates the HTML fragments from disk on **every**
request to `/`. Both are deliberate and solve the real blank-page stale-cache
failure. The cost: every asset request is a Python round-trip, no CDN, no
content hashing. Fine at current scale — the first thing to change if a CDN is
ever introduced.

Scale note: `static/styles.css` is **2,546 lines**, unminified, and re-fetched on
every navigation because of the blanket `no-cache`. That is the concrete cost of
this trade, and the number to watch.

### N6 — `services/work_orders.py` is 2,034 lines / 59 functions

**Trigger: none — this is a boundary rule, not a refactor request.**

Roughly 3.7× the next-largest service (`mass_staging.py`, 549) and larger than
any other file in the repo except `styles.css`. Its frontend counterpart
`static/views/workOrders.js` is 1,442 lines. Change risk in this codebase is
concentrated in these two files.

Not a defect — the layering it sits inside is sound, and the extraction target
already exists and already works: `domain/work_orders.py` (461 lines) holds the
pure rules, so the pattern is established rather than hypothetical.

The standing rule is that **further rule-shaped logic belongs behind that
boundary**. Splitting the module for its own sake would churn the
highest-traffic file in the project for no behavior change.

### C2 — Tool-custody N+1 (its risky half is already gone)

**Trigger: the Tools page feels slow, or the tool count grows enough to matter**
· *demoted from Tier 1 on 2026-08-10*

`routers/tools.py` calls `_tool_response` per tool, and each invocation runs
`_custody_query` (`services/tools.py`), a `GROUP BY` aggregate over
`tool_transactions`. `list_tools` is unbounded, so N tools cost **N+1 queries per
page load**.

**Demoted because the symptom is not occurring** — the owner confirmed the Tools
page is accurate and performing as expected, and the "200 tools" figure came
from reading the code, not from the data.

**The ordering half shipped instead, and it was the part that carried the risk.**
`_custody_query` ended at `.having(net > 0)` with no `ORDER BY`, so the order of
holders within a tool was whatever Postgres returned — a user-visible list free
to change after a vacuum or plan change. It is now ordered by first name, last
name, then `assigned_to_id`. That last key is not decoration: **full names are
not unique**, so name alone would leave two same-named holders undefined
relative to each other. Legacy NULL names sort last under Postgres's default
`NULLS LAST`, putting `Name unavailable` at the bottom. Pinned by
`test_custody_is_ordered_by_name` and
`test_custody_order_is_deterministic_for_duplicate_full_names`
(`tests/test_tools_service.py`).

**This is why the item is now cheap and safe.** With the order pinned, a
consolidated all-tools query returns the *same* order as the per-tool one, so
eliminating the N+1 becomes provably invisible — no reshuffle to validate,
whenever someone wants the query count back.

Scope note: `_custody_query` has three callers and only `tool_custody` cares
about order. `_outstanding_for_user` filters to one user and takes `.first()`,
and `delete_tool`'s archive guard only tests truthiness — so the consolidation
work is confined to the list path.

### N7 — `pyzbar` is the one dependency that can break a fresh environment

**Trigger: new dev machine, or a runtime/base-image change.**

It wraps native `zbar`; the wheel bundles the DLLs but they need the Visual C++
2013 redistributable on Windows, and the failure surfaces as a missing
`libiconv.dll` on import — an error message naming neither `pyzbar` nor the real
cause. It takes down the **whole app at import time** rather than degrading
barcode decode alone. Containerized deploys are unaffected; this is a
local-setup and future-runtime-change hazard. Also noted in `requirements.txt`
and `docs/current-state.md`.

### N8 — `/docs` and `/redoc` are CSP-broken wherever they are enabled

**Trigger: someone actually wants a working API explorer** · *found while
shipping C4, 2026-08-10*

A4's CSP is `default-src 'self'` and `add_security_headers` applies it to
**every** response, production and local alike. FastAPI's Swagger UI and ReDoc
load their only assets from `cdn.jsdelivr.net` (`swagger-ui-bundle.js` +
`swagger-ui.css`; `redoc.standalone.js`). The browser refuses all three, so both
pages render blank. Measured by driving the ASGI stack: `/docs` returns 200 with
**1,023 bytes** and `/redoc` 200 with **905 bytes** — HTML shells with nothing
that can load. True since A4 shipped (2026-08-07); nobody noticed, which is its
own data point about how much these pages were used.

`/openapi.json` was never affected — plain JSON with no assets, which is why it
was the only real exposure C4 closed, and why it measured **113,156 bytes**
against their ~1 KB.

**Not fixed as part of C4, deliberately.** The fix is to vendor
`swagger-ui-dist` into `static/vendor/` (beside the ZXing bundle, the
established precedent) and pass `swagger_js_url` / `swagger_css_url` to
`get_swagger_ui_html`. That adds a dependency to keep updated and does not
belong inside a security item whose point was removing a surface. The
alternative — loosening CSP to allow the CDN — would trade a real defence for a
developer convenience and **should not be done**.

---

## 3. UX observations — never re-audited

July 2026 findings that were never promoted or dismissed. Treat these as
observations, **not** as agreed work. Numbers are the original review's and are
not renumbered. Promote one into this file's section 1 as an `IMP-` item before
treating it as active — that promotion step is what #19 followed, and it is not
optional.

### 21. Supervisor+ "Add Stock" path is one toggle deep

The direction toggle (Add Stock / Take Out) is hidden behind *Manual entry &
stock options* by default. Reasonable given dispense-only is the common case.

**This is not an implementation item** — it asks the owner to confirm the
discoverability tradeoff is intended rather than accidental, so it can be closed
with a yes or a no. It is the cheapest thing on this list to close.

Files: `backend/static/pages/transaction.html`,
`backend/static/views/transactions.js`.

### 23. No hardware (keyboard-wedge) barcode scanner support

A Bluetooth laser scanner typically types the barcode plus Enter — faster and
more reliable in warehouse lighting than camera decoding. Today those keystrokes
go nowhere unless a text input happens to be focused. A global fast-keystroke
accumulator on the Transaction page feeding the existing `resolveBarcode` path
would add this without disturbing the camera flow.

**Additive, not a rewrite.** Assumes the crew has or wants scanners — worth one
question before any code.

Files: `backend/static/views/scan.js`, `backend/static/views/transactions.js`.

### 24. No low-stock signal until a dispense is rejected

Mass Stage already computes and displays "short by N" during staging
(`massStage.js` `shortBy`/`coverageHtml`), but Find Item never surfaces low
stock — the first signal is a rejected dispense on the floor. Highlighting
quantity at or below a threshold on the Find Item table would let supervisors
act before the crew hits a wall, even without a formal reorder-point field.

**Assumes people are being surprised by empty stock** — worth one question
before any code.

Files: `backend/static/views/items.js`, `backend/static/pages/saved-items.html`.

---

## Ruled out — recorded so they are not re-proposed

### X2 — Move work-order sorting into SQL — **not safely possible**

`parse_schedule_date` (`domain/work_orders.py`) does three things SQL cannot
easily replicate: regex-matches `M/D/YYYY` **or** ISO with optional trailing
time; expands two-digit years (`year < 100 → +2000`); and catches `ValueError`
on invalid calendar dates so Feb 30 becomes `None` rather than an error. The
third is the blocker — Postgres `make_date` *raises* instead of returning NULL,
so replicating this needs a PL/pgSQL function or a generated column. Both are
schema changes, and `schedule_date` is deliberately raw text.

Superseded by A6, which captured the available win (not hydrating the whole
matching set to return 10 cards) with no behavior change.

### X3 — Paginate the unbounded collections — **shipped 2026-08-10**

Promoted and shipped the same day as a **safety ceiling rather than
pagination**, because the symptom was not occurring and two of the endpoints
back client-side search. Recorded here only because it was parked as out of
scope for being *a feature*, not for being unimportant — and measurement then
showed the feature half was never needed.

---

## Verified as non-issues — do not re-audit

- **Pydantic v1→v2 migration debt** — none. `pydantic==2.13.4`, already current.
- **`BackgroundTasks` durability** — no usage anywhere, so no dropped-job
  exposure. The CSV import is the workload that would normally live in a queue;
  it runs inline, threadpooled rather than blocking the loop.
- **Async correctness** — 89 of 89 routes.
- **Error-translation consistency** — `to_http` used across every router
  (77 call sites). Not drifting.
- **API versioning** — routers mount at `/auth`, `/items`, `/work-orders` with
  no `/v1`. A non-issue while the SPA is the only client and ships in the same
  deploy. Becomes real the moment a mobile app or third-party integration
  consumes the API.
- **ORM and migrations** — SQLAlchemy 2.0, 31 Alembic revisions at head
  (`fbc4e6a8d0f2`) including data backfills. 15 indexes in `models.py`,
  including the functional unique index `uq_work_orders_number_ci`.
- **Concurrency** — `with_for_update()` row locking protects inventory and
  custody mutations.
- **Password hashing** — scrypt with `hmac.compare_digest`, no third-party
  dependency.
- **Layering** — `routers → services → domain → models` held consistently across
  nine resources.
