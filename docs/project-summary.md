# Project Summary

## What it is

A **self-hosted inventory + work-order staging system** for physical materials tracked by barcode — built for a field crew scanning items on a phone, plus supervisors/admins doing office-side review and billing.

**Stack:** a single FastAPI process serving both the JSON API and a no-build static SPA (`backend/static`, plain ES modules — no bundler). PostgreSQL via SQLAlchemy + Alembic. Barcode *uploads* decode server-side (`pyzbar`/zbar); *live camera* scanning uses vendored `@zxing/browser`. Deploys as one Docker web service + one managed Postgres on Render (port 8124).

**Architecture** is a strict layer chain: `routers → schemas/services → domain/models → database`. Routers stay thin (parse, auth, delegate); services own DB queries/locks/commits; domain modules are pure rules (no FastAPI/SQLAlchemy). Backend role gates are authoritative — frontend role hiding is UX-only.

## Core domains

- **Items & transactions** — find/create/edit items by barcode; Find Item initially loads only a name/barcode suggestion index, then explicit Search or Load All retrieves full records. Stock, dispense, correct (append-only `adjust` rows), and void (soft delete, reverses stock). Prices/links are cost-sensitive and redacted below Admin. Row locks guard every quantity change; money is `Decimal`.
- **Work orders** — first-class standalone, import-only entities whose case-insensitive identity is the **number**. Live workflow is Created → Assigned → In-Progress → Completed → Review, with supervisor-controlled On-Hold; Closed is the archived state. Work orders support multiple technician assignments, free-form Notes, aggregate material billing, and per-technician labor billed at $62.50/hour after the combined duration rounds upward to 30 minutes. The source of truth is a **CSV import** (`POST /work-orders/import`, Admin+, idempotent fill-blanks); pre-import rows are marked `legacy`. Everything is server-scoped by role (technician→any assignment, supervisor→created/routed, admin/owner→all).
- **Mass staging** — truck-loading plans per community/building/unit that *reference* work orders; forward-only lifecycle planning→loading→completed.
- **Tools** — parallel to items but smaller (no price/location); ledger-derived custody ("who has what" is computed, never stored). Checkout is Admin+, check-in any role.
- **Users/roles** — `owner > admin > supervisor > technician`; unique usernames
  stay login/account identifiers, while first + last names drive operational
  display and CSV supervisor routing. Legacy NULL names are explicitly editable
  on Users. Scrypt sessions use an HttpOnly cookie; archive is soft-delete with a
  tool-custody guard.

## Documentation map

- **`docs/current-state.md`** — the durable contract/invariants reference (data model, hard invariants, API surface, roles). "If it conflicts with code, trust the code."
- **`docs/endpoint-map.md`** — traces all 61 endpoints DB↔view (router→service→table, api.js→view), plus full request/response contracts, an error catalog, and service algorithms — meant to make reading source unnecessary.
- **`docs/ux-review.md` + `docs/handoff.md`** — track a UX-improvement effort.

## Current state of work

The working tree contains active uncommitted feature work. IMP-001 is implemented:
Find Item starts without item cards, loads only lightweight name/barcode
suggestions, searches the full live dataset only on Search/Enter, and exposes an
explicit Load All Items action.

IMP-002 is now implemented on top of the active uncommitted work-order import
feature: migration `f3b5d7a9c1e2` adds nullable first/last names without guessing
legacy identity; Add User requires both; Users can explicitly repair legacy
names; CSV routing matches an unambiguous active-supervisor full name and leaves
misses/duplicates unassigned; operational UI surfaces render full names while
username remains limited to login/account-management views.

IMP-003 is implemented on Scan / Stock: Supervisor+ gets a compact
work-order-number search card above the scoped cards; typing live-filters the
cards through the existing API. Selecting In-Progress starts the batch, while
IMP-011 now redirects earlier states to their Work Order card. The
manual item picker is hidden until a work order is selected.

IMP-005 is implemented with the corrected lifecycle: imports start Created;
technician assignment derives Assigned; and first committed material or labor
derives In-Progress. Selecting a
Scan/Stock card is status-neutral. A technician or supervisor can Mark completed,
while only Supervisor+ sees Send to Review and must confirm readiness in a
pop-up before it enters final Admin Review. Closed uses the existing archive state, is Admin+ and Review-only, and
has no action on ordinary Work Orders. Cards use the requested
gray/red/yellow/blue/green status backgrounds with contrasting text. That
lifecycle correction concluded at migration `f5d7f9b1c3e4`.

IMP-009 and IMP-010 are implemented. Supervisor+ Edit details now exposes a
non-Review status selector that can roll Completed and earlier states backward
or place work On-Hold; pre-work rollback remains derived from technician
assignment, and activity does not resume a held order. Every expanded Work Order
card has a free-form Notes section that any in-scope user may save or clear.
On-Hold cards are orange. Migration `f6e8a0b2d4f5` added the nullable
`work_orders.notes` column.

IMP-006 is implemented. Supervisor+ Edit details uses a multi-technician
assignment set; every assigned technician receives normal server-scoped access.
Expanded cards track actual labor as per-technician minute entries beneath item
selection. Billing sums all entries, rounds upward once to the next 30 minutes,
and applies $62.50/hour; rate and charge remain Admin/Owner-only. Technicians can
manage only their own labor, while Supervisor+ can manage any assigned
technician. Migration `f7a9b1c3d5e6` backfills existing singular assignments and
adds the labor table while retaining `assigned_to_id` as a compatibility mirror.

IMP-007 is implemented as an Admin/Owner-only Admin Review page. It lists every
live Review work order as a green number-titled card. Selecting one builds a
persistent 41-character receipt from authoritative override-aware material
lines, the `+15%` material mark-up, an always-present `[x] Labor Hours` line
using billed hours and the unmarked-up labor charge, and the combined Total.
The copied text intentionally has no work-order-number header. The shared pure
formatter keeps Admin Review and History aligned; missing prices render
`NO PRICE` and block Close. Confirmed Return to In-Progress and Review-only
Close both remove the card from the queue while leaving the receipt visible.

IMP-011 is implemented: Created/Assigned Work Order cards expose Set In-Progress
to in-scope technicians and supervisors. Scan/Stock only starts a batch from an
In-Progress card; selecting an earlier state opens a confirmation and can take
the user directly to the expanded Work Order to set it In-Progress. Cancel keeps
the user at the scan gate. On-Hold remains Supervisor-controlled and excluded
from Scan/Stock.

IMP-008 is implemented with explicit page-entry refresh semantics. Navbar
navigation remains an in-memory SPA switch, while every entry to Work Orders,
Find Item, or Mass Stage requests current server data. Work Orders and Mass Stage
also replace their cached item/user reference lists on page entry; Find Item
refreshes its lightweight search index and keeps full rows behind Search or Load
All.

Latest IMP-007 verification: all 32 frontend JavaScript files pass syntax checks;
pure receipt assertions cover the no-header contract, 41-character maximum,
long-name truncation, `[0]`/`[1.5]` labor, combined totals, and missing prices;
53 focused backend billing/role tests pass; Python compilation, served SPA/DOM
and changed-resource checks, and `git diff --check` pass. The full backend run
reported 322 passed and one unrelated baseline-sensitive failure because the
configured test database already contained one persisted `work_order_items` row
before that test transaction. Interactive browser QA was unavailable because no
browser backend was attached.
