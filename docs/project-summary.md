# Project Summary

## What it is

A **self-hosted inventory + work-order staging system** for physical materials tracked by barcode — built for a field crew scanning items on a phone, plus supervisors/admins doing office-side review and billing.

**Stack:** a single FastAPI process serving both the JSON API and a no-build static SPA (`backend/static`, plain ES modules — no bundler). PostgreSQL via SQLAlchemy + Alembic. Barcode *uploads* decode server-side (`pyzbar`/zbar); *live camera* scanning uses vendored `@zxing/browser`. One same-origin WebSocket (`/ws`) carries real-time cache invalidation — REST stays the source of truth. Read-only NetFacilities enrichment drives a bundled Playwright Chromium. Deploys as one Docker web service + one managed Postgres on Render (port 8124).

**Architecture** is a strict layer chain: `routers → schemas/services → domain/models → database`. Routers stay thin (parse, auth, delegate); services own DB queries/locks/commits; domain modules are pure rules (no FastAPI/SQLAlchemy). Backend role gates are authoritative — frontend role hiding is UX-only.

## Core domains

- **Items, transactions & User Requests** — find/create/edit items by barcode; Find Item opens with no item request or native suggestion popup, then explicit Search or Load All retrieves full records. Stock, dispense, correct (append-only `adjust` rows), and void (soft delete, reverses stock). A Scan / Stock or Work Orders Add Item dispense beyond the recorded count is saved with a negative expected balance and atomically raises a durable TechFM OA and above inventory-recount request; removing the source transaction/line resolves it. Prices/links are cost-sensitive and redacted below TechFM OA. Row locks guard every quantity change; money is `Decimal`.
- **Work orders** — first-class standalone, import-only entities whose case-insensitive identity is the **number**. Live workflow is Created → Assigned → In-Progress → Completed → Review, with On-Hold as a pause state; Closed is archived. Work orders support multiple worker assignments: active Technicians and Supervisors may perform work, while active TechFM OAs, Admins, and Supervisors may supervise. Assigned workers receive narrow card actions without general status permission: Set In-Progress → Mark Completed, Place On-Hold only while In-Progress, and Resume In-Progress only while On-Hold. Review requires Completed state and a second person: Admin+ (Admin proper, not TechFM OA) or the routed Supervisor, provided the caller is not assigned to the work. Missing imported tasks become clickable NetFacilities URLs; that exact synthetic value can be replaced by a later real task, while real/manual tasks retain normal fill-blank protection. An append-only note log carries server-generated Central time/date and authenticated full name; aggregate material billing and per-worker labor bill at $62.50/hour after combined duration rounds upward to 30 minutes. Edit permissions are least-privilege: Technician = notes/add material/narrow worker actions; Supervisor+ = routing/general status/mode/labor/material corrections; TechFM OA+ = imported metadata and archive from any live status. Supervisors see the shared unassigned pickup queue, work routed to themselves, and work where they are assigned as a worker. Pickup and import merges lock the same row; a stale pickup receives a named 409, while import fills supervisor routing only when the locked row is still unassigned, preserving manual reroutes. Archived import matches are counted as closed and ignored. The server-side list composes status, service type, routed supervisor, derived community, exact scheduled date, and number filters with AND, then sorts by parsed Scheduled Date descending. TechFM OA+ can export that uncapped filtered set as a re-importable operational CSV; the client billing/receipt CSV remains scope-based. Everything is server-scoped by role (Technician→any assignment, Supervisor→unassigned/self-routed/worker-assigned, TechFM OA and above→all).
- **Mass staging** — truck-loading plans per community/building/unit that *reference* work orders; forward-only lifecycle planning→loading→completed.
- **Tools** — parallel to items but smaller (no price/location); ledger-derived custody ("who has what" is computed, never stored). Checkout is TechFM OA+, check-in any role.
- **Users/roles** — `owner > admin > supervisor > technician`; unique usernames
  stay login/account identifiers, while first + last names drive operational
  display and CSV supervisor routing. Legacy NULL names are explicitly editable
  on Users, login usernames can be corrected in the same flow, and TechFM OA+ may
  change only strictly subordinate roles. Role changes revoke active sessions.
  Five roles, strictly ranked: `technician 0 < supervisor 1 < techfm_oa 2 <
  admin 3 < owner 4`. **TechFM OA** carries the whole Admin toolkit minus two
  things, both consequences of its rank rather than special cases: it cannot
  send a work order to Review, and it cannot re-role an Admin or Owner or hand
  those roles out.
  Scrypt sessions use an HttpOnly cookie; archive is soft-delete with a
  tool-custody guard and an explicit force-check-in retry.
- **NetFacilities enrichment** — read-only, TechFM OA-gated backfill of imported
  work orders from the upstream system. A TechFM OA or Admin signs in through a local headed
  browser (or an operator provisions a secret storage-state file on Render); one
  serialized job then re-reads existing live work orders through an isolated
  bundled Chromium with subresources blocked, and may fill only exact-fallback
  Task/Symptom and blank Priority. It never creates a work order — CSV import
  remains the sole create path.
