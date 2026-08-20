# Open Work — every named improvement not yet implemented

**This is the only backlog file.** It owns the full write-up for every open
item; there is no other doc to consult and no index to keep in sync. If an item
is not here, it is not open.

Consolidated **2026-08-10** from six files (`improvement-tracker.md`,
`api-hardening-checklist.md`, `ux-review.md`, their two archives, and
`handoff.md`). Shipped history was dropped — git holds it. All figures below
were re-verified against the code during that consolidation.

Expanded **2026-08-11** at `ac99487` with the evidence-backed stack maturity
register in section 4. The register is a candidate inventory for later
roadmapping, not a committed schedule. It deliberately separates confirmed
defects, production-baseline controls, measured triggers, and optional
enterprise/compliance work.

The three files that remain beside this one describe **what the system is**, not
what is left to do:

| Doc | Holds |
|---|---|
| `docs/current-state.md` | contracts, invariants, data model, roles, known gaps — **the authority**; if it conflicts with code, trust the code |
| `docs/endpoint-map.md` | every endpoint traced DB↔view, request/response contracts, error catalog, service algorithms |
| `docs/project-summary.md` | what the app is, stack, architecture, verification baseline |

---

## The state of things

**Nothing is scheduled.** The items below are real, but none is queued and none
has a date. Every item is either an owner-requested feature, a confirmed defect,
a production-baseline candidate, a standing note with a named trigger, optional
enterprise/compliance work, or ruled out of scope.

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

### IMP-034 — User Hub (role-scoped landing page)

- **Logged** 2026-08-20 · *Landing / Time tracking*

A new role-scoped landing page — the front door every user signs in to —
answering "what am I responsible for right now, and how long have I been
working" without opening a work order. Settled with the owner 2026-08-20;
design spec at `docs/superpowers/specs/2026-08-20-user-hub-design.md`, 18
locked decisions. Four phases:

- **P1 · Time engine — shipped.** `domain/labor_day.py`,
  `services/labor_summary.py`, `services/hub.py`, `GET /hub`, and the global
  stale-session sweep. Backend only; no UI.
- **P2 · Technician hub — shipped.** The page fragment, tab shell, clock
  widget, technician dashboard, the `mountWorkOrderList({container,
  lockedFilter})` extraction from `views/workOrders.js`, and the nav/landing
  changes. Built on `user-hub-p2-technician-hub`; not yet merged to `main`.
- **P3a · Supervisor crew board — shipped.** `GET /hub/crew`,
  `domain/hub.py`'s attention flags, `crew_day_summaries`/`last_worked` in
  `services/labor_summary.py`, and the `labor.session.changed` realtime event
  (registered in `docs/notification-events.md`). Split out of the original
  P3 scope; the crew board renders inside the Dashboard tab, no new tab.
  Built on `user-hub-p3-crew`; not yet merged.
- **P3b · Timesheets — next.** `GET /hub/timesheets`, the grid, per-cell
  drill-down, and CSV export, reusing P3a's crew-scope query. D17 moved this
  down from P4, making the split P3a/P3b the larger of the two remaining
  phases.
- **P4 · Admin hub.** `GET /hub/admin`, the four tile groups, the conditional
  crew board, and widening the timesheet row scope from "my crew" to
  everyone.

---

## 2. Hardening — standing notes

None of these is scheduled work. Each is a real property of the system with a
**named trigger** that would promote it, written down so the trigger is
recognized when it arrives rather than rediscovered.

### N-ITEM-RESTORE — There is no item unarchive, and item requests now expose it

**Trigger: an item request that turns out to name an archived item.**

An archived item is invisible to search in exactly the same way an uncatalogued
one is — `list_items` filters on `archived_at IS NULL` — so a user who searches
for a real-but-archived material gets an empty result and files an item request.
The Admin fulfilling it has no restore path: `services/items.py` has no
unarchive function. `override_archived` (`items.py:116`) frees an archived
item's *barcode* via `_free_archived_holder`, which purges or retires the
archived row; it does not bring it back.

So today the only way to fulfil such a request is to create a fresh row,
reclaiming the barcode with `override_archived=True`. That is a working path,
but it silently forks the item's identity: the archived row's history stays
attached to the retired barcode while new activity accrues to the new row.

This is the same shape as the archived-work-order gotcha, which was solved with
an explicit restore workflow (`restore_work_order`, supervisor+). If archived
items start showing up in item requests with any regularity, the answer is
probably the same: an explicit `restore_item`, gated and confirmed, rather than
teaching the fulfil form more tricks.

**Done when triggered:** an Admin can restore an archived item from the fulfil
form, and the resulting request links to the original row rather than a new one.

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

**A real-time connection registry would be the third thing to inherit it, and
the worst of the three.** The other two *degrade* under a second instance: the
Alembic race is a startup window, and the rate limiter's cap becomes 60/s per
process instead of per caller. A registry does not degrade — it **silently
halves delivery**. Connections are held in process memory, so a user on instance
A would never receive an event emitted on instance B, with no error anywhere on
either side. The screens that failed to update would look exactly like screens
with nothing to update.

Nothing is built yet. The design note that recorded this — whose §15 lists
horizontal scaling as an explicit non-goal precisely because of this item — was
archived out of the repo on 2026-08-16; it survives in the Obsidian vault under
`archive/superpowers/`. Recorded here now so that adding a second instance
surfaces it as a known constraint rather than a production mystery.

### N4 — Reconsider serving the SPA from the API process

**Trigger: introducing a CDN** · *deferred by design*

`main.py` mounts `NoCacheStaticFiles` with `Cache-Control: no-cache` on every
asset and re-reads/concatenates the HTML fragments from disk on **every**
request to `/`. Both are deliberate and solve the real blank-page stale-cache
failure. The cost: every asset request is a Python round-trip, no CDN, no
content hashing. Fine at current scale — the first thing to change if a CDN is
ever introduced.

Scale note: `static/styles.css` is **2,710 lines** (2,546 at the 2026-08-10
consolidation), unminified, and re-fetched on every navigation because of the
blanket `no-cache`. That is the concrete cost of this trade, and the number to
watch.

### N6 — `services/work_orders.py` is 2,034 lines / 59 functions

**Trigger: none — this is a boundary rule, not a refactor request.**

Roughly 3.7× the next-largest service (`mass_staging.py`, 549) and larger than
any other file in the repo except `styles.css`. Its frontend counterpart
`static/views/workOrders.js` is **1,705 lines** (1,442 at the 2026-08-10
consolidation — it has grown 18% since, faster than the service it fronts, which
is unchanged at 2,034). Change risk in this codebase is concentrated in these
two files.

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
`tool_transactions`. `list_tools` is capped at 5,000 by X3, so N returned tools
still cost **N+1 queries per page load**, but memory/result cardinality is bounded.

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

### N9 — Web Push Phase A sits on `main` wired to nothing — RESOLVED 2026-08-18

**Resumed.** The wiring landed: `push_subscriptions` + migration
`1d2e3f4a5b6c`, `services/push.py`, `routers/push.py`, `static/service-worker.js`,
`static/manifest.json`, and the opt-in UI in `static/views/push.js`.
`domain/push.py` is now imported by the service rather than only by its own
test, and `pywebpush` is called. See *API Surface → Web Push* in
`current-state.md` for the behavior.

