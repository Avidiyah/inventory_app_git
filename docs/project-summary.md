# Project Summary

## What it is

A **self-hosted inventory + work-order staging system** for physical materials tracked by barcode — built for a field crew scanning items on a phone, plus supervisors/admins doing office-side review and billing.

**Stack:** a single FastAPI process serving both the JSON API and a no-build static SPA (`backend/static`, plain ES modules — no bundler). PostgreSQL via SQLAlchemy + Alembic. Barcode *uploads* decode server-side (`pyzbar`/zbar); *live camera* scanning uses vendored `@zxing/browser`. Deploys as one Docker web service + one managed Postgres on Render (port 8124).

**Architecture** is a strict layer chain: `routers → schemas/services → domain/models → database`. Routers stay thin (parse, auth, delegate); services own DB queries/locks/commits; domain modules are pure rules (no FastAPI/SQLAlchemy). Backend role gates are authoritative — frontend role hiding is UX-only.

## Core domains

- **Items & transactions** — find/create/edit items by barcode; Find Item initially loads only a name/barcode suggestion index, then explicit Search or Load All retrieves full records. Stock, dispense, correct (append-only `adjust` rows), and void (soft delete, reverses stock). Prices/links are cost-sensitive and redacted below Admin. Row locks guard every quantity change; money is `Decimal`.
- **Work orders** — first-class standalone, import-only entities whose case-insensitive identity is the **number**. Live workflow is Created → Assigned → In-Progress → Completed → Review, with supervisor-controlled On-Hold; Closed is the archived state. Work orders support multiple technician assignments, free-form Notes, aggregate material billing, and per-technician labor billed at $62.50/hour after the combined duration rounds upward to 30 minutes. Edit permissions are least-privilege: Technician = notes/add material; Supervisor+ = routing/status/mode/labor/material corrections; Admin+ = imported metadata and archive from any live status. Supervisors see the shared unassigned pickup queue plus work routed to themselves. Pickup and import merges lock the same row; a stale pickup receives a named 409, while import fills supervisor routing only when the locked row is still unassigned, preserving manual reroutes. Routing targets must be active Supervisors. Archived import matches are counted as closed and ignored. The server-side list composes status, service type, routed supervisor, derived community, exact scheduled date, and number filters with AND, then sorts by parsed Scheduled Date descending. Admin+ can export that uncapped filtered set as a re-importable operational CSV; the client billing/receipt CSV remains scope-based. Everything is server-scoped by role (technician→any assignment, supervisor→unassigned/self-routed, admin/owner→all).
- **Mass staging** — truck-loading plans per community/building/unit that *reference* work orders; forward-only lifecycle planning→loading→completed.
- **Tools** — parallel to items but smaller (no price/location); ledger-derived custody ("who has what" is computed, never stored). Checkout is Admin+, check-in any role.
- **Users/roles** — `owner > admin > supervisor > technician`; unique usernames
  stay login/account identifiers, while first + last names drive operational
  display and CSV supervisor routing. Legacy NULL names are explicitly editable
  on Users, login usernames can be corrected in the same flow, and Admin+ may
  change only strictly subordinate roles. Role changes revoke active sessions.
  Scrypt sessions use an HttpOnly cookie; archive is soft-delete with a
  tool-custody guard and an explicit force-check-in retry.

## Documentation map

- **`docs/current-state.md`** — the durable contract/invariants reference (data model, hard invariants, API surface, roles). "If it conflicts with code, trust the code."
- **`docs/endpoint-map.md`** — traces all 66 endpoints DB↔view (router→service→table, api.js→view), plus full request/response contracts, an error catalog, and service algorithms — meant to make reading source unnecessary.
- **`docs/improvement-tracker.md`** — requested improvements and their current status.
- **`docs/ux-review.md` + `docs/handoff.md`** — historical records of the July UX-improvement effort; not current-state authorities.

## Current baseline

Last reconciled: 2026-08-04 against the current worktree based on committed
baseline `0566a64`. The large
work-order/QoL batch and its follow-up user-management and export work are
committed; older documents that call that feature set uncommitted are historical.
OpenAPI exposes 66 operations and Alembic head is `f7a9b1c3d5e6`.

IMP-001 through IMP-003 and IMP-005 through IMP-018 are implemented and marked
Done. IMP-004 (the Mass Stage redesign) is the only open requested improvement
and remains very low priority. See `docs/improvement-tracker.md` for the original
requests and implementation notes.

Capabilities added after the improvement batch include:

- User administration can replace first/last/login names; Admin+ can change a
  strictly subordinate user's role and revoke that user's sessions; user archive
  can force-check-in outstanding tools before disabling the account.
- Admin+ work-order export supports `variant=full`, whose import headers make the
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
- Expanded Work Order controls follow the backend role matrix. Admin/Owner Edit
  Details includes imported metadata plus operations; Supervisor sees only
  supervisor, technicians, and status plus separate mode/labor/material-correction
  controls; Technician sees Notes and Add Item only. Admin/Owner additionally
  receives a confirmed Archive action on every expanded live-status card.
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

- Full backend suite on 2026-08-04: 436 passed, including the Excel `sep=,`
  and closed-row/import-routing regressions, joined Work Orders/date filtering,
  scheduled ordering, filtered operational export, stale-pickup conflicts, and
  the Work Orders field/action/archive role matrix.
- All 32 frontend JavaScript files pass `node --check`.
- OpenAPI reports 66 operations, including GET+POST on
  `/work-orders/legacy/archive`; Alembic reports `f7a9b1c3d5e6 (head)`.
- `git diff --check` passes; Git reports only expected LF-to-CRLF working-copy
  conversion warnings for modified files.

## Active follow-ups

- IMP-004 remains open and intentionally low priority.
- Hardware/iPhone scanner behavior still requires real-device validation when
  those paths change; there is no frontend test harness.
