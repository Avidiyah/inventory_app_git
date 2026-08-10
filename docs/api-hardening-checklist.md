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
size caps) shipped 2026-08-09** on top of it. **C1, C4, C2's ordering half and
B3 all shipped 2026-08-10** — every static role gate in
`routers/work_orders.py` is declarative, FastAPI's docs endpoints are closed in
production, tool-custody row order is pinned, and every route is now rate
limited — and nothing left on the list exposes anything to an unauthenticated
caller. C4's implementation also produced **N8**. Tier 1 emptied on that day,
the owner refilled it by promoting **X3** out of *Not in scope*, and **X3
shipped the same day** — as a safety ceiling rather than the pagination it was
logged as, because measuring showed the symptom was not occurring and that the
endpoints in question back client-side search. **Tier 1 is empty again.**

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
shipped items into `docs/api-hardening-archive.md` rather than leaving them
in the queue.

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

N5 was the only item here and it is closed (see `docs/api-hardening-archive.md`). Nothing on this list
now has an external clock; the queue below is ordered purely on merit.

---

## Tier 1 — empty

X3 shipped on 2026-08-10 (see `docs/api-hardening-archive.md`) and nothing replaced it. Every item
on the original audit is now either shipped, a Tier 2 standing note with a
named trigger, or ruled out of scope.

**Do not invent an item to fill this.** The last two items to be questioned
before being built — C2 and X3 — both turned out to describe symptoms that
were not occurring, and both got materially cheaper for having been checked
against data first. Re-read Tier 2 for a trigger that has fired, or ask the
owner what actually hurts.

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

**B3's rate limiter does inherit it, and is the first thing here that does**
(added 2026-08-10). `services/rate_limit.py` holds its counters in process
memory, so a second worker or instance makes the effective cap 60/s *per
process* rather than per caller. That was a deliberate trade — a one-second
window makes persistence worthless and a Postgres write per request would cost
more than the runaway client it catches — but it means this note now has a
concrete second item to revisit, not just the Alembic race.

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

### C2 — The tool-custody N+1 (its risky half is already gone)

- [ ] **Class C, now effectively Class A** · **trigger: the Tools page feels
  slow, or the tool count grows enough to matter** · *demoted from Tier 1
  2026-08-10*

`routers/tools.py:73` calls `_tool_response` per tool, and each invocation runs
`_custody_query` (`services/tools.py`), a `GROUP BY` aggregate over
`tool_transactions`. `list_tools` is unbounded, so N tools cost **N+1 queries
per page load**.

**Demoted because the symptom is not occurring.** The owner confirmed on
2026-08-10 that the Tools page is accurate and performing as expected. The
original write-up cited "200 tools = 201 queries", but that figure came from
reading the code, not from the data — the real instance is nowhere near a
size where this is felt. A half day spent here buys nothing today.

**The ordering half shipped instead, and it was the part that carried the
risk.** `_custody_query` ended at `.having(net > 0)` with **no `ORDER BY`**, so
the order of holders within a tool was whatever Postgres returned — a
user-visible list on the Tools page with an unspecified order, free to change on
its own after a vacuum or a plan change. It is now ordered by first name, last
name, then `assigned_to_id`. That last key is not decoration: **full names are
not unique** (`docs/current-state.md` → `users`), so name alone would still
leave two same-named holders undefined relative to each other. Legacy NULL names
sort last under Postgres's default `NULLS LAST`, putting `Name unavailable` at
the bottom.

**This is why the item is now cheap and safe rather than "riskier than a pure
optimization".** The whole reason consolidating the query was a Class C change
is that it would reshuffle rows. With the order pinned, a consolidated all-tools
query returns the *same* order as the per-tool one, so eliminating the N+1
becomes provably invisible — no decision required, no reshuffle to validate,
whenever someone wants the query count back.

Pinned by `test_custody_is_ordered_by_name` and
`test_custody_order_is_deterministic_for_duplicate_full_names`
(`tests/test_tools_service.py`). **585 passed.**

Scope note for whoever picks this up: `_custody_query` has three callers and
only `tool_custody` cares about order. `_outstanding_for_user` filters to one
user and takes `.first()`, and `delete_tool`'s archive guard only tests
truthiness — so the consolidation work is confined to the list path.

### N8 — `/docs` and `/redoc` are CSP-broken wherever they are enabled

- [ ] **Class N** · **trigger: someone actually wants a working API explorer**
  · *found while shipping C4, 2026-08-10*

A4's CSP is `default-src 'self'` and `add_security_headers` applies it to
**every** response, production and local alike. FastAPI's Swagger UI and ReDoc
pages load their only assets from `cdn.jsdelivr.net`:

- `/docs` → `swagger-ui-bundle.js` + `swagger-ui.css`
- `/redoc` → `redoc.standalone.js`

The browser refuses all three, so both pages render blank. Measured by driving
the ASGI stack: `/docs` returns 200 with **1,023 bytes** and `/redoc` 200 with
**905 bytes** — HTML shells with nothing that can load. This has been true since
A4 shipped (2026-08-07); nobody noticed, which is its own data point about how
much these pages were being used.

`/openapi.json` was never affected — it is plain JSON with no assets, which is
why it was the only real exposure C4 closed and why it measured **113,156
bytes** against their ~1 KB.

**Not fixed as part of C4, deliberately.** The fix is to vendor
`swagger-ui-dist` into `static/vendor/` (beside the ZXing bundle, which is the
established precedent) and pass `swagger_js_url` / `swagger_css_url` to
`get_swagger_ui_html`. That adds a dependency to keep updated and does not
belong inside a security item whose whole point was removing a surface. The
alternative — loosening CSP to allow the CDN — would trade a real defence for a
developer convenience and should not be done.

So the local explorer is currently unavailable, and that is a known state rather
than a regression to hunt. Promote this if anyone actually wants it back.

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

### X3 — **Promoted, then shipped 2026-08-10.** See *Shipped*.

Left as a pointer rather than deleted, because the *reason* it sat here is the
interesting part: it was parked as out of scope for being a feature, not for
being unimportant. The owner accepted that cost and promoted it — and then
measurement showed the feature half was not needed at all. What shipped was a
safety ceiling with no frontend work, which is why this entry's original
objection never had to be paid.

---

## Shipped — moved to `docs/api-hardening-archive.md`

Every shipped item, with its decision record and verification-evidence
table intact, now lives in **`docs/api-hardening-archive.md`**.

It was moved on 2026-08-10 because it had reached **1,134 lines — 79% of
this file** — and a queue you have to scroll past an archive to reach is a
queue people stop reading. Nothing was deleted or edited in the move.

Shipped so far: A1–A6, B1, B2, B3, B4, C1, C2 (ordering half), C3, C4, N1,
N2, N5, X1, X3.

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
