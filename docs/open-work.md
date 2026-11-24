# Open Work — every named improvement not yet implemented

**This is the only backlog file.** If an item is not here, it is not open.
Soft word budget: 12,000 (CLAUDE.md → Documentation conventions).

Sibling docs describe what the system *is*: `docs/current-state.md` (contracts,
invariants, data model, roles, known gaps — the authority; if it conflicts with
code, trust the code) and `docs/project-summary.md` (stack, architecture,
verification baseline).

**Nothing is scheduled.** Every item is an owner-requested feature, a confirmed
defect, a production-baseline candidate, a standing note with a named trigger,
optional enterprise work, or ruled out.

**Do not invent work to fill the queue — ask what the number actually is before
building what an item describes.** The last three items questioned before being
built (C2, B3, X3) described symptoms that were not occurring. Promotion into
section 1 as an `IMP-` item is mandatory before an observation becomes active
work.

---

## 1. Requested feature

IMP-004, IMP-035 and IMP-042 are the open requests; every other IMP number
through 042 is implemented or retired.

### IMP-004 — Mass Stage redesign

- **Logged** 2026-08-03 · **very low priority** (the owner's label) · *Mass Stage*

Make *New Mass Stage* a collapsible card, collapsed by default. Remove the
redundant Unit # field under Communities. Workflow becomes: search a work-order
**number** first (the search queries only the number), then load the rest after
a result is selected. Use mass staging to group work orders by Location: if a
saved Community appears in a work order's Location field, show that work order
under the Communities cards. Request logged only.

### IMP-035 — Item/work-order photo attachments

- **Logged** 2026-08-23 · *Items / Work Orders* · raised during `DEC-002` scoping

Attach photos to items and/or work orders (damage evidence, install proof, part
identification). Owner-flagged as a storage/processing-growth risk, not a plain
feature add; also `SCL-017`'s concrete future trigger. Needs its own scoping
pass (upload limits, storage backend, retention/deletion policy, whether it
reuses `SEC-003`'s image bounding) before promotion.

### IMP-042 — Material and catalogue requests from a work order

- **Logged** 2026-11-15 · *Work Orders / Requests* · outside the live rendering
  roadmap (W1–W7)

The owner needs material and catalogue requests filed from work orders "some
way"; the form is not chosen. The card's Request section and stocked "Add
requested material" lines were hidden 2026-11-06 (`ac95d23`). Still present:
`views/workOrderRequests.js` (loaded, never mounted; tests drive it via
`tests/frontend/helpers/detachedSections.js`) and every backend route.
Whatever brings requests back should follow the W2 patch rules
(`2026-11-14-work-order-live-rendering-design.md`, Stage 2). Needs its own
scoping pass before promotion.

---

## 2. Hardening — standing notes

None of this is scheduled. Each is a real property of the system with a **named
trigger** that promotes it.

### N-MEMORY-CRASH — production crashes from stepwise memory growth; cause unknown

**Trigger: already fired — this is the next workstream.** The endpoint memory
suite (`backend/scripts/memprobe.py`: harness, `sweep`, `soak`, `jumps`)
reproduces the growth locally to name the request. Environment is the
`inventory-local` container, never the host (`docs/current-state.md` → Local
Docker reproduction).

Readout so far:

- The all-route sweep found no route that repeats growth; it is not a per-route
  leak at that request count.
- The 30-minute soak reproduced one mid-run step: `GET /hub/admin` (global
  over-cap session sweep plus company-wide minutes) jumped about 14 MB and held.
  This is the Phase 4 candidate.
- Owed: a 120-minute soak (needs the machine kept awake) and, for production,
  exporting Render logs spanning the next step and running `jumps` on them.
- Also open: confirm the Render dashboard Auto-Deploy toggle is off.

### N-HUB-TAB-SHELL — `userHub.js` is at the 500-line rule (499)

A tab shell that grows ~55 lines per tab; the fifth tab (Report) pushed it over
and was wired in the established shape deliberately. Timesheets has since moved
out whole (`hubTimesheetsTab.js`); Messages went in at net zero lines (logic in
`hubMessages.js`). **Trigger:** the next tab, or any substantive
edit to the lazy-loading machinery. Extraction is mechanical:
`loadGraphs`/`loadReport` and their error renderers into a `hubTabs.js` that
owns the caches and request counters. Do it as its own change, verified by hand.

### N-MESSAGES-LATER — messaging features left out of v1

Named in the live-messaging spec as later, not owner-scheduled: photos,
work-order links, typing dots, reactions, editing or deleting a sent message,
muting, adding/removing group members after start, leaving a group, a native
over-other-apps bubble. Also owed: a **Messages tutorial script** (bubble, put
away, Hub tab). **Trigger:** an owner request naming one.

### N-WO-STATUS-EVENTS — no status history, so a live close can vanish

Work orders carry only `created_at`/`updated_at`/`completed_at`/`archived_at`;
nothing records when a status was entered, and a restore clears `archived_at`.
The weekly report's *completed* weeks are frozen records
(`work_order_report_weeks`); the week in progress is still a live view.
**Trigger:** any other surface needing to reconcile past state, or a per-status
timeline. Fix: a `work_order_status_events` table. Do not infer history from
`updated_at`.

### N-REPORT-EXPORT-AUDIT — the report Excel export joins the unlogged-export set

DEC-009 commits every CSV/report export to an audit record (actor, type, row
count, timestamp) in the log sink DEC-008 funds; `GET /hub/report/export` is a
member from the day it shipped and is not separately logged today. **Trigger:**
the sink landing — wire this export in then; a second, differently-shaped
export log is worse than the gap. It is Admin-only and company-wide, so it is
the higher-value audit record.

### N-ITEM-RESTORE — no item unarchive, and catalogue requests expose it

An archived item is search-invisible (`archived_at IS NULL` filter), so a user
searching a real-but-archived material files a catalogue request. The Admin
fulfilling it has no restore path: `override_archived` frees the *barcode*
(purging or retiring the archived row); creating a fresh row silently forks the
item's identity. Same shape as the archived-work-order gotcha, same likely fix:
an explicit gated `restore_item`. Also applies to the catalogue → material
chain: a fulfilment that links an archived item is impossible today.
**Trigger:** a catalogue request naming an archived item with any regularity.
**Done when triggered:** an Admin can restore from the fulfil form, and the
request links to the original row.

### N-NF-STEEL-SESSION — NetFacilities Steel session: two unverified edges

IMP-040 (per-user Steel cloud auth, owner-confirmed 2026-09-14) left two
properties with no automated check:

- **Vendor-side session health** (spec §4.4, `2026-08-28-netfacilities-cloud-auth`):
  the E7 deadline bounds a reaped session; nothing detects Steel reaping one
  early. **Trigger:** an enrichment run failing with a sign-in page while the
  stored session is inside its deadline.
- **The Playwright `download` listener is unverified over `connect_over_cdp`.**
  Every capture logs `capture_path=listener|poll`; the first production capture
  read `poll`. **Trigger:** one more `poll` reading — then delete the listener
  and its branch rather than keep two paths.

### N3 — decide the multi-instance story before scaling horizontally

**Trigger: adding a second instance.** Three things inherit it, worst last:
`entrypoint.sh` runs `alembic upgrade head` on every cold start (races across
instances); B3's rate limiter holds counters in process memory (the cap becomes
60/s per process, a deliberate trade); a realtime connection registry does not
degrade — it **silently halves delivery**, since connections are process-local
and instance A's users never receive instance B's events, with no error on
either side.

### N4 — reconsider serving the SPA from the API process

**Trigger: introducing a CDN** · deferred by design. `NoCacheStaticFiles` plus
per-request shell assembly deliberately solve the real blank-page stale-cache
failure; the cost is a Python round-trip per asset, no CDN, no content hashing.
`static/styles.css` is 7,048 lines, unminified, re-fetched on every navigation —
the number to watch.

### N6 — `services/work_orders.py` is 3,325 lines / 93 functions

**Trigger: none — this is a boundary rule, not a refactor request.** Its
frontend counterpart, the `workOrder*.js` group (~5,600 lines across 19 files,
largest 841), grows faster than the service; change risk concentrates in these
two areas. The extraction target already exists and works: `domain/work_orders.py`
holds the pure rules. **Further rule-shaped logic belongs behind that boundary**;
splitting the module for its own sake is churn with no behavior change.

### C2 — tool-custody N+1 (its risky half is already gone)

**Trigger: the Tools page feels slow, or the tool count grows enough to
matter.** `list_tools` still costs N+1 queries per page load (bounded by the X3
cap); the symptom is not occurring. The custody order is now pinned (first name,
last name, then `assigned_to_id`; tests in `test_tools_service.py`), so a
consolidated all-tools query returns provably identical order — cheap and safe
whenever someone wants the query count back. Only the list path needs it:
`_outstanding_for_user` and the archive guard don't care about order.

### N7 — `pyzbar` can break a fresh environment

**Trigger: new dev machine, or a runtime/base-image change.** It needs the
Visual C++ 2013 redistributable on Windows; the failure is a missing
`libiconv.dll` at import — naming neither `pyzbar` nor the real cause — and
takes down the whole app at import time rather than degrading decode alone.
Containerized deploys are unaffected; a bare Linux environment needs `libzbar0`
installed or the app fails at import the same way. Also noted in
`requirements.txt` and `current-state.md`.

### N8 — `/docs` and `/redoc` are CSP-broken

**Trigger: someone actually wants a working API explorer.** A4's
`default-src 'self'` CSP blocks their only assets (cdn.jsdelivr.net), so both
pages render ~1 KB blank shells; `/openapi.json` is unaffected. Fix: vendor
`swagger-ui-dist` into `static/vendor/` (the ZXing precedent) and pass
`swagger_js_url`/`swagger_css_url`. **Do not loosen CSP** for a developer
convenience.

### N9 — Web Push: deliberate limits (none are defects)

See `current-state.md` → API Surface → Web Push and
`docs/adding-a-notification-trigger.md`. Sequential fan-out in the background
task (hundreds of devices need a queue); no per-user opt-out (routing is role +
assignment only); no delivery record beyond the discarded
`{sent, dropped, failed}` log line; iOS needs a manual Home-Screen install per
device.

### N10 — Work Orders live status: three frontend gaps

Pinned (not fixed) by `tests/frontend/views/workOrders/realtime.test.js`; all
frontend-only.

- **Reassignment is asymmetric:** the gaining technician sees nothing until next
  page entry (subscriber ignores ids with no card; only restore emits the
  null-id signal). **Trigger:** a technician reports a new assignment not
  appearing until reload.
- **Two rapid status events on one card can resolve out of order:**
  `workOrderList.js:refreshCardSummary` has no request-ordering guard
  (`adminReview.js` has a monotonic request id). **Trigger:** a card showing an
  older status after a fast double change.
- **A card collapsed while its editor is open stays held indefinitely**
  (`workOrderList.js:isHeld`). **Trigger:** a badge stuck on an old status with
  no open card visible.

### N-CHARACTERIZED — defects pinned by tests, not fixed

Frontend characterization suites record today's behaviour, so each known defect
is green *as a bug*: the tests are the record, and fixing one means flipping its
pinning test in the same change. Grep the tests rather than expect a list here.
Groups, with the trigger being the next substantive edit to the area:

- **Work-order card (P2, `tests/frontend/views/workOrders/`):** dead empty state, silent status rollback on save, `"NaN"` hours.
- **Spine (P5):** nav, composition root, auth/boot 401 and batch-resume paths, items table, scan-and-go batch, History, hub tab shell, scanner widget, Mass Stage page.
- **Leaf views (P6):** hub clock/Dashboard/Technician/Admin, Tools page, Users page, push opt-in, shared `setMessage` class-wipe class of defect.
- **Remainder (P7):** User Requests, Admin Review, Low Stock, work-order Request section, catalogue prompt, scan harness, push service worker; `setMessage` class-wipe can make a second action on a card throw.

### N11 — notification triggers considered and deferred

**Trigger: a user asking to be told about one, or the first drive to a job
archived under them.** Ordered by value-to-effort, each costing the three steps
in `docs/adding-a-notification-trigger.md`: (1) Completed → Review notifies
Admin; (2) On-Hold notifies Team Lead and assignees; (3) Archive notifies
assignees (real operational cost); (4) NetFacilities enrichment finished
notifies the starting Admin (currently poll-only). A recount/missing-price push
remains unbuilt and unrequested. Excluded outright: customer/job detail in
bodies (lock-screen rule); digest/batching until real volume is seen (N14).

### N12 — auto-hold is the largest source of notification volume ever added

**Trigger: a Team Lead saying the On-Hold alerts are noise, or observably
ignoring them.** Stopping the last clock on an In-Progress work order auto-holds
it, and every entry into On-Hold notifies the routed Team Lead — a rule written
when On-Hold was deliberate, now firing several times a day per crew (lunch,
parts runs, end of shift). Chosen behavior: shipped loud to reveal whether the
volume is actually a problem. The mitigation is already scoped and deliberately
narrow: silence the `/tracking/stop` trigger site alone, leaving `/hold` and the
PATCH arm untouched. See `docs/notification-events.md`.

### N14 — the bulk import send is the first batched notification

**Trigger: a second batching case, or an import send wrong in a way
per-work-order sends would not have been.** `work_order.supervisor_assigned_bulk`
sends one push per matched Team Lead per import. **Not precedent** — a second
batching case argues its own volume evidence. **Under-counts on purpose** — only
work orders the import *created* count, so the push and `supervisors_matched`
never disagree; widen both together if silence ever matters more.

---

## 3. UX observations — never re-audited

July 2026 findings never promoted or dismissed: observations, **not** agreed
work. Numbers are the original review's and are not renumbered. Promote one
into section 1 as an `IMP-` item before treating it as active.

### 21. Team Lead+ "Add Stock" path is one toggle deep

The direction toggle (Add Stock / Take Out) is hidden behind *Manual entry &
stock options* by default. Reasonable given dispense-only is the common case.

**Not an implementation item** — it asks the owner to confirm the
discoverability tradeoff is intended rather than accidental, so it can be closed
with a yes or a no. The cheapest thing on this list to close.

Files: `backend/static/pages/transaction.html`,
`backend/static/views/transactions.js`.

### 23. No hardware (keyboard-wedge) barcode scanner support

A Bluetooth laser scanner typically types the barcode plus Enter — faster and
more reliable in warehouse lighting than camera decoding. Today those keystrokes
go nowhere unless a text input is focused. A global fast-keystroke accumulator
on the Transaction page feeding the existing `resolveBarcode` path would add
this without disturbing the camera flow.

**Additive, not a rewrite.** Assumes the crew has or wants scanners — worth one
question before any code.

Files: `backend/static/views/scan.js`, `backend/static/views/transactions.js`.

### Dropdown-normalization follow-ups (2026-08-21)

- **`--gray-600` is used but never defined.** `styles.css`
  (`.user-request-resolved .user-request-status`) reads `var(--gray-600)`;
  `:root` declares 50/100/200/300/400/500/700/900 and no 600, so a resolved user
  request inherits the panel text color instead of going muted. Add the token
  or point the rule at `--text-panel-mute`.
- **`.lu-card-body` still uses light-panel colors** (`--color-ink` text,
  `--gray-300` borders on the work-order lookup card), which the design system
  says disappear on the dark canvas.
- **`scrollIntoView({ behavior: "smooth" })` ignores reduced-motion.** The CSS
  `prefers-reduced-motion` block cannot reach a scripted scroll. Call sites
  across `views/` need to read the media query and pass `"auto"`.

---

## 4. Stack maturity register — candidates for later roadmapping

**10/10 target:** a business-critical internal application, one region,
moderate growth, small operating team — not zero risk, unlimited scale, SOC 2,
or multi-region. Graduation: every `Must-fix` Done with retained evidence;
every `Production baseline` Done or externally evidenced; every `Measured
trigger` instrumented and owned (may stay unbuilt while its trigger is false);
every `Optional enterprise` explicitly accepted or excluded; owner decisions
resolved. Candidate states: `Candidate`, `Approved`, `Scheduled`, `In progress`,
`Done`, `Deferred`, `Declined`. Effort `S`/`M`/`L`/`XL` is relative. Each row
below carries its class and its dependency or trigger; an owner, target state
and verification artifact are set when roadmapped.

### Recorded decisions

All twelve owner decisions were resolved 2026-08-23.

- **DEC-001 — target:** business-critical, single-region, moderate growth.
  `SEC-019`/`SCL-020`/`SCL-021` are `Declined` (exclusion, not deferral);
  Must-fix and Production-baseline items apply at full weight. Revisit if
  DEC-002 growth changes.
- **DEC-002 — scale:** ~100 concurrent peak per instance. Growth (~10k users in
  24 months) comes from fleet repeatability — one app + one DB per university —
  so `PRO-016`, `PRO-001`/`PRO-006`, `SCL-010` are load-bearing per-deployment
  costs. Import ceiling ~800 rows (sizes `SCL-005`). Photos = `IMP-035`.
- **DEC-003 — SLO:** true 24/7, no maintenance window; RTO 15–30 min; RPO ~15
  min; protect current p95. So `PRO-004` first, `SCL-010` needs expand/contract,
  `PRO-002` rollback rehearsed to RTO, `PRO-014` drills restores (Render's 3-day
  PITR is retention, not proven recovery), `PRO-012` load-tests ~100 concurrent.
- **DEC-004 — identity:** local credentials + TOTP MFA for Admin/Owner only; no
  external IdP. Admin/Owner get the approved-standard length (NIST 800-63B);
  Team Lead/Technician stay sole-factor, so the ≥15-character minimum binds
  them. The enumeration-timing gap and 4-character minimum stay in scope for
  every account. `SEC-011` = TOTP enrollment/recovery/step-up for Admin/Owner;
  lost-authenticator recovery needs its own decision.
- **DEC-005 — visibility vs writing (revised 2026-10-14):** every recognised
  role sees every live work order; archiving removes it from view. A Technician
  *writes* only to a work order they are on the crew of
  (`require_crew_for_technician`, 403 otherwise); Begin Charging puts them on it.
- **DEC-006 — Mass Stage ownership:** creator-owned; Admin/Owner/TechFM OA
  bypass. `get_stage` and mutations match `list_stages` scoping; inaccessible
  IDs return 404. No peer-Team Lead coverage — if that bites, add a logged
  Admin-gated transfer action. Scopes `SEC-007`.
- **DEC-007 — imports:** preview-then-commit, undo, skip-and-report with skipped
  rows **individually named**. Undo needs each import to durably record what it
  changed. Fully scopes `SCL-005` (`XL`); narrows `SCL-006` to per-row commit +
  change-log atomicity.
- **DEC-008 — budget:** small now, nothing structurally blocking growth.
  Always-on web mandatory; monitoring (`PRO-013`) and scanning (`PRO-006`) start
  free-tier; staging (`PRO-003`) waits for `PRO-016`'s template; **log retention
  (`SEC-012`) starts now** — unrecorded audit history is unrecoverable.
- **DEC-009 — data policy:** no known external obligation; archive-forever is
  permanent (no purge), so `SCL-017` is storage/performance-triggered only;
  exports become audited events in the DEC-008 sink. Scopes `SEC-018`.
- **DEC-010 — governance:** solo maintainer, accepted plainly: branch
  protection with required checks and blocked force-push/deletion; human review
  waived under a recorded exception; no break-glass access (bus factor one).
  `PRO-018` targets this; `SEC-013`/`SEC-016` inherit the one-person loop.
- **DEC-011 — cross-origin clients:** none planned, likely later; kept open by
  discipline. Authorization predicates take plain values (role, user id,
  ownership), never the request or cookie, so a bearer-token transport is
  additive. `SEC-017` stays a measured trigger.
- **DEC-012 — exports:** `full` round-trips into import → CSV-safe escaping only
  (XLSX ruled out); `client` is never re-imported → escaping or explicit-text
  XLSX. Scopes `SEC-006`; both need fixture + Excel/LibreOffice verification.

### Security candidates

| ID | Status | What / done when / dependency |
|---|---|---|
| SEC-001 | Candidate | Must-fix, L. Global limiter keys off any raw session cookie (`main.py` limiter, `services/rate_limit.py` process-local buckets); rotating bogus cookies bypass it. Done when invalid/rotating cookies cannot bypass the IP budget, authed traffic gets IP + principal limits, trusted-proxy and multi-instance behavior tested. Needs Render ingress/shared-store choice. |
| SEC-002 | Partial | Must-fix, M. Crew half shipped (`routers/transactions.py` `require_crew_for_technician`). Open: a dispense by an archived work-order ID is still accepted. Done when it returns 404 with no mutation, enforced in the service transaction. DEC-005. |
| SEC-003 | Candidate | Must-fix, M. `_uploads.py` caps compressed bytes but `services/barcodes.py` fully decodes with no dimension/pixel ceiling. Bound format, pixels, memory, concurrency, wall time; reject oversized bodies before multipart parsing. Done when bomb/boundary/10-way concurrent fixtures stay in budget. |
| SEC-004 | OPEN | Must-fix, M. `schemas/auth.py` permits 4-character passwords; `services/auth.py` skips scrypt for absent/archived users (known-wrong ~79.55 ms vs unknown ~0.028 ms). Raise policy per DEC-004 (≥15 chars sole-factor, ≥64 accepted), dummy-hash non-users, reject common values, migration/reset path. |
| SEC-005 | Candidate | Must-fix, M. `services/login_throttle.py` read/increment/write is unlocked and the IP-wide layer defaults off. Atomic counters per account, IP, account+IP. Done when 100 concurrent failures record exactly 100 and multi-IP tests hold with no 5xx. Needs SEC-001 and lockout thresholds. |
| SEC-006 | Candidate | Must-fix, S-M. Work-order export (`services/work_orders.py` CSV writer) sends user/vendor text straight through `csv.writer`; formulas not neutralized. Encode cells starting `= + - @` tab CR. DEC-012. |
| SEC-007 | Candidate | Must-fix, M. `services/mass_staging.py` `list_stages` is creator-scoped but ID-based detail/mutations don't receive the caller. One policy for every operation; inaccessible IDs 404; role/ownership matrix test. DEC-006. |
| SEC-008 | Candidate | Must-fix, S/M. `backend/.env` was tracked from the first commit; no longer in the tree (checked 2026-11-20). Unevidenced: reuse assessment, rotation, redacted `.env.example`, full-history scan, history-rewrite decision. PRO-006 owns ongoing prevention. |
| SEC-009 | Candidate | Baseline, S. `entrypoint.sh` leaves Uvicorn access logs on, which carry query strings. Disable/redact; keep route template, status, duration, request ID. |
| SEC-010 | Candidate | Baseline, M. `entrypoint.sh` runs Alembic and the app with one `DATABASE_URL`, so the server holds DDL rights. Split migration-owner and runtime DML roles. Needs PRO-001/002 and provider role capability. |
| SEC-011 | Candidate | Baseline, XL, repo gap. TOTP MFA for Admin/Owner, step-up, idle timeout, session list/revoke-all, offboarding propagation. DEC-004, DEC-008. |
| SEC-012 | Candidate | Baseline, L, repo gap. Append-only external audit sink with material-event coverage (auth, roles, exports, adjustments, imports, WOs, stages, admin). Started now per DEC-008. DEC-009. |
| SEC-013 | Candidate | Baseline, M, external. Tested detection signals and response SLAs for credential attacks, privilege changes, exports, decoder abuse. Needs SEC-012, PRO-013, PRO-015. |
| SEC-014 | Candidate | Baseline, M, external. Dated proof of TLS, DB exposure, forwarded-header trust, ingress limits, environment separation. PRO-005 collects evidence. |
| SEC-015 | Candidate | Baseline, M, repo gap + external. Maintained threat model, abuse cases as regression tests, annual independent test. DEC-008. |
| SEC-016 | Candidate | Baseline, S-M recurring, external. Quarterly Admin/Owner access review, no shared accounts, offboarding SLA. DEC-004, DEC-010. |
| SEC-017 | Candidate | Measured trigger, S-M. Origin/CSRF enforcement before any untrusted sibling domain or cross-origin cookie client exists. DEC-011. |
| SEC-018 | Candidate | Baseline, M, external. Owned data inventory, retention/deletion policy, export entitlement/audit rules. DEC-009. |
| SEC-019 | Declined | Optional enterprise (DEC-001, 2026-08-23): contractual/privacy/legal-hold controls. Revisit if DEC-002 growth changes the target. |
| SEC-020 | OPEN | Must-fix, S. `EDITABLE_DETAILS` (`services/user_requests.py`) whitelists keys but nothing validates values (`schemas/user_requests.py` types `details` as `dict[str, Any]`). Reproduced: `quantity: "abc"` stores then 500s at fulfilment; `quantity: -5` writes a negative line onto the work order. UI-reachable (edit input's `min` never runs; `views/userRequests.js` sends the raw string). Done when the patch is validated per type at the schema boundary (reuse `CatalogueRequestCreate`'s `Decimal gt=0`), malformed input returns 422/409 with no mutation, and a regression test fails without the fix. Open shape question: typed per-type patch models vs per-key coercion. |

### Professionalism candidates

| ID | Status | What / done when / dependency |
|---|---|---|
| PRO-001 | Candidate | Must-fix, L. `.github/workflows/ci.yml` tests the checkout but never builds `backend/Dockerfile`; deploy is a manual click not bound to the tested SHA. Build, boot and smoke the image against migrated Postgres, deploy that digest. Registry/deploy choice, DEC-008. |
| PRO-002 | Candidate | Must-fix, M. No deploy concurrency control, rollout polling, SHA confirmation or post-deploy smoke; rollback unpracticed. Needs PRO-001, DEC-003. |
| PRO-003 | Candidate | Baseline, L, repo gap. `render.yaml` has one service on the production DB; no staging. Promote the same image through an isolated service/DB/secrets. Waits for PRO-016. |
| PRO-004 | Partial | Must-fix, S. `render.yaml` declares `plan: standard` (2 GB / 1 CPU, always-on); cold start gone. Remaining: measured 30-day availability, warm latency, restart time and 30% peak headroom against the SLO (N-MEMORY-CRASH is the live headroom risk). |
| PRO-005 | Candidate | Baseline, M, external. Quarterly check of operators, branch, hooks, DB binding, plan, PITR, hostname against repo intent. DEC-010. |
| PRO-006 | Candidate | Baseline, L. Hash-locked deps, pinned action/image digests, whole-image scans, SBOM, license inventory, secret scanning (SEC-008 prevention). N7 covers zbar portability. |
| PRO-007 | Candidate | Baseline, M. About 30 test files use `TestClient`, but coverage is per-feature and no OpenAPI snapshot blocks breaking changes. |
| PRO-008 | In progress | Baseline, L. Vitest + jsdom + MSW harness complete (blocking coverage gate in CI; figures in `current-state.md`); Playwright smoke layer gates deploy. Unbuilt: deeper browser journeys (login, item lookup, stock/dispense, work-order update, Mass Stage, request resolution) against disposable data. Needs PRO-003 or an ephemeral environment. Pinned defects: N-CHARACTERIZED. |
| PRO-009 | Candidate | Baseline, L. Ordinary DB fixture is one connection, so races are unproven. Build a multi-session harness for stock/void, WO deletion, custody, Mass Stage, archive, barcode, login throttle, import. |
| PRO-010 | Candidate | Baseline, M. No Ruff, Python type gate, ESLint/checkJs or coverage-regression signal in CI; adopt ratcheted baselines. |
| PRO-011 | Candidate | Baseline, M, repo gap. Accessibility is manual; define the support matrix and add axe checks, zoom/keyboard/screen-reader passes. Needs PRO-008. |
| PRO-012 | Candidate | Baseline, L, repo gap. No approved SLO or load proof; target 2x observed peak plus 3x burst within p95/p99. DEC-002, DEC-003. |
| PRO-013 | Candidate | Baseline, M, external. Centralized telemetry, synthetics, alerts with owners. Needs PRO-004, PRO-012, provider choice. |
| PRO-014 | Candidate | Must-fix, L, external. Three-day PITR is documented but no restore drill exists; quarterly isolated restore verifying head, counts, ledger invariants. DEC-003, 008, 009. |
| PRO-015 | Candidate | Baseline, M, repo gap. Tested runbooks (deploy/rollback, DB outage, wrong import, wrong DB binding, secret exposure, zbar, storage, malicious upload). |
| PRO-016 | Candidate | Baseline, M. `README.md` is links only; clean Windows and Linux clones should reach green in 30 minutes with a redacted `.env.example`. Needs SEC-008, PRO-006. |
| PRO-017 | Candidate | Baseline, S-M. Migration/route/test counts quoted in `docs/` drift; CI should check the facts the docs quote. |
| PRO-018 | Candidate | Baseline, M, external. Protected `main`, required checks, CODEOWNERS, `SECURITY.md`, break-glass process; solo-maintainer exception recorded. DEC-010. |
| PRO-019 | Candidate | Baseline, S-M, repo gap. Light durable release record (SHA, migrations, rollback, user-visible notes) and a named support path. |
| PRO-020 | Candidate | Baseline, M, repo gap. Scheduled read-only invariant reconciliation (impossible quantities, void/contributor mismatch, duplicate custody, orphaned links) with alarms. Needs PRO-013, PRO-015. |
| PRO-021 | OPEN | Must-fix, S. Whitespace-only `searched_text` returns 500: one shared validator in `schemas/user_requests.py` serves a required and an optional field and returns `strip() or None`; `min_length` passed on the untrimmed value, then `create_catalogue_request` calls `.strip()` on `None`. API-only (`views/catalogueRequest.js` trims first) — the same client-guard-for-server-guard pattern as SEC-020. Done when trimming runs in a `mode="before"` validator, required and optional fields get separate validators, and whitespace-only input returns 422 with no row. |

### Scalability and reliability candidates

| ID | Status | What / done when / trigger |
|---|---|---|
| SCL-001 | Candidate | Must-fix, L. Primary and alternate barcode uniqueness live in two tables with check-then-write in `services/items.py`; concurrent claims can both commit. One DB-enforced namespace plus backfill. |
| SCL-002 | Candidate | Must-fix, M. Transaction void locks Transaction→Item; work-order-line deletion locks Item→Transactions. One global lock order; no `40P01`. Needs PRO-009. |
| SCL-003 | Candidate | Must-fix, L. Mass Stage state checks and slot ordering are unlocked; lock the stage, enforce transitions transactionally, unique `(stage_id, sort_order)`. Needs SCL-002, PRO-009. |
| SCL-004 | Candidate | Must-fix, S. `alembic check` proposes six index removals, two transaction-FK rewrites and one `push_subscriptions.user_id` index addition (rechecked 2026-11-20); align metadata without deleting intended protections. |
| SCL-005 | Candidate | Must-fix, XL. Work Order import commits row by row and applies immediately; a prior mistaken 800-row import forced a DB cutover. Preview/diff, batch identity, approval, undo. DEC-007. |
| SCL-006 | Candidate | Baseline, L. Helpers like `_merge_reference` commit internally; helpers should `flush`, top-level services own commit/rollback. Designed first, delivered with SCL-002/003/005. |
| SCL-008 | Candidate | Baseline, M. No declared pool, pool-wait, statement or lock timeout budget; keep pools under 80% of DB connections and waits under the request deadline. |
| SCL-009 | Candidate | Baseline, L. Stock/dispense POSTs are not idempotent, so retries duplicate effects; scoped idempotency keys. Owner picks key lifetime. |
| SCL-010 | Candidate | Baseline, L. Every start runs migrations before Uvicorn (races at 2+ instances, couples start to DDL); one runner/advisory lock and expand/contract. Needs PRO-001, PRO-014, SEC-010. |
| SCL-011 | Candidate | Baseline, M. Import/export share request-worker capacity; admission, concurrency, RSS and deadline budgets (SEC-003 owns decoder limits). |
| SCL-012 | Measured trigger | L. History does exact count + offset sort without a full index set. Keyset `(created_at,id)` pagination, server-side report. Trigger: slow-query evidence, p95 breach, or material growth. |
| SCL-013 | Measured trigger | XL. 5,000-row ceilings bound memory but are not pagination. Cursor/search contracts. Trigger: any `list.truncated`, payload above 2 MB, or list-route SLO breach. |
| SCL-014 | Measured trigger | L. Work Orders scan and Python-sort because schedule dates are raw text; add a validated sortable column (X2 does not forbid this). Trigger: scanned/returned ratio above 20x or list p95 breach. |
| SCL-015 | Measured trigger | L. Work Order export hydrates everything into one string; stream or make async. Trigger: response above 25 MB, over 20% process memory, or over half the request deadline. SEC-006. |
| SCL-016 | Measured trigger | XL. Import, export and decode run inline; durable jobs only when measured. Trigger: p95 near 75% of the deadline, any timeout, or concurrency breaching ordinary SLO. |
| SCL-017 | Measured trigger | XL. Durable growth tables (transactions, tool transactions, requests, work orders); archive/partition without weakening audit. Trigger: projected exhaustion, high-water mark, failed maintenance window. DEC-009. |
| SCL-018 | Measured trigger | M. Roles/statuses/modes are unconstrained text with one app writer; add `CHECK` constraints before a second writer exists. |
| SCL-019 | Measured trigger | L. Normalized search uses `regexp_replace(lower(...))` plus leading wildcards, not indexable; measure before generated columns or trigram indexes. Trigger: item-search p95 breach or catalogue growth. |
| SCL-020 | Declined | Optional enterprise (DEC-001): multi-zone HA. N3 owns second-instance readiness. Revisit if DEC-002 growth changes the target. |
| SCL-021 | Declined | Optional enterprise (DEC-001): read replica / search index. Would trigger on primary read CPU above 70% after query fixes. |
| SCL-022 | Candidate | Baseline, M. No bounded whole-transaction retry for `40001`/`40P01`; retry only explicitly safe transactions, never after an uncertain commit. Needs SCL-002/008/009, PRO-009. |

N3, N4, C2, N6, N7 and N8 above are part of this register without duplicate
tickets.

### Dependency groups for later roadmapping

Sequencing constraints, not a schedule:

1. **Resolve the target:** DEC-001–004 (scope, load, SLO, identity), then DEC-005–012.
2. **Close confirmed exposure:** SEC-001–008, SCL-001–005, PRO-001/002/004/014.
3. **Build the operating floor:** release/staging, least privilege, supply chain, backups, telemetry, runbooks, onboarding, governance.
4. **Prove boundaries:** ASGI/browser/concurrency/security tests, load tests, threat model, accessibility, independent assessment.
5. **Measured scale work only on evidence:** N3, N4, C2, SCL-012–019.
6. **Enterprise scope:** SEC-019, SCL-020/021 unless DEC-001 changes.

### External standards

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

### Attendance: billed column and analog time dial — **ruled out**

- A per-person **billed** column beside clocked and charged:
  `billed_labor_minutes` rounds a work order's *combined* labor to 30 minutes
  across every technician and day, so no per-person-per-day billed number
  exists. Reopen only with a per-person billing rule behind it.
- `promptTime()`'s analog dial: the dropdowns + nudge row are complete and
  keyboard-accessible; the dial is optional polish.