- **Real-time invalidation** — one same-origin `/ws` WebSocket per authenticated
  browser. The envelope is exactly `type`, `id`, `req` and never carries row data
  or an actor; it tells a subscribed view to refetch over REST. The only current
  event is `work_order.review_queue.changed` (TechFM OA and above only). Emission is
  best-effort and never affects the durable HTTP write.

## Documentation map

**Four files, consolidated 2026-08-10** from ten. Shipped history and the
per-backlog split were removed — git holds the history, and the three separate
backlogs had drifted out of agreement with each other.

- **`docs/open-work.md`** — **the only backlog file.** Every named improvement
  not yet implemented, with its full write-up, plus what was ruled out and what
  was audited and found to be a non-issue. Read this when asking what remains.
- **`docs/current-state.md`** — the durable contract/invariants reference (data
  model, hard invariants, API surface, roles, known gaps). "If it conflicts with
  code, trust the code."
- **`docs/endpoint-map.md`** — traces every endpoint DB↔view
  (router→service→table, api.js→view), plus full request/response contracts, an
  error catalog, and service algorithms — meant to make reading source
  unnecessary.
- **`docs/project-summary.md`** — this file: what the app is, stack,
  architecture, and the verification baseline.

A fifth file was added 2026-08-18 and does not reopen the split above, because
it is a **procedure** rather than a backlog or a contract reference:

- **`docs/adding-a-notification-trigger.md`** — how to wire a business event to
  a Web Push notification: the three files a trigger touches, the five rules
  that are each a bug someone already nearly shipped, and what to verify by
  hand. Read it before touching `services/push.py` or adding a `notify_*` call.

## Current baseline

Last reconciled: 2026-08-16 against `main` at `4a211fb`. The backend declares
**79 router operations** across 11 routers (78 HTTP + the `/ws` WebSocket), plus
3 app-level routes in `main.py` (`/`, `/healthz`, `/db-test`) for **82 total**.
Alembic head is **`0c1d2e3f4a5b`** (32 revisions) and the suite collects
**974 tests**.

Older documents are historical if they use `73bdc95`, `19e661c`, `0566a64`, or
`Sane Roles` as the baseline, or if they quote any of these superseded figures:

| Superseded figure | Baseline it describes |
|---|---|
| 72 operations, head `faa2c4e6b8d0`, 478 tests | 2026-08-06 |
| 69 operations / 9 routers, head `fbc4e6a8d0f2` (31 revisions), 659 tests | 2026-08-10 (`f0e3b3c`) |

IMP-001 through IMP-003 and IMP-005 through IMP-033 are implemented.
IMP-004 (the Mass Stage redesign) is the only open requested improvement and
remains very low priority — see `docs/open-work.md`.

Capabilities added after the improvement batch include:

- Any work-order material path now raises one deduplicated missing-price User
  Request per item with a NULL or non-positive price (`$0.00` included),
  collecting all affected work-order numbers. Its
  TechFM OA and above card saves Price and Product Link together; the item update keeps
  the request open until a positive price and nonblank link both exist, then
  resolves it atomically. Existing live work-order items are backfilled by
  migrations `f9b1d3e5a7c9` and `faa2c4e6b8d0`, and their totals
  immediately use the live price.

- Scan / Stock now starts a scoped Assigned work order in place after the
  Technician/Supervisor confirms, using a narrow status action rather than
  general Technician status editing. Every committed batch line has Remove;
  Technicians are limited server-side to their own work-order dispenses.
- Short-count dispenses from Scan / Stock or Work Orders Add Item are recorded
  instead of blocked. The active surface turns red with `Please re-count stock`,
  and an TechFM OA and above User Requests page shows
  item, work order, user, recorded-before, dispensed, and shortage context with
  open/resolved management. The generic queue is migration-backed and the
  source transaction/request lifecycle stays atomic.
- Material the catalogue has no row for is reported as an **item request** from
  an empty search on Work Orders or Find Item, by any signed-in role. An
  TechFM OA and above fulfils it by linking an existing item or creating one; that logs
  the material retroactively (never moving stock) on the originating work order
  and cascades to confirmed sibling requests for the same material, each onto
  its own work order. A closed work order is warned about and skipped rather
  than blocking the catalogue fix. All three request types can also be edited in
  place, except a recount's frozen audit numbers.

- User administration can replace first/last/login names; TechFM OA+ can change a
  strictly subordinate user's role and revoke that user's sessions; user archive
  can force-check-in outstanding tools before disabling the account.