One correction worth preserving, because this entry asserted it twice and it was
wrong: the remaining work was **not** stranded on `feat/push-notifications`.
That branch was fully merged into `main` (PRs #8 and #9) and held nothing
unique — it was the vehicle for the NetFacilities work, and push Phase A merely
rode along in #8. There was no rebase to do and nothing to recover; the rest of
the feature had simply never been written.

**Phase B — real triggers — landed the same day.** Four work-order events now
send: assignment (to the newly added technicians), completion (Admin and
above), leaving Completed for any live status other than Review, and being
returned from Review to In-Progress — the last two to the assignees plus the
routed supervisor. Recipients are resolved during the request and delivered on a
`BackgroundTasks` handoff. See *API Surface → Web Push* in `current-state.md`
for the rules, and `docs/adding-a-notification-trigger.md` for the procedure to
add a fourth.

Two corrections this entry and the planning document both got wrong, preserved
because each cost time:

- *"Technicians cannot subscribe."* They always could. `/push/subscribe`
  depends only on `get_current_user`; the restriction was one constant in
  `static/views/push.js`.
- The fan-out tests were not hermetic. They assumed `push_subscriptions` held
  only what they seeded, so they passed in CI and failed on any machine with a
  genuinely enrolled device.

**Remaining deliberate limits, none of which are defects:**

- The fan-out is sequential inside the background task. Crew-sized audiences are
  fine; hundreds of devices would need a queue.
- No per-user opt-out and no per-event preferences. Routing is by role and
  assignment only.
- No delivery record. `{sent, dropped, failed}` is logged and discarded, so
  "was this person notified?" has no answer beyond the log.
- iOS requires a manual Home-Screen install per device before push works at all,
  and the installed app has its own cookie jar, so users log in again inside it.
  Accepted, not solvable — Apple exposes no programmatic install.
- Frontend coverage is manual-validation only, same class of gap as N10 and
  PRO-008. `views/push.js` has no automated test.

### N10 — Work Orders live status: frontend gaps with no automated coverage

**Trigger: none for the coverage gap itself — this is a testing gap, not a
defect. The other three each have their own trigger, named below.**

There is no `package.json` and no JS test runner anywhere in this repository;
CI verifies `backend/static/views/workOrders.js` with `node --check` only. The
subscriber, the hold rule, the in-place card update, and the deferred list
refetch (`refreshCardSummary`, `isHeld`, `runOrDeferListRefresh`) are all
manual-validation only, same as the rest of the frontend (PRO-008 is the
general-purpose item for closing this class of gap).

Three more specific gaps live in the same feature and are recorded here rather
than separately, since they share both a trigger class (manual validation) and
a fix class (frontend-only):

- **Reassignment is asymmetric.** `update_work_order`
  (`routers/work_orders.py:533`) emits `_emit_status_changed(work_order.id)`
  (`:562`) unconditionally, including on a technician reassignment. The
  technician who *loses* the work order has its card on screen, so their
  refetch 404s and the row disappears live. The technician who *gains* it has
  no card on screen for the subscriber to match
  (`views/workOrders.js`'s `subscribe(STATUS_CHANGED_EVENT, ...)` ignores any
  id it cannot find in the DOM), so it does not appear until they next enter
  the page. Only `restore_work_order` (`:681`, `_emit_status_changed(None)` at
  `:693`) emits the null-id membership signal that would cover this, and
  reassignment does not use it. **Trigger: a technician reports a newly
  assigned work order not appearing until they reload.**
- **Two rapid status events on one card can resolve out of order.**
  `refreshCardSummary` (`views/workOrders.js:872`) calls `apiGetWorkOrder` with
  no request-ordering guard, so a slower response to an older event can
  overwrite a newer one already rendered. `views/adminReview.js` already solves
  this class of race with a monotonically increasing request id
  (`queueRequestId` / `committedQueueRequestId`, `loadAdminReview`,
  `adminReview.js:122-143`) that only commits a response at least as new as the
  last one rendered. **Trigger: a card observed showing an older status than
  the one just set, immediately after a fast double status change.**
- **A card collapsed while its editor is still open stays held indefinitely.**
  `isHeld` (`views/workOrders.js:913`) checks whether any editor `<details>`
  inside a card is open regardless of whether the card itself is expanded, so
  collapsing the outer card without closing its editor leaves the card held.
  No refresh reaches it, and because `anyCardHeld()` also stays true, a
  deferred full list refetch is blocked until that specific card is
  re-expanded and its editor closed. **Trigger: a badge observed stuck on an
  old status with no open card visible anywhere in the list.**

### N11 — Notification triggers considered and deliberately deferred

**Trigger: a user asking to be told about one of these, or the first time
somebody drives to a job that was archived under them.**

Five triggers were proposed alongside the three that shipped in N9 and were
scoped out to keep that batch tight. None is blocked; each reuses an existing
emitter and the machinery is now in place, so the cost is the three steps in
`docs/adding-a-notification-trigger.md` rather than any new design. Ordered by
value-to-effort:

1. **Completed → Review notifies Admin.** The Review handoff is already
   Admin-only and is the queue they watch. The assignee half of this transition
   was considered and deliberately dropped: Completed → Review notifies nobody
   on the crew, because it is the forward handoff rather than work coming back.
   The *return* out of Review does notify them, and shipped as a fourth
   trigger.
2. **On-Hold notifies the supervisor and assignees.** Same shape as the reopen
   rule, different trigger (`hold_work_order`).
3. **Archive notifies assignees.** Someone actively working a job currently
   learns it was closed by arriving at it. The one item here with a real
   operational cost attached to not doing it.
4. **New user request / recount notifies TechFM OA and above.** Different
   router (`routers/user_requests.py`) and a different audience — genuinely
   useful, but a larger step than 1-3.
5. **NetFacilities enrichment finished notifies the Admin who started it.**
   Long-running and currently poll-only. Touches
   `services/netfacilities_jobs.py` and is the least related to work orders.

**Deliberately excluded rather than deferred:** anything putting customer or job
detail in a notification body (the lock-screen rule), and any general digest or
batching scheme — premature until real volume is observed. The one batched send
that exists, `work_order.supervisor_assigned_bulk`, is scoped to the CSV import
and argued from its volume; see N14.

### N12 — Auto-hold is the largest source of notification volume ever added

**Trigger: a supervisor saying the On-Hold alerts have become noise, or
observably ignoring them.**

Shipped 2026-08-19 with work-order time tracking. Stopping the last clock on an
In-Progress work order now moves it to On-Hold, and every entry into On-Hold
notifies the routed supervisor — a rule written when On-Hold happened only by
deliberate tap. It now happens several times a day per crew: lunch, a parts run,
the end of a shift.

This is the chosen behavior, not an oversight. It was shipped notifying rather
than pre-suppressed because the honest first version is the one that reveals
whether the volume is actually a problem, and because a silent status change is
harder to debug than a loud one.

**The mitigation is already scoped and deliberately narrow:** add one condition
at the `/tracking/stop` trigger site so the auto-hold path alone stays silent,
leaving `/hold` and the PATCH arm untouched. No change to the audience, the
rule, the wording, or the other three trigger sites. See
`docs/notification-events.md`.

### N13 — Send Back tells the technician nothing — CLOSED

Closed 2026-08-20 by `work_order.sent_back`, a fifth arm on
`_notify_work_order_patch` addressed to the assignees and the routed supervisor.
It is its own event rather than a reuse of `work_order.reopened`, for the reason
this item always gave: that rule means "your finished job is no longer
Completed" and a sent-back row never reached Completed.

Shipped alongside `work_order.supervisor_assigned` and
`work_order.supervisor_assigned_bulk`. See `docs/notification-events.md`.

### N14 — The bulk import send is the first batched notification

**Trigger: a second batching case appearing, or an import send that is wrong in
a way per-work-order sends would not have been.**

`work_order.supervisor_assigned_bulk` collapses a whole import into one push per
matched supervisor, which is the only place in this system where one
notification stands for more than one event. The argument for it is volume — an
import creating forty work orders for one supervisor would otherwise fire forty
pushes in seconds — and it is deliberately scoped to the import rather than
generalised into a digest layer.

Two things follow, and both are the reason this is written down:

- **It is not precedent.** "Do not batch or digest" still holds everywhere else.
  A second batching case should be argued on its own volume evidence, not by
  pointing at this one.
- **It under-counts on purpose.** Only work orders the import *created* count.
  An import that routes an existing unrouted work order to a supervisor is
  silent, so that the push and the on-screen `supervisors_matched` can never
  disagree. If that silence turns out to matter more than the agreement does,
  the fix is to widen both together — the import summary and the notification
  read off the same branch precisely so that stays one change.

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

## 4. Stack maturity register - candidates for later roadmapping

### What "10/10" means here

The target is a **business-critical internal application** in one region, with
moderate growth and a small operating team. It is not an assertion of zero risk,
unlimited scale, SOC 2 readiness, or multi-region availability. A 10/10 rating
means that the controls appropriate to the declared target are implemented and
demonstrably effective:

| Metric | Graduation evidence |
|---|---|
| Professionalism | A clean clone builds reproducibly; CI tests the production artifact; releases, rollbacks, recovery, monitoring, support, onboarding, and governance are documented and exercised. |
| Security | No unresolved confirmed defect; identity, authorization, secrets, least privilege, audit, monitoring, recovery, and supply-chain controls have tests or current external evidence; an independent assessment has verified the boundary. |
| Scalability/reliability | The target load and SLO are explicit; representative load and concurrency tests pass with headroom; database invariants, timeouts, capacity, recovery, and growth triggers are measured rather than assumed. |

Graduation rules:

1. Every `Must-fix` item is `Done` with its acceptance evidence retained.
2. Every `Production baseline` item is `Done`, or has verified external evidence
   showing the control already exists.
3. Every `Measured trigger` has instrumentation and an owner; it may remain
   unbuilt while its trigger is demonstrably false.
4. Every `Optional enterprise/compliance` item is explicitly accepted into or
   excluded from the target operating model.
5. Owner decisions below are resolved. A rating cannot be 10/10 while its
   service level, recovery target, access model, or scale target is undefined.

### Register protocol

All entries start in `Candidate`. Allowed states are `Candidate`, `Approved`,
`Scheduled`, `In progress`, `Done`, `Deferred`, and `Declined`. Roadmapping must
record an owner, target state, and verification artifact before changing state.
Effort is relative: `S` is focused/local, `M` crosses several files or one
external control, `L` crosses subsystems, and `XL` is a multi-iteration program.
A range such as `S-M` means an unresolved owner/platform decision changes the
implementation shape; roadmapping must resolve it to one size.

Evidence labels mean:

- `Confirmed`: reproduced or directly demonstrated in code/configuration.
- `Repo gap`: not present in the repository; external implementation may still
  exist and must be verified before work is scheduled.
- `External verification`: the repository cannot prove the current dashboard,
  provider, organizational, or legal state.

Labels may be combined when code and external evidence are both required. The
roadmap-export rules for fields not repeated on every entry are:

- **Value/risk reduction:** `Must-fix` is confirmed exposure or integrity risk;
  `Production baseline` closes material operating risk; `Measured trigger` has
  value only when its stated threshold fires; `Optional enterprise/compliance`
  has value only when DEC-001 or DEC-009 puts it in scope. Numeric scoring waits
  for owner impact/cost input rather than inventing precision here.
- **Owner input:** the summary table in each pillar is authoritative. A `DEC-`
  reference identifies a decision-queue answer; other text names the operational
  limit, policy, or platform choice that must be supplied. `None` means technical
  design can proceed from current evidence, not that no owner reviews the result.
- **Verification surface:** `Confirmed` closes with code/config tests;
  `Repo gap` closes with a repository artifact plus exercises where stated;
  `External verification` closes with dated dashboard/process evidence. Combined
  labels require both.

### Owner decision queue

These are inputs, not implementation tickets. Answering them turns the register
into a roadmap without inventing requirements.

| ID | Open decision | Why it gates work |
|---|---|---|
| DEC-001 | Confirm the provisional target: business-critical, single-region, moderate growth; or choose enterprise/audited scope. | Determines whether optional HA/compliance items are required for 10/10. |
| DEC-002 | Expected users, simultaneous peak, item/work-order/history growth, and largest import/export over 12-24 months. | Sets load fixtures, pool size, query budgets, and scale triggers. |
| DEC-003 | Availability SLO, request latency target, maintenance tolerance, RPO, and RTO. | Defines acceptable platform, alerts, backups, and rollback behavior. |
| DEC-004 | Use local credentials with enforced MFA, or adopt an OIDC/SAML identity provider with enforced MFA. Password-only auth cannot graduate. | Determines password migration, session, recovery, and offboarding work. |
| DEC-005 | Exact Technician visibility and mutation rules for reassigned/archived work orders. | Required to close SEC-002 without guessing policy. |
| DEC-006 | Whether Mass Stages are creator-owned, team-owned, or shared to all Supervisors. | Required to make list/detail/mutation authorization consistent. |
| DEC-007 | Whether imports require atomic rejection, partial success, preview, approval, and/or undo. | Defines the import transaction and audit model. |
| DEC-008 | Budget for always-on web, staging, monitoring, log retention, scans, and identity. | Determines feasible production controls and provider choices. |
| DEC-009 | Data classification, retention, audit, privacy, contractual, and legal-hold obligations. | Determines logging, exports, backups, deletion, and compliance scope. |
| DEC-010 | Solo-maintainer or reviewed-change governance, and named incident/release approvers. | Determines branch protection, CODEOWNERS, production approvals, and break-glass process. |
| DEC-011 | Whether mobile, third-party, sibling-domain, or other cross-origin clients are planned. | Activates API versioning, non-cookie auth, and origin/CSRF work. |
| DEC-012 | Whether exported files must round-trip into this app unchanged. | Selects safe CSV encoding versus explicit-text XLSX output. |

### Security candidates

| ID | Risk reduction/value | Owner input required |
|---|---|---|
| SEC-001 | Very high: abuse/DoS control cannot be bypassed or multiplied by workers. | Platform/shared-limit choice and trusted-proxy policy; DEC-008. |
| SEC-002 | High: prevents unauthorized inventory and Work Order mutation. | DEC-005. |
| SEC-003 | High: bounds remote memory/CPU exhaustion. | Legitimate image/resource limits and provider ingress capability. |
| SEC-004 | High: reduces credential compromise and account enumeration. | DEC-004 and credential-migration/support policy. |
| SEC-005 | High: prevents parallel/distributed login-throttle bypass. | Lockout thresholds, unlock/support policy, and SEC-001 platform choice. |
| SEC-006 | Medium-high: prevents admin-targeted spreadsheet execution. | DEC-012. |
| SEC-007 | High: closes cross-owner Mass Stage access/mutation. | DEC-006. |
| SEC-008 | High: removes a known tracked credential pattern and recurrence path. | Credential owner, reuse assessment, and history-rewrite tolerance. |
| SEC-009 | Medium: prevents query-secret leakage while retaining useful logs. | Log-consumer requirements. |
| SEC-010 | High: limits database blast radius after runtime compromise. | Provider role/release capability and DEC-008. |
| SEC-011 | Very high: prevents password-only privileged compromise and stale sessions. | DEC-004 and DEC-008. |
| SEC-012 | High: preserves attributable evidence outside an app/DB compromise. | DEC-009, retention owner, and logging platform. |
| SEC-013 | High: shortens detection and containment of material abuse. | DEC-010 and security response SLAs. |
| SEC-014 | High: validates the perimeter assumptions behind cookies, limits, and DB security. | Provider operator and DEC-008. |
| SEC-015 | High assurance: finds cross-boundary abuse before attackers do. | Assessment budget, remediation SLA, and DEC-008. |
| SEC-016 | High: reduces stale, shared, and unjustified privileged access. | DEC-004, DEC-010, and HR/manager workflow. |
| SEC-017 | Medium when triggered: prevents cookie-authenticated cross-origin abuse. | DEC-011. |
| SEC-018 | High: gives ordinary operational data an owned lifecycle and export policy. | DEC-009. |
| SEC-019 | Compliance-dependent: satisfies only applicable legal/contractual duties. | DEC-001, DEC-009, and legal/contract owner. |
| SEC-020 | Very high: prevents an unvalidated quantity from being billed to a customer work order. | None. |
| SEC-021 | High: closes item-request filing against work orders the filer cannot see. | DEC-005. |

#### SEC-001 - Trustworthy, bounded request throttling

`Must-fix`; `L`; Security + Scalability; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** `main.py:164-176` keys the global limiter from any raw
  session cookie and `services/rate_limit.py:58-82` creates process-local
  buckets. Rotating bogus cookies bypassed the fixed-cookie quota. Use validated
  identities plus an IP budget, bounded cardinality/TTL, and a shared or edge
  control when more than one process exists.
- **Done when:** invalid or rotating cookies cannot bypass the IP budget;
  authenticated traffic receives both IP and principal limits; trusted-proxy
  behavior and multi-instance enforcement have automated tests.
- **Dependency/decision:** Render ingress topology and shared-store/edge choice.

#### SEC-002 - Caller-scoped, live work-order authorization on dispense

`Must-fix`; `M`; Security + Integrity; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** `routers/transactions.py:66-85` accepts a work-order ID
  by existence only; the downstream service can attach material and advance
  state. A proof accepted an archived order for a Technician. Enforce current
  visibility and archive policy inside the service transaction.
- **Done when:** inaccessible, archived, and reassigned IDs return `404` with no
  mutation; Technician, Supervisor, and Admin cases are covered.
- **Dependency/decision:** DEC-005.

#### SEC-003 - Bounded barcode-image decoding and ingress

`Must-fix`; `M`; Security + Reliability; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** `_uploads.py:49` caps compressed bytes, while
  `services/barcodes.py:79-85` fully decodes without an application dimension or
  pixel ceiling. Bound format, dimensions, pixels, decoded memory, concurrency,
  and wall time; reject oversized bodies before multipart parsing where the
  platform permits.
- **Done when:** malformed, decompression-bomb, boundary, and ten-way concurrent
  fixtures remain inside an approved resource budget without starving health
  or ordinary requests.
- **Dependency/decision:** largest legitimate scan and ingress-limit capability.

#### SEC-004 - Strong password assurance without account-enumeration timing

`Must-fix`; `M`; Security; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** `schemas/auth.py:15-16` permits four-character passwords;
  `services/auth.py:102` skips scrypt for absent/archived users. The measured
  known-wrong versus unknown timing was about 79.55 ms versus 0.028 ms. Raise
  the policy, benchmark/version the KDF, reject common/compromised values, and
  execute a dummy hash on non-users.
- **Done when:** if passwords remain the sole factor, new passwords require at
  least 15 characters; with MFA, the approved current standard applies; at least
  64 characters are accepted; a migration/reset path is enforced; public
  response/timing distributions are materially indistinguishable.
- **Dependency/decision:** DEC-004 and user-support plan.

#### SEC-005 - Atomic, multidimensional login-abuse controls

`Must-fix`; `M`; Security + Scalability; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** `services/login_throttle.py:111-161` performs an
  unlocked read/increment/write and the IP-wide layer defaults off. Use atomic
  counters for account, source IP, and account-plus-IP dimensions with bounded
  cleanup and non-enumerating responses.
- **Done when:** 100 concurrent failures record exactly 100 attempts and the
  intended lock window; multi-IP and repeated-account tests enforce documented
  limits without 5xx responses.
- **Dependency/decision:** SEC-001 plus support/unlock thresholds.

#### SEC-006 - Spreadsheet-safe exports

`Must-fix`; `S-M`; Security; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** `services/work_orders.py:1029-1156` sends user/vendor
  fields directly through `csv.writer`; quoting does not neutralize formulas.
  Safely encode every text cell beginning with `=`, `+`, `-`, `@`, tab, or CR,
  or emit XLSX cells explicitly typed as text.
- **Done when:** every exported text column has fixtures and Excel/LibreOffice
  verification, with required round trips preserved.
- **Dependency/decision:** DEC-012.

#### SEC-007 - One explicit Mass Stage authorization model

`Must-fix`; `M`; Security; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** Supervisor lists are creator-scoped in
  `services/mass_staging.py:148-169`, while ID-based detail and mutations do not
  receive the caller. Apply one policy to list, detail, slots, transitions,
  load/return, reuse, and deletion.
- **Done when:** every operation receives the principal, inaccessible IDs return
  `404`, and a role/ownership matrix covers every route.
- **Dependency/decision:** DEC-006.

#### SEC-008 - Remove tracked credentials and prevent recurrence

`Must-fix`; `S`, or `M` with history rewrite; Security + Professionalism;
`Confirmed`; status `Candidate`.

- **Evidence/outcome:** `backend/.env` is tracked with a local database
  credential despite ignore rules and has existed since the first commit.
  Assess reuse, rotate affected credentials, untrack it, add a redacted example,
  and scan the full history. PRO-006 owns ongoing pre-commit/CI prevention.
- **Done when:** the file is untracked, every potentially reusable value is
  rotated and therefore inactive, the scan is clean of active credentials, and
  the repository-distribution-based history-rewrite decision is recorded.
- **Dependency/decision:** credential ownership and repository distribution.

#### SEC-009 - Query-free, policy-aligned production access logs

`Production baseline`; `S`; Security + Professionalism; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** the application logging policy excludes query strings,
  but `entrypoint.sh:25` leaves Uvicorn access logs enabled. Disable or redact
  that stream while retaining route template, status, duration, request ID, and
  approved actor metadata.
- **Done when:** a sentinel secret in a query is absent from every emitted log
  and useful structured request fields remain present.

#### SEC-010 - Separate migration-owner and runtime database privileges

`Production baseline`; `M`; Security + Professionalism; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** `entrypoint.sh:15-25` runs Alembic and the app with the
  same `DATABASE_URL`, leaving DDL rights in the request-serving process. Move
  migrations to a controlled release identity and grant runtime only required
  table/sequence DML.
- **Done when:** automated verification proves runtime DDL fails while every
  workflow passes; credentials are stored and rotated independently.
- **Dependency/decision:** PRO-001, PRO-002, and provider role/release-job
  capabilities.

#### SEC-011 - MFA-backed identity and privileged-session controls

`Production baseline`; `XL`; Security; `Repo gap`; status `Candidate`.

- **Evidence/outcome:** local hashed sessions are strong, but MFA/IdP lifecycle,
  step-up, idle timeout, session inventory, and technical offboarding propagation
  are not evidenced. Use IdP-enforced MFA or an equivalently operated local
  control for every privileged account and the approved broader population.
- **Done when:** MFA enrollment coverage is 100% for Admin/Owner; recovery and
  every bypass path are tested; immutable subject mapping, idle/absolute expiry,
  step-up for high-risk actions, session listing/revoke-all, and disable-to-
  session-revocation propagation meet the approved SLA end to end.
- **Dependency/decision:** DEC-004 and DEC-008.

#### SEC-012 - Externally retained security and business audit trail

`Production baseline`; `L`; Security + Professionalism; `Repo gap`; status
`Candidate`.

- **Evidence/outcome:** request logging exists, but an append-only, tamper-evident
  external sink and complete material-event coverage are not evidenced. Define
  events for auth, roles, sessions, exports, inventory adjustments, imports,
  Work Orders, Mass Stages, and administrative actions.
- **Done when:** representative events retain actor, target, result, correlation
  ID, and time without secrets; deletion is restricted; immutable retention is
  controlled; completeness is reconciled end to end; tamper or delivery failure
  raises a tested alert.
- **Dependency/decision:** logging platform and DEC-009.

#### SEC-013 - Actionable security monitoring and incident response

`Production baseline`; `M`; Security + Professionalism; `External verification`;
status `Candidate`.

- **Evidence/outcome:** security-specific detection coverage and response SLAs
  cannot be proven from the repo. Define detection logic for credential attacks,
  privilege changes, unusual exports, decoder abuse, authorization failures,
  inventory tampering, and resource attacks. PRO-013 owns telemetry delivery;
  PRO-015 owns general runbooks and exercises.
- **Done when:** each security use case has a tested signal, severity, owner,
  triage data, false-positive review, and containment SLA; controlled events
  prove end-to-end detection through PRO-013.
- **Dependency/decision:** SEC-012, PRO-013, PRO-015, and DEC-010.

#### SEC-014 - Production perimeter and trusted-proxy attestation

`Production baseline`; `M`; Security + Reliability; `External verification`;
status `Candidate`.

- **Evidence/outcome:** repo configuration cannot prove current TLS renewal,
  database exposure/TLS, forwarded-header trust, ingress body limits,
  environment isolation, or preview-data policy. Verify the dashboard boundary
  on every material infrastructure change; PRO-005 owns evidence collection and
  operator/config reconciliation.
- **Done when:** TLS-only ingress, allowed-host enforcement, restricted DB access,
  encryption-at-rest/key-rotation evidence, pre-app body limits, environment
  separation, and renewal monitoring have dated proof; a trusted-proxy test
  proves SEC-001's client IP cannot be spoofed.
- **Dependency/decision:** PRO-005, SEC-001, SEC-003, and DEC-008.

#### SEC-015 - Maintained threat model and independent adversarial testing

`Production baseline`; `M` initially plus recurring cost; Security;
`Repo gap + External verification`; status `Candidate`.

- **Evidence/outcome:** extensive component tests did not expose all observed
  authorization, rate-limit, decode, and export issues. Maintain trust-boundary
  abuse cases and obtain an independent test before claiming critical-production
  security maturity.
- **Done when:** the threat model covers identity, role/ownership, stock changes,
  import/export, native decode, logging, DB, and deployment; abuse cases become
  regression tests; annual independent findings meet remediation SLAs.
- **Dependency/decision:** DEC-008 and test environment.

#### SEC-016 - Privileged-access review and evidence-based offboarding

`Production baseline`; `S-M` recurring; Security + Governance;
`External verification`; status `Candidate`.

- **Evidence/outcome:** session revocation on account changes is a strength, but
  named privileged owners, shared-account prohibition, access recertification,
  separation of duties, and HR/manager joiner-mover-leaver evidence were not
  assessed. SEC-011 owns technical identity/session propagation.
- **Done when:** Admin/Owner access is reviewed quarterly, no shared accounts
  remain, removal meets an approved SLA, and emergency access is time-limited,
  logged, and tested.
- **Dependency/decision:** DEC-004 and DEC-010.

#### SEC-017 - Trusted-origin enforcement before cross-origin expansion

`Measured trigger`; `S-M`; Security; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** same-origin deployment, no CORS, JSON mutations, and
  `SameSite=Lax` are reasonable today; explicit Origin/CSRF enforcement was not
  found. Add it before an untrusted sibling domain or cookie-authenticated
  cross-origin client exists.
- **Done when triggered:** unsafe methods reject absent/untrusted origins or
  require CSRF tokens, and non-browser clients use explicit non-cookie auth.
- **Trigger/dependency:** DEC-011.

#### SEC-018 - Baseline data classification, retention, and export governance

`Production baseline`; `M`; Security + Governance; `External verification`;
status `Candidate`.

- **Evidence/outcome:** even without a regulatory program, the app needs an
  owned inventory of user, operational, log, export, and backup data; a minimum
  retention/deletion policy; and explicit export entitlement/audit rules.
- **Done when:** each data class has an owner, sensitivity, storage locations,
  access/export roles, minimum/maximum retention, deletion behavior, and backup
  expiry; representative export and expiry behavior is tested and audited.
- **Dependency/decision:** DEC-009.

#### SEC-019 - Contractual, privacy, legal-hold, and regulated deletion controls

`Optional enterprise/compliance`; `L`; Security + Governance;
`External verification`; status `Candidate`.

- **Evidence/outcome:** applicable jurisdictions, customer contracts, privacy
  rights, legal holds, and regulated deletion requirements are unknown. Add only
  the controls selected by an owner/legal applicability assessment.
- **Done when in scope:** obligations map to implemented control owners and
  evidence; legal holds override ordinary deletion safely; access/export/delete
  requests and backup expiry meet recorded deadlines.
- **Trigger/dependency:** DEC-001 and DEC-009.

#### SEC-020 - Validate item-request `details` values, not just their keys

`Must-fix`; `S`; Security + Integrity; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** `EDITABLE_DETAILS`
  (`services/user_requests.py:43`) whitelists *which* `details` keys an Admin may
  write; nothing validates *what* is written.
  `schemas/user_requests.py:23` types the field `Optional[dict[str, Any]]`, and
  `update_user_request_fields:514` strips strings and passes every other type
  through. Fulfilment then computes
  `Decimal(str(details.get("quantity") or "1"))` at
  `services/user_requests.py:255`. Two behaviors were reproduced against a live
  database: `quantity: "abc"` stores cleanly and raises an unhandled
  `InvalidOperation` at fulfilment (a 500, after which the request cannot be
  fulfilled until it is edited back), and `quantity: -5` stores cleanly and
  writes a **−5 line onto the work order**. Because `attach_dispense_line`
  aggregates by `(work_order_id, item_id)`, a negative value can also silently
  reduce an existing line rather than appearing as its own.
- **UI-reachable, not API-only:** the edit input carries `min="0.01"`
  (`views/userRequestCards.js:152`) but is handled by a click listener rather
  than a form submit, so the constraint never runs; `views/userRequests.js:245`
  sends the raw trimmed string.
- **Done when:** the patch is validated per request type at the schema boundary
  — reusing the `quantity: Decimal = Field(gt=0)` rule
  `ItemRequestCreate` already declares (`schemas/user_requests.py:47`) — a
  malformed or non-positive quantity returns `422`/`409` with no mutation, and a
  regression test fails without the fix. None of the 10 tests in
  `test_item_requests.py` covers this.
- **Dependency/decision:** none. Shape is the only open question: typed per-type
  patch models end the whole class of defect; per-key coercion beside
  `EDITABLE_DETAILS` is smaller and leaves `Any` in the schema.

#### SEC-021 - Work-order visibility check when filing an item request

`Must-fix`; `S`; Security + Integrity; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** `routers/user_requests.py:96-105` resolves
  `work_order_id` by existence and `archived_at IS NULL` only. The pure
  predicate `domain/work_orders.can_view_work_order` is never called, though it
  takes no I/O and is used for exactly this elsewhere. A proof filed a request
  against a work order assigned to another Technician: accepted, and the
  response returned that work order's `number`. On fulfilment, material is
  retroactively billed to it. This is the same shape as SEC-002, on the route
  deliberately opened to any authenticated session.
- **Done when:** filing against a work order the caller cannot see returns `404`
  with no row created and no number disclosed; Technician, Supervisor, and Admin
  cases are covered.
- **Dependency/decision:** DEC-005, same as SEC-002 — the visibility rule for
  reassigned/archived work orders is the same policy question.

### Professionalism candidates

| ID | Risk reduction/value | Owner input required |
|---|---|---|
| PRO-001 | Critical: makes the tested and deployed artifact identical. | Registry/deploy choice and DEC-008. |
| PRO-002 | Critical: prevents stale/unknown releases and reduces rollback time. | DEC-003. |
| PRO-003 | High: validates releases without exposing production data. | DEC-008 and staging-data policy. |
| PRO-004 | Critical: removes intentional production sleep/cold starts. | DEC-003 and DEC-008. |
| PRO-005 | High: prevents provider/operator drift outside repository review. | DEC-010 and named platform operators. |
| PRO-006 | High: makes released dependencies reproducible and auditable. | DEC-008, tooling choice, and remediation SLA. |
| PRO-007 | High: verifies middleware, HTTP, cookie, and serialization contracts. | None. |
| PRO-008 | High: protects core user workflows rather than syntax alone. | Browser matrix and test-environment budget. |
| PRO-009 | High: proves the database concurrency assumptions behind inventory integrity. | None. |
| PRO-010 | Medium-high: prevents static/type/coverage quality regression. | Initial thresholds and exclusions. |
| PRO-011 | High usability: proves accessible operation for the supported workforce. | WCAG/browser/device/assistive-tech target. |
| PRO-012 | High: turns capacity and reliability claims into measurements. | DEC-002 and DEC-003. |
| PRO-013 | High: detects failures before users and provides diagnostic evidence. | DEC-008, DEC-010, provider, and alert thresholds. |
| PRO-014 | Critical: proves recoverability from destructive error or outage. | DEC-003, DEC-008, and DEC-009. |
| PRO-015 | High: makes high-risk response repeatable under pressure. | DEC-010 and communication roles. |
| PRO-016 | High: makes clean-environment setup reproducible. | None. |
| PRO-017 | High: prevents stale canonical facts from driving decisions. | Vault orphan/tombstone policy. |
| PRO-018 | High: controls changes to critical code and production. | DEC-010 and administrator access. |
| PRO-019 | Medium: makes releases/support visible and traceable. | DEC-010. |
| PRO-020 | High: detects production invariant drift before it compounds. | Source-of-truth rule and alert severity for each invariant. |
| PRO-021 | Medium: turns a malformed item-request payload into a 4xx instead of a 500. | None. |

#### PRO-001 - Build, test, and deploy one immutable production artifact

`Must-fix`; `L`; Professionalism + Security + Reliability; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** `.github/workflows/ci.yml:43-153` tests the checkout but
  never builds `backend/Dockerfile`; the generic deploy hook at `:215-219` does
  not bind the release to the tested SHA. CI must build and boot the production
  image against migrated PostgreSQL, then deploy that exact digest/SHA.
- **Done when:** CI verifies `/healthz`, `/`, static assets, and an authenticated
  route's unauthenticated response; records the digest and source SHA; production
  reports the identical artifact.
- **Dependency/decision:** registry/deploy integration and DEC-008.

#### PRO-002 - Serialized, observable deployment and tested rollback

`Must-fix`; `M`; Professionalism + Reliability; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** the workflow has no deployment concurrency control,
  rollout polling, exact-SHA confirmation, post-deploy smoke, or automated
  failure signal. Add one-at-a-time releases with recorded actor/artifact/result
  and a practiced rollback path.
- **Done when:** a newer deployment cannot be overwritten by a late older run;
  CI waits for provider success and smoke tests; failure is red; the prior
  artifact restores inside the approved target.
- **Dependency/decision:** PRO-001 and DEC-003.

#### PRO-003 - Isolated production-parity staging

`Production baseline`; `L`; Professionalism + Security; `Repo gap`; status
`Candidate`.

- **Evidence/outcome:** `render.yaml:6-46` declares one web service connected to
  the production database; no staging environment is represented. Promote the
  same immutable image through isolated service, DB, secrets, and data policy.
- **Done when:** migrations and critical smoke flows pass in staging before
  production, configuration parity is checked, and production data is never
  copied without sanitization and approval.
- **Dependency/decision:** PRO-001 and DEC-008.

#### PRO-004 - Always-on, explicitly sized production compute

`Must-fix`; `S`; Professionalism + Reliability; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** `render.yaml:10` declares a free web service that can
  sleep and has no production capacity commitment. Use an always-on plan whose
  CPU/RAM/restart behavior meets the service target.
- **Done when:** normal traffic has no idle cold start and 30-day availability,
  warm latency, restart time, and at least 30% peak resource headroom satisfy
  the approved SLO.
- **Dependency/decision:** DEC-003 and DEC-008.

#### PRO-005 - Auditable provider configuration and operator access

`Production baseline`; `M`; Professionalism + Security; `External verification`;
status `Candidate`.

- **Evidence/outcome:** manual deploy/Blueprint operations and dashboard-only DB
  plan, PITR, binding, hostname, and secrets can bypass or drift from repo
  intent. Inventory operators, enforce MFA/least privilege, restrict manual
  deploy to break-glass use, and reconcile material settings.
- **Done when:** a quarterly signed or automated check covers operators, branch,
  hook rotation, DB binding, plan, PITR, hostname, environment, and unsafe
  startup invariants.
- **Dependency/decision:** DEC-008 and DEC-010.

#### PRO-006 - Reproducible, policy-gated software supply chain

`Production baseline`; `L`; Professionalism + Security; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** direct Python pins still resolve transitive versions;
  the base image, apt `libzbar`, Actions tags, audit tool, and vendored ZXing are
  not one reproducible/audited graph. Add hash locks, reviewed action/image
  digests, scheduled whole-image scans, update automation, license inventory,
  SBOM, provenance, and expiring exceptions. Existing N7 covers zbar portability.
- **Done when:** an old release rebuilds identically enough to reproduce its
  dependency graph; Python, OS/container, vendor JS, secret, and IaC policy gates
  run on PRs and schedule with documented severity SLAs.
- **Dependency/decision:** PRO-001 and scan/update tooling budget.

#### PRO-007 - Real ASGI and API-contract tests

`Production baseline`; `M`; Professionalism + Security; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** `requirements-dev.txt:12-15` states no test uses an HTTP
  client; handlers/services are mostly invoked directly. Exercise routing,
  middleware, cookies, serialization, uploads, malformed input, security
  headers, auth failures, and production docs behavior through ASGI.
- **Done when:** critical inventory/work-order writes have HTTP tests and an
  OpenAPI snapshot/diff blocks unintended breaking changes.
- **Dependency/decision:** existing PostgreSQL fixture extension.

#### PRO-008 - Automated frontend unit, DOM, and browser workflow coverage

`Production baseline`; `L`; Professionalism; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** CI uses `node --check` only; large API/view modules and
  role-dependent DOM workflows have no automated behavioral harness. Add tests
  for helpers and UI state plus a small browser suite for the highest-value work.
- **Done when:** PRs deterministically cover login, item lookup, stock/dispense,
  work-order update, Mass Stage authorization-visible behavior, and request
  resolution against disposable data.
- **Dependency/decision:** PRO-003 or an ephemeral browser-test environment.

#### PRO-009 - True multi-session database concurrency tests

`Production baseline`; `L`; Professionalism + Reliability; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** row locking is a core invariant, but the ordinary DB
  fixture uses one connection/outer transaction and does not prove races. Build
  a two-or-more-session harness and retain deterministic interleavings.
- **Done when:** stock/void, work-order deletion, tool custody, Mass Stage,
  archive, barcode uniqueness, login throttle, import, and retry races assert
  final database and ledger invariants after both transactions finish.
- **Dependency/decision:** dedicated PostgreSQL test database.

#### PRO-010 - Static analysis, type checking, and meaningful coverage gates

`Production baseline`; `M`; Professionalism; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** CI currently has compile/syntax checks but no Ruff,
  Python type gate, ESLint/checkJs, or coverage regression signal. Introduce
  ratcheted baselines so adoption does not require an unrelated rewrite.
- **Done when:** Ruff and JavaScript lint pass; type debt cannot increase;
  coverage is published; auth, authorization, inventory, import, and concurrency
  modules meet an approved branch threshold; total coverage cannot silently fall.
- **Dependency/decision:** initial thresholds and exclusions.

#### PRO-011 - Evidence-based accessibility and device QA

`Production baseline`; `M`; Professionalism; `Repo gap`; status `Candidate`.

- **Evidence/outcome:** ARIA/focus work exists, but validation is manual. Define
  the supported browsers, devices, zoom, keyboard, and assistive-technology bar
  for a workforce tool.
- **Done when:** automated axe checks have no critical/serious findings on core
  pages; keyboard workflows, focus restoration, names, contrast, 200%/400% zoom,
  touch targets, responsive layouts, and one screen-reader pass are recorded.
- **Dependency/decision:** PRO-008 and chosen WCAG/support matrix.

#### PRO-012 - Declared SLOs and representative capacity proof

`Production baseline`; `L`; Professionalism + Scalability; `Repo gap`; status
`Candidate`.

- **Evidence/outcome:** no approved availability, latency, durability, load,
  query-count, import/export, RPO, or RTO envelope exists. Define it from actual
  use and retain a representative dataset/workload per release.
- **Done when:** core scan, stock, work-order, Mass Stage, history, and login mix
  sustains 2x observed peak plus a 3x short burst within p95/p99/error targets,
  without deadlocks or invariant drift; browser/query budgets are recorded.
- **Dependency/decision:** DEC-002 and DEC-003.

#### PRO-013 - Centralized telemetry, synthetics, alerts, and error grouping

`Production baseline`; `M`; Professionalism + Security + Scalability;
`External verification`; status `Candidate`.

- **Evidence/outcome:** structured stdout/request IDs and health checks exist,
  but external retention, synthetic checks, metrics, dashboards, alerts, and
  escalation are not evidenced. Observe route latency/errors, release SHA,
  DB pool/connections/locks/slow queries, CPU/memory/storage, rate/login limits,
  list truncation, imports/jobs, and deploy events.
- **Done when:** external and authenticated synthetics run; alert delivery is
  test-fired quarterly; sensitive-field probes pass; each alert has an owner,
  threshold, and response procedure.
- **Dependency/decision:** PRO-004, PRO-012, provider choice, named responder.

#### PRO-014 - Proven backup, PITR, and isolated restoration

`Must-fix`; `L`; Professionalism + Security + Reliability;
`External verification`; status `Candidate`.

- **Evidence/outcome:** dashboard documentation describes three-day PITR, but no
  restore-drill evidence exists; a prior wrong-data import required a cutover.
  Treat recoverability as unproven until exercised independently of runtime
  credentials.
- **Done when:** quarterly isolated restore verifies migration head, row counts,
  ledger invariants, login, and representative workflows; measured RPO/RTO meet
  policy; cutover/rollback and backup-access separation are documented.
- **Dependency/decision:** DEC-003, DEC-008, and DEC-009.

#### PRO-015 - Concise operational and incident runbooks

`Production baseline`; `M`; Professionalism + Security; `Repo gap`; status
`Candidate`.

- **Evidence/outcome:** knowledge is narrative rather than a tested runbook set.
  Cover failed deploy/rollback, DB outage, wrong import/data repair, wrong DB
  binding, secret exposure, zbar failure, storage exhaustion, malicious upload,
  dependency incident, and unavailable provider.
- **Done when:** each runbook names owner, commands, safety checks, communication,
  stop conditions, and rollback; semiannual tabletop and technical recovery
  drills retain results and follow-up actions.
- **Dependency/decision:** PRO-013, PRO-014, SEC-013, and DEC-010.

#### PRO-016 - Reproducible onboarding and local development

`Production baseline`; `M`; Professionalism; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** `README.md` is links only; setup assumes an existing
  Windows venv, while PostgreSQL, zbar, environment values, migrations, owner
  bootstrap, run/test commands, and troubleshooting are distributed elsewhere.
- **Done when:** clean Windows and Linux clones reach a running app and green
  checks within 30 minutes using CI-aligned documented commands and a redacted
  `.env.example`.
- **Dependency/decision:** SEC-008 and PRO-006.

#### PRO-017 - Trustworthy generated facts and Obsidian synchronization

`Production baseline`; `M`; Professionalism; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** migration/route/schema/test counts and provenance drift;
  `scripts/sync-obsidian.ps1:94-152` writes current mirrors but does not remove
  or flag orphans, and its content-hash shortcut can skip provenance-only
  refreshes. Generate or check volatile facts and make stale memory detectable.
- **Done when:** CI checks current Alembic/OpenAPI/test facts; sync `-Check`
  detects stale metadata and orphan mirrors; obsolete notes are removed or
  tombstoned; targeted Obsidian search returns current authority first.
- **Dependency/decision:** vault deletion/tombstone policy.

#### PRO-018 - Repository and production change governance

`Production baseline`; `M`; Professionalism + Security; `External verification`;
status `Candidate`.

- **Evidence/outcome:** branch protection, code ownership, review requirements,
  production approvals, and secret scanning cannot be verified from the repo.
  Codify what can be codified and record a deliberate solo-maintainer exception
  where a second reviewer is unavailable.
- **Done when:** protected `main`, required checks, blocked force push/deletion,
  PR/migration/security/rollback checklist, sensitive-area CODEOWNERS, protected
  production environment, `SECURITY.md`, break-glass process, and quarterly rule
  review have current evidence.
- **Dependency/decision:** DEC-010 and GitHub/provider admin access.

#### PRO-019 - Traceable releases and user-impact communication

`Production baseline`; `S-M`; Professionalism; `Repo gap`; status `Candidate`.

- **Evidence/outcome:** commits and deploy hooks exist, but a durable release
  record, compatibility statement, maintenance communication, and support intake
  are not defined. Keep this light for one bundled SPA/API rather than inventing
  public API ceremony.
- **Done when:** each production change is traceable to artifact/SHA, migrations,
  verification, rollback, and user-visible notes when behavior changes; a named
  support path and urgent-maintenance communication process exist.
- **Dependency/decision:** PRO-001, PRO-002, and DEC-010.

#### PRO-020 - Production data-integrity reconciliation

`Production baseline`; `M`; Professionalism + Reliability; `Repo gap`; status
`Candidate`.

- **Evidence/outcome:** transactional services and tests enforce many local
  invariants, but no periodic production reconciliation or invariant alarm is
  evidenced. Define checks that are valid for this data model, such as impossible
  quantities, mutually inconsistent void/contributor state, duplicate active
  custody, invalid Mass Stage completion state, and orphaned business links.
- **Done when:** checks run read-only on a schedule and after risky imports/data
  repair; failures identify affected IDs without exposing secrets, page an owner
  at the approved severity, and link to a repair/rollback runbook. At least one
  controlled fixture proves every alarm path.
- **Dependency/decision:** PRO-013, PRO-015, SCL-005/SCL-006, and the approved
  source-of-truth rule for each invariant.

#### PRO-021 - Whitespace-only `searched_text` returns 500, not 422

`Must-fix`; `S`; Professionalism + Reliability; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** one shared validator serves a required field and an
  optional one (`schemas/user_requests.py:54`, applied to `searched_text` and
  `note`) and returns `value.strip() or None`. Pydantic v2 does not re-validate
  an after-validator's return against the annotation, and `min_length=1`
  (`:46`) already passed on the *untrimmed* value — so `searched_text="   "`
  yields `None` on a field typed `str`, and `create_item_request` then calls
  `.strip()` on it (`services/user_requests.py:174`). Reproduced: unhandled
  `AttributeError`.
- **Reachability:** API-only today. `views/itemRequest.js:92` trims and rejects
  empty text before sending, so no user hits this through the UI — a client-side
  guard standing in for a server-side one, which is the same pattern SEC-020
  shows failing once a second client path exists.
- **Done when:** trimming happens in a `mode="before"` validator so `min_length`
  sees the trimmed value, one validator no longer serves both a required and an
  optional field, and whitespace-only input returns `422` with no row created.

### Scalability and reliability candidates

| ID | Risk reduction/value | Owner input required |
|---|---|---|
| SCL-001 | High: guarantees unambiguous barcode identity under concurrency. | None. |
| SCL-002 | High: prevents cross-workflow database deadlocks. | None. |
| SCL-003 | High: prevents partial or conflicting Mass Stage transitions. | None beyond DEC-006 authorization policy. |
| SCL-004 | High: prevents accidental removal of intended DB indexes/FK behavior. | None after schema-intent review. |
| SCL-005 | High: prevents partial/misattributed imports and enables recovery. | DEC-007. |
| SCL-006 | High: makes command atomicity explicit and testable. | Approved partial-import policy from DEC-007. |
| SCL-007 | Medium: removes an existing O(N) query pattern cheaply. | None. |
| SCL-008 | High: prevents connection exhaustion and unbounded DB waits. | DEC-002, DEC-003, and provider connection limits. |
| SCL-009 | High: prevents duplicated inventory effects on retry. | Idempotency-key lifetime/conflict policy. |
| SCL-010 | High: prevents startup migration races and unsafe rollback. | DEC-003 maintenance tolerance and provider release capability. |
| SCL-011 | Medium-high: prevents heavy work from starving ordinary traffic. | Resource/deadline limits and provider ingress capability. |
| SCL-012 | High when triggered: keeps durable History/report access bounded. | Count/report semantics and DEC-002. |
| SCL-013 | High when triggered: prevents real rows becoming undiscoverable. | DEC-002 and picker/search UX contract. |
| SCL-014 | High when triggered: bounds Work Order reads while preserving legacy dates. | Malformed-date policy. |
| SCL-015 | Medium when triggered: bounds export memory and request duration. | Synchronous-download expectation and DEC-012. |
| SCL-016 | Medium when triggered: makes long work durable across deploy/retry. | Queue/provider budget and cancellation policy. |
| SCL-017 | Medium when triggered: controls storage/query growth without losing audit data. | DEC-009. |
| SCL-018 | Medium when triggered: protects invariants when additional writers appear. | Approved value set and maintenance tolerance. |
| SCL-019 | Medium when triggered: keeps normalized search responsive at larger catalogues. | DEC-002 and accepted search-latency target. |
| SCL-020 | High only when required: raises availability beyond single-region recovery. | DEC-001, DEC-003, and DEC-008. |
| SCL-021 | Medium only when proven: relieves sustained primary read pressure. | DEC-001, DEC-002, and DEC-008. |
| SCL-022 | High: handles retryable PostgreSQL failures without duplicating business effects. | Retry/deadline policy and the commands approved as safely retryable. |

Existing standing notes remain part of this register without duplicate tickets:

- **N3** is the measured multi-instance story.
- **N4** is the measured static-asset/CDN story.
- **C2** is the measured Tool-custody query story.
- **N6**, **N7**, and **N8** remain professionalism/maintainability candidates
  with their existing triggers and full write-ups above.

#### SCL-001 - One authoritative barcode namespace

`Must-fix`; `L`; Scalability + Integrity; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** primary and alternate barcode uniqueness lives in two
  separately constrained tables, while `services/items.py` checks then writes.
  Concurrent primary/alternate claims can both commit and make lookup ambiguous.
  Introduce one database-enforced namespace or an equivalently serializable
  claim mechanism.
- **Done when:** migration detects/backfills existing conflicts; concurrent
  cross-table claims permit exactly one commit; every lookup is deterministic.
- **Dependency/decision:** schema/backfill design.

#### SCL-002 - One canonical lock order across inventory workflows

`Must-fix`; `M`; Reliability + Integrity; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** transaction void locks Transaction then Item, while
  work-order-line deletion locks Item then updates contributor Transactions.
  Define and apply a global lock order for shared entities.
- **Done when:** repeated two-session void/delete and related races produce no
  PostgreSQL `40P01`, no 5xx, and invariant-correct stock/ledger results.
- **Dependency/decision:** PRO-009 concurrency harness.

#### SCL-003 - Serializable Mass Stage lifecycle and slot ordering

`Must-fix`; `L`; Reliability + Integrity; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** Mass Stage state checks and slot ordering are not locked;
  concurrent completion, load/edit, and slot additions can race. Lock the stage,
  enforce transition preconditions transactionally, and add deterministic unique
  slot ordering.
- **Done when:** every tested interleaving is equivalent to a valid serial order;
  no mutation commits after completion; `(stage_id, sort_order)` remains unique;
  no partial stock/custody change survives failure.
- **Dependency/decision:** SCL-002 and PRO-009; the relevant SCL-006 transaction-
  ownership work is a coordinated prerequisite within this change.

#### SCL-004 - Eliminate ORM/migration metadata drift

`Must-fix`; `S`; Reliability + Professionalism; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** `alembic check` proposes six physical-index removals and
  two transaction-FK rewrites because model metadata does not describe the
  migration-owned schema. Align metadata without deleting intended protections.
- **Done when:** reviewed metadata matches the intended live schema and
  `alembic check` passes locally and in CI with no proposed operations.
- **Dependency/decision:** index/FK intent audit.

#### SCL-005 - Staged, attributable, reversible imports

`Must-fix`; `XL`; Reliability + Security + Professionalism; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** Work Order import performs repeated lookups and commits
  row by row; the UI submits immediately. A prior mistaken 800-row import
  required database cutover. Add preview/diff, batch identity, explicit approval,
  policy-defined visibility, retry, and rollback/compensation semantics.
- **Done when:** actor/checksum/counts are recorded; interrupted or rejected
  batches expose only state DEC-007 permits; tested retry and owner-approved
  undo/compensation meet the selected recoverability policy.
- **Dependency/decision:** DEC-007 and schema/UI work; the relevant SCL-006
  transaction-ownership work is designed first and delivered with this fix.

#### SCL-006 - Explicit top-level transaction ownership

`Production baseline`; `L`; Reliability + Maintainability; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** helpers such as `_merge_reference` commit internally and
  callers later perform more work/commits, obscuring atomic command boundaries.
  Helpers should `flush`; top-level services should own commit/rollback.
- **Done when:** failure injection proves Work Order, Mass Stage, reference,
  transaction, and import commands never partially persist outside the approved
  partial-import policy.
- **Dependency/decision:** design the common transaction policy first and deliver
  it with SCL-002/SCL-003/SCL-005; those items are not reverse dependencies.

#### SCL-007 - Bounded item-list query count

`Production baseline`; `S`; Scalability + Professionalism; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** item listing can return thousands of rows without eager
  loading alternate barcodes, while response mapping reads that relationship per
  item. Add eager/grouped loading and deterministic alternate-barcode order.
- **Done when:** the endpoint uses at most two DB queries for 1, 100, and 5,000
  items and preserves its response contract.
- **Dependency/decision:** query-count fixture.

#### SCL-008 - Explicit database connection and timeout budget

`Production baseline`; `M`; Scalability + Reliability; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** the engine uses pre-ping, recycle, and connect timeout,
  but has no declared pool, pool-wait, statement, or lock timeout budget. Size
  all process pools against the actual DB connection limit and request deadline.
- **Done when:** maximum pools stay below 80% of available connections; pool,
  lock, and statement waits are bounded below the request deadline; saturation
  fails quickly with a controlled response and observable metric.
- **Dependency/decision:** DEC-002, DEC-003, and current provider limits.

#### SCL-009 - Idempotent high-value write APIs

`Production baseline`; `L`; Reliability + Integrity; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** stock/dispense POSTs append and apply quantity on every
  accepted request. Network/client retries can duplicate business effects. Add
  scoped idempotency keys to inventory-changing commands, then expand to other
  high-value workflows based on risk.
- **Done when:** concurrent duplicates return one original result, create one
  ledger event, and apply one stock change; key conflict/expiry/retention rules
  are documented and tested.
- **Dependency/decision:** schema/API/frontend and owner-approved key lifetime.

#### SCL-010 - Controlled, backward-compatible schema rollout

`Production baseline`; `L`; Reliability + Professionalism; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** every container startup runs migrations before Uvicorn.
  This races at multiple instances and couples app start to privileged DDL. Use
  one migration runner/advisory lock and an expand/contract policy.
- **Done when:** production-clone rehearsals cover data migrations; pre-deploy
  backup checks run; old/new app overlap is safe where required; app rollback
  after schema change is tested without corruption.
- **Dependency/decision:** PRO-001, PRO-014, SEC-010, and maintenance tolerance.

#### SCL-011 - Bounded admission for import/export request work

`Production baseline`; `M`; Scalability + Reliability; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** large import/export work shares request-worker capacity.
  SEC-003 exclusively owns barcode ingress/decoder limits. Apply explicit
  admission, concurrency, wait, RSS, and deadline budgets to import/export.
- **Done when:** representative concurrent imports/exports stay inside approved
  RSS/wait/rejection budgets and ordinary-route p95 remains inside PRO-012's SLO;
  admission metrics prove the configured bound.
- **Dependency/decision:** SCL-005, SCL-015, and PRO-012.

#### SCL-012 - Indexed, keyset-paginated History and server-side reports

`Measured trigger`; `L`; Scalability; `Confirmed`; status `Candidate`.

- **Evidence/outcome:** History performs an exact count and offset sort on each
  page without a complete declared index set, while pricing/report UI can fan
  out across pages and referenced Work Orders. Use query-plan evidence, suitable
  indexes, `(created_at,id)` keyset pagination, bounded count semantics, and a
  server-side report/export when needed.
- **Done when triggered:** representative 10x data meets the route SLO with
  deterministic traversal and bounded report requests.
- **Trigger/dependency:** slow-query evidence, p95 breach, copy time above half
  the deadline, or material history growth; count semantics require owner input.

#### SCL-013 - Cursor/search contracts before list ceilings omit real data

`Measured trigger`; `XL`; Scalability + UX; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** 5,000-row safety ceilings bound memory but are not
  pagination; some endpoints also back client-side reference search. Redesign
  contracts and pickers only when an actual ceiling or payload limit is reached.
- **Done when triggered:** responses expose cursor/truncation metadata; every row
  remains discoverable through server search; no picker requires whole-table
  loading; contract and browser tests preserve workflows.
- **Trigger/dependency:** any `list.truncated`, payload above 2 MB, or list-route
  SLO breach; DEC-002.

#### SCL-014 - Typed schedule dates and bounded SQL Work Order ordering

`Measured trigger`; `L`; Scalability + Data quality; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** Work Orders must scan and Python-sort matching projections
  because schedule dates are permissive raw text. Preserve raw display/input as
  needed but add a validated sortable representation when measurement justifies
  the migration.
- **Done when triggered:** legacy values are audited under an approved malformed-
  date rule; displayed ordering is preserved; initial-page SQL reads only a
  bounded multiple of returned rows.
- **Trigger/dependency:** scanned/returned ratio above 20x, list p95 breach, or
  substantial Work Order growth.

#### SCL-015 - Bounded-memory export delivery

`Measured trigger`; `L`; Scalability + Reliability; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** Work Order export eagerly hydrates the uncapped result and
  builds one in-memory string. Stream from a bounded cursor or create an
  asynchronous artifact once synchronous delivery exceeds its budget.
- **Done when triggered:** count/checksum are complete; peak RSS rises less than
  the approved buffer (initial candidate 10 MB); disconnect cleanup and export
  duration are verified/observable.
- **Trigger/dependency:** response above 25 MB, over 20% process memory, or over
  half the request deadline; SEC-006.

#### SCL-016 - Durable job execution when requests outgrow their deadline

`Measured trigger`; `XL`; Scalability + Reliability; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** import, export, and barcode decode run inline. Do not add
  queue infrastructure merely for fashion; add it when measured duration or
  contention makes request execution unreliable.
- **Done when triggered:** persisted job state, idempotent retry, leasing/recovery,
  progress, cancellation, audit identity, deploy survival, and operational
  dashboards are exercised end to end.
- **Trigger/dependency:** projected worst case or observed p95 approaches 75% of
  the request deadline, any operation times out, or repeated heavy concurrency
  breaches ordinary-route SLO; SCL-005/SCL-011/PRO-013.

#### SCL-017 - Measured retention, archival, and partition strategy

`Measured trigger`; `XL`; Scalability + Governance; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** transactions, tool transactions, requests, and Work
  Orders are durable growth tables; current provider storage is finite. Observe
  growth first, then archive or partition without weakening the audit model.
- **Done when triggered:** retention is approved; archived data restores and is
  queryable as required; the strategy is rehearsed on a production clone; vacuum
  and index maintenance remain inside budget.
- **Trigger/dependency:** projected exhaustion enters the implementation lead
  time, an owner-approved high-water mark is crossed, maintenance fails its
  window, or query SLO degrades after index fixes; DEC-009.

#### SCL-018 - Database-enforced enum/state invariants for additional writers

`Measured trigger`; `M`; Reliability + Integrity; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** several roles, statuses, modes, and transaction types are
  unconstrained text and currently rely on one application writer. Add reviewed
  `CHECK`/reference constraints before the trust boundary expands.
- **Done when triggered:** existing values are audited; constraints install with
  the approved availability strategy; invalid direct writes fail; application
  and migration tests cover each allowed transition/value.
- **Trigger/dependency:** before a second app, integration, or direct import path
  writes these tables.

#### SCL-019 - Indexed search plan for normalized item matching

`Measured trigger`; `L`; Scalability; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** improved punctuation-insensitive search computes multiple
  `regexp_replace(lower(column), ...)` expressions and leading-wildcard matches
  per row. This is correct for the small catalogue but cannot use an ordinary
  B-tree index. Measure it before introducing generated normalized columns,
  trigram indexes, or a search service.
- **Done when triggered:** representative 10x catalogue search meets the SLO;
  `EXPLAIN (ANALYZE, BUFFERS)` proves the selected plan; Python/Postgres/browser
  parity and punctuation behavior remain unchanged.
- **Trigger/dependency:** item-search p95 breach, high scanned/returned ratio, or
  material catalogue growth; DEC-002.

#### SCL-020 - Multi-zone high availability

`Optional enterprise`; `XL`; Reliability + Scalability;
`External verification`; status `Candidate`.

- **Evidence/outcome:** one region/zone and one managed primary DB remain failure
  domains. N3 separately owns ordinary second-worker/second-instance readiness.
  Do not call multi-zone HA mandatory until DEC-001/DEC-003 demand availability
  beyond tested single-region recovery.
- **Done when in scope:** multi-instance and provider-zone failure drills meet
  approved RPO/RTO without invariant loss; pool, migration, session, rate-limit,
  deploy, and observability controls are instance-safe.
- **Dependency/decision:** N3, SEC-001, SCL-008/SCL-010, and platform budget.

#### SCL-021 - Read replica, search index, or analytical store

`Optional enterprise`; `XL`; Scalability; `Confirmed`;
status `Candidate`.

- **Evidence/outcome:** all reads/reports use the primary. Add a secondary store
  only after query/index/export improvements leave sustained primary read
  pressure; otherwise it adds consistency and recovery risk without value.
- **Done when in scope:** lag/consistency contract, reconciliation monitoring,
  failure/failback drills, and measurable primary-load reduction satisfy SLOs.
- **Trigger/dependency:** primary read CPU remains above 70% after relevant query
  fixes; DEC-001/DEC-002/DEC-008.

#### SCL-022 - Bounded whole-transaction retry for transient PostgreSQL failures

`Production baseline`; `M`; Reliability + Integrity; `Confirmed`; status
`Candidate`.

- **Evidence/outcome:** PostgreSQL can abort transactions with serialization
  (`40001`) or deadlock (`40P01`) errors, and no bounded command-level retry
  policy was found. Retry only entire explicitly safe/idempotent transactions;
  never retry after an uncertain commit or use retry to hide a lock-order defect.
- **Done when:** injected `40001`/`40P01` failures prove bounded backoff within the
  request deadline and exactly one ledger/stock effect; exhausted retries return
  a sanitized, observable retryable failure; uncertain commit never replays.
- **Dependency/decision:** SCL-002, SCL-008, SCL-009, PRO-009, and approved
  retryable-command/max-attempt policy.

### Dependency groups for later roadmapping

These are sequencing constraints, not a schedule:

1. **Resolve the target:** DEC-001 through DEC-004 establish scope, load, SLO,
   recovery, and identity; DEC-005 through DEC-012 resolve workflow policy.
2. **Close confirmed exposure:** SEC-001 through SEC-008, SCL-001 through
   SCL-005, PRO-001/PRO-002/PRO-004/PRO-014.
3. **Build the operating floor:** release/staging, least privilege, reproducible
   supply chain, external configuration, backups, telemetry, runbooks,
   onboarding, and governance.
4. **Prove boundaries:** ASGI/browser/concurrency/security tests, SLO/load tests,
   threat model, accessibility, and independent assessment.
5. **Promote measured scale work only on evidence:** N3, N4, C2 and SCL-012
   through SCL-019 each carry their own trigger.
6. **Choose enterprise scope explicitly:** SEC-019 and SCL-020/SCL-021 are not
   required for the provisional single-region target unless DEC-001 changes.

### Review evidence and external standards

Clean-commit verification at `ac99487`: 679 Python tests and 32 non-vendor
JavaScript syntax checks passed. After concurrent search-ranking worktree changes
appeared during this documentation session, all 683 collected tests and the same
32 syntax checks passed. `pip check` is clean; `pip-audit --local` was clean at
the preceding review baseline. Alembic head/current were `fbc4e6a8d0f2`;
`alembic check` proposed six intended-index removals and two transaction-FK
`RESTRICT` rewrites, the exact drift tracked by SCL-004. Docker was unavailable
locally, which is why image-build evidence is a candidate rather than success.

Primary references used to set the maturity bar:

- NIST SP 800-63B: <https://pages.nist.gov/800-63-4/sp800-63b.html>
- OWASP Password Storage Cheat Sheet:
  <https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html>
- GitHub secure-organization guidance:
  <https://docs.github.com/en/code-security/tutorials/secure-your-organization/protect-against-threats>
- Render deploy hooks: <https://render.com/docs/deploy-hooks>
- Render free instances: <https://render.com/docs/free>
- Render health checks: <https://render.com/docs/health-checks>

## Ruled out — recorded so they are not re-proposed

### X2 — Reimplement the raw-text date parser in SQL — **ruled out**

`parse_schedule_date` (`domain/work_orders.py`) does three things SQL cannot
easily replicate: regex-matches `M/D/YYYY` **or** ISO with optional trailing
time; expands two-digit years (`year < 100 → +2000`); and catches `ValueError`
on invalid calendar dates so Feb 30 becomes `None` rather than an error. The
third is the blocker — Postgres `make_date` *raises* instead of returning NULL,
so an expression-only rewrite against the current raw text is not safe.

Superseded by A6, which captured the available win (not hydrating the whole
matching set to return 10 cards) with no behavior change.

This ruling does **not** prohibit SCL-014's triggered data-model change: after a
legacy-value audit and owner-approved malformed-date policy, a separately
validated typed sortable representation could make bounded SQL ordering safe.

### X3 — Paginate the unbounded collections — **shipped 2026-08-10**

Promoted and shipped the same day as a **safety ceiling rather than
pagination**, because the symptom was not occurring and two of the endpoints
back client-side search. Recorded here only because it was parked as out of
scope for being *a feature*, not for being unimportant — and measurement then
showed the feature half was never needed.

---

## Verified strengths at `ac99487` — re-audit after relevant change

These statements are scoped to the reviewed commit. Re-audit a statement when
its code, dependency, deployment topology, or named exception materially changes.

**Known drift since `ac99487` (checked 2026-08-16, statements not otherwise
re-audited):** the migration count below is now **32 revisions at head
`0c1d2e3f4a5b`**, not 31 at `fbc4e6a8d0f2`; the suite now collects **974** tests,
not 679/683. The `BackgroundTasks` statement is unchanged but now sits beside a
real-time dispatch task and a NetFacilities job coordinator, both supervised
through `lifespan.py` rather than `BackgroundTasks` — the finding still holds,
its context does not. Figures below are otherwise left at their audited values
on purpose: this is a dated record, not a live one.

- **Pydantic v1→v2 migration debt** — none. `pydantic==2.13.4`, already current.
- **`BackgroundTasks` durability** — no usage anywhere, so no dropped-job
  exposure. The CSV import is the workload that would normally live in a queue;
  it runs inline, threadpooled rather than blocking the loop.
- **Async boundary** — route handlers follow the established async/threadpool
  boundary. PRO-017 owns replacing volatile route counts with a generated check.
- **Error-translation consistency** — routers use the shared `to_http` boundary
  (63 direct router call sites at this baseline). PRO-017 owns count freshness.
- **API versioning** — routers mount at `/auth`, `/items`, `/work-orders` with
  no `/v1`. A non-issue while the SPA is the only client and ships in the same
  deploy. Becomes real the moment a mobile app or third-party integration
  consumes the API.
- **ORM and migrations** — SQLAlchemy 2.0 and 31 Alembic revisions at head
  (`fbc4e6a8d0f2`) provide a strong migration foundation. SCL-004 is the narrow
  exception: model metadata currently drifts from intended index/FK state.
- **Concurrency foundation** — `with_for_update()` protects core inventory and
  custody mutations. SCL-001 through SCL-003 and SEC-005 are the specifically
  demonstrated cross-table or multi-session exceptions; SCL-005/SCL-006 instead
  track transaction-boundary and partial-persistence risk.
- **Password hashing foundation** — scrypt with `hmac.compare_digest`, no
  third-party dependency. SEC-004 tracks policy, cost, and non-user timing; it
  does not replace or invalidate existing hashes merely by raising new-password
  rules, but it still owns weak-credential reset and KDF version/rehash migration.
- **Sessions and cookies** — session tokens are high entropy and stored hashed;
  production cookies are `HttpOnly`, `Secure`, and `SameSite`, with expiry and
  revocation behavior. SEC-011/SEC-016 own MFA, lifecycle, and review evidence.
- **Browser security posture** — CSP/HSTS and a no-CORS same-origin deployment
  form a strong baseline. SEC-017 is the explicit topology-change trigger.
- **Injection/output foundation** — ORM parameterization, HTML escaping, and URL
  validation are established. SEC-006 is the spreadsheet-output exception.
- **Authorization foundation** — role gates and server-side price redaction are
  broadly applied. SEC-002 and SEC-007 are the demonstrated workflow exceptions.
- **Upload/container foundation** — uploads are byte-capped and nonpersistent;
  the container runs non-root and production secrets are externally referenced.
  SEC-003 owns decoded-resource limits; SEC-008 owns the tracked local credential.
- **Layering** — `routers → services → domain → models` held consistently across
  nine resources.