- TechFM OA+ work-order export supports `variant=full`, whose import headers make the
  CSV re-importable through the idempotent fill-blanks path, and `variant=client`,
  whose material/labor totals and full fixed-width receipt match Admin Review.
  Backend `domain/receipt.py` and frontend `adminReviewReceipt.js` intentionally
  render the same 41-character contract.
  Download names use `MM-DD-YY_HH-MM_filter1-filter2.csv` in UTC; filtered
  exports list every active filter and client exports use `client-<scope>`.
- Work Orders advanced search composes status, dynamic service type, assigned
  supervisor, derived community, exact scheduled date, and number with AND.
  Community membership is derived from structured/raw location text; Academics
  is the fallback. Cards and operational exports sort parsed Scheduled Date
  descending, with malformed/blank legacy values last. Export filtered CSV sits
  beside Search and uses the full active result set; For Client is unchanged.
  When an TechFM OA and above number search exactly identifies an archived row, the
  shared modal says `Work Order has been closed.` and offers Restore or Close;
  Restore uses the existing unarchive endpoint and reloads the matching live card.
- Expanded Work Order controls follow the backend role matrix. TechFM OA and above Edit
  details includes imported metadata plus operations; Supervisor sees only
  supervisor, technicians, and status plus separate mode/labor/material-correction
  controls; Technician sees Notes, Add Item, and the assigned-worker walkthrough.
  Edit details is a nested card, collapsed by default beneath the persistent
  read-only overview, and is unchanged by the walkthrough. Its status dropdown
  remains the Supervisor's general Created/Assigned → In-Progress, rollback, and
  On-Hold control. The card's primary quick button advances an assigned worker
  from Set In-Progress to Mark Completed and then disappears; only while
  In-Progress, a second Place On-Hold button is available; while On-Hold, one
  Resume In-Progress button replaces it. Send to Review is shown
  only to unassigned Admin+ or the unassigned routed Supervisor, and the backend
  enforces this second-person handoff from Completed. The technician
  assignment editor searches active Technicians and Supervisors by full name,
  shows matches only while searching, and lists removable selected workers below the search;
  Save replaces the complete plural assignment set. The Supervisor selector
  lists active Admins and Supervisors. Notes, Materials, and Labor
  are also nested cards that start collapsed. Notes displays its accumulated
  text log above an empty input; Save appends `[TIME] [MMDDYY] [User]` metadata,
  clears the input, and closes the card. Materials and Labor reopen after their
  write-triggered detail refreshes so the changed rows remain visible. Logged material rows, the total, and Add Item controls
  stay grouped inside Materials. TechFM OA and above additionally receives a confirmed
  Archive action on every expanded live-status card.
- Supervisors share unassigned Work Orders as a pickup queue. Edit Details sends
  the originally rendered supervisor as an optimistic precondition; a competing
  pickup returns the current supervisor's full name in a 409 prompt and reloads
  the page after dismissal. Import and manual routing serialize on a row lock,
  so import assigns only a still-unassigned row and never overwrites a manual
  reroute.
- Owner-only legacy cleanup exposes a hidden-by-default Re-archive button in the
  Work Orders import/export section. It previews the number of live
  `legacy=true` rows in the existing modal, atomically soft-archives them after
  confirmation, reports the actual affected count, and reloads the list. Both
  route and service gates require Owner exactly.

## Verification baseline

- Backend suite as of 2026-08-16: **974 tests collected**
  (`backend\venv\Scripts\python.exe -m pytest --collect-only -q`). Collection
  needs no database. The authoritative **pass** count comes from CI, which runs
  the suite against its own Postgres service — a local run additionally needs a
  reachable `DATABASE_URL`. Coverage spans the Work Order
  authored/timestamped append-only note log, Scan/Stock and
  Technician/Supervisor Work Orders short-count recount creation, Technician
  scan-removal boundaries, automatic request resolution,
  missing-price/link deduplication and completion, request-queue management,
  assigned-worker start/completion walkthrough and two-person Review handoff,
  the NetFacilities enrichment stack, the real-time invalidation layer, and the
  rate-limit (B3) and list-ceiling (X3) suites.
- All frontend JavaScript modules pass `node --check`; Python compilation is clean.
- 79 router operations across 11 routers, including work-order
  start/complete/hold/resume, both User Requests routes, the six NetFacilities
  routes, and the `/ws` WebSocket; Alembic head is `0c1d2e3f4a5b`.
- CI is the deploy path: a green run on `main` deploys to Render. A red build
  skips the deploy — observed 2026-08-10 on run `31425413107`.
- `git diff --check` passes; Git reports only expected LF-to-CRLF working-copy
  conversion warnings for modified files.

## Active follow-ups

- IMP-004 remains open and intentionally low priority.
- Hardware/iPhone scanner behavior still requires real-device validation when
  those paths change; there is no frontend test harness.
- Per the project owner's direction, Codex does not run interactive browser
  automation. Served-resource and automated contract checks remain in scope;
  the project owner performs in-browser click-through testing manually.
