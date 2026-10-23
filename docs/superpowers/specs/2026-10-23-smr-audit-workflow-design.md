# SMR27 audit workflow — design

Date: 2026-10-23. Status: approved in conversation; plan next.

## Intent

Roughly $700,000 of labor and material went unbilled on the Summer Make Ready
2026 project (service type `SMR27 - Belfor`, 688 NetFacilities work orders).
The vendor sheet `SMR27 Work Orders.csv` is the current state. The app
already holds the editor, labor/material lines, totals, receipt text, CSV
import, NetFacilities enrichment and xlsx export. This workflow strings
those together so Admins can re-charge every SMR order and Owners can hand
analytics a before/after record of exactly what changed.

**Not a new feature set.** One new page, one new import route, one new
export route, two new columns, one nullable FK. Everything else is reuse.

## Goals / non-goals / anti-goals

| Goals | Non-goals | Anti-goals (failure even if it works) |
|---|---|---|
| Import the sheet so every Closed row is an editable, unarchived work order | Any change to the normal import or the live Work Orders page | SMR rows leaking into the live list, Hub counts or the weekly closed report |
| Admin+ edit each order with the normal editor | Importing the sheet's hand-typed annotation columns as app lines | Losing the pre-audit state (baseline must survive re-imports) |
| Know which orders have been touched since import | A diff screen or SMR-specific editor | A guard dialog on every edit (see feedback: undo over guardrails) |
| Export before / after / delta, summary and line level, for analytics | Charts | Export that disagrees with the editor's own totals |

## The sheet (input contract)

| Fact | Value |
|---|---|
| Columns | WORK ORDER, CREATOR, SERVICE TYPE, SCHEDULE DATE, COMPLETION DATE, ASSIGNED TO, FILED STATUS, LOCATION, two free-text annotation columns |
| Rows | 688, unique numbers; 681 Closed, 7 Canceled |
| LOCATION | composite `Building:Floor,Room,Detail`; the task text is the third segment |
| Missing vs `IMPORT_HEADERS` | OUTPUT TO, SYMPTOM/TASK |

The sheet is **not** the normal mass export: it lacks the task column and
carries five columns the app has no field for.

## Decisions (as made)

| # | Decision | Owner |
|---|---|---|
| 1 | SMR orders live only in their own **SMR view**, white on black, brutalist. They never appear in the live Work Orders list, filter options, Hub tabs, Graphs, or the weekly closed report. | user |
| 2 | **SMR Import** button sits in the NetFacilities card on Integrations, styled like the buttons already there. **Owner only.** | user |
| 3 | Import sets every Closed row to **closed-but-unarchived**: existing archived rows are restored, active rows stay active, missing numbers are created. All gain the SMR marker. Canceled rows are skipped. | user |
| 4 | Admin+ open an SMR order in the **normal editor** and add labor and materials as usual. | user |
| 5 | Finishing an order = archiving it manually from the SMR view (existing archive action). Archived SMR orders remain in the SMR view and the export. | user |
| 6 | Export is comprehensive: one summary row per order with before / after / delta for every number, plus line-level rows tagged BEFORE or AFTER. **Owner only.** | user |
| 7 | SMR view is **Admin+**. | user |
| 8 | Tile layout (mockup B): one box per order, big number, big delta, untouched tiles dim; filters All / Edited / Untouched / Archived; click opens the editor. | user |
| 9 | Baseline = frozen snapshot taken the first time SMR Import touches an order; a re-import never overwrites it. | Claude, approved |
| 10 | "Edited since import" is derived, not stored: the order's current snapshot differs from its baseline. | Claude, approved |

## Data

Two nullable columns on `work_orders` (one Alembic migration, no backfill):

| Column | Type | Meaning |
|---|---|---|
| `smr_imported_at` | timestamptz | the SMR marker; set on first SMR import, never cleared |
| `smr_baseline` | JSONB | the pre-audit snapshot (below) plus the raw sheet row |

Snapshot shape, produced by one pure function in `domain/work_orders.py`
that the baseline, the edited check and the export all share:

```
{ "taken_at", "source_row": {<every sheet column verbatim>},
  "totals": {materials_total, labor_minutes, billed_labor_minutes, labor_total, total},
  "status", "archived_at", "notes",
  "material_lines": [{item_id, item_name, barcode, quantity, billable_quantity, unit_price, created_at}],
  "labor_entries":  [{technician, minutes, created_at}],
  "labor_sessions": [{technician, started_at, ended_at, minutes, capped, edited_at, edited_by}] }
```

Storing `source_row` verbatim is how "every bit of raw data" (CREATOR,
COMPLETION DATE, FILED STATUS, the annotation columns) reaches analytics
without five new columns. Claude's call.

Why JSONB, not a table: one write per order, read only by the export and the
edited check, never queried by field.

## Import (`POST /work-orders/smr/import`, Owner)

Reuses the existing upload reading, UTF-8 and header preflight, and
`get_or_create_work_order`. Differences from the normal import, and nothing
else:

- Accepts the sheet's headers. LOCATION, ASSIGNED TO, SERVICE TYPE,
  SCHEDULE DATE map as today; task uses the NetFacilities fallback URL so
  enrichment can fill it (same as a blank task today).
- `FILED STATUS != Closed` → skipped, counted.
- Existing archived row → `archived_at = NULL` (restore), counted as
  `restored`. Existing live row → fill-blanks as today, counted `opened`.
- Every touched row: set `smr_imported_at` if null; set `smr_baseline`
  if null, from the row **after** restore and fill-blanks.
- Summary: `total, created, opened, restored, skipped, baselined`.

Enrichment: the candidate query already selects unarchived rows with a
fallback task, so SMR rows enrich with the normal "Import Tasks and
Priority" button. The builder confirms that the live-list exclusion (next
section) is **not** applied to the enrichment candidate query.

## Exclusion from the live surfaces

Every query that today means "live" by `archived_at IS NULL` and feeds a
user-facing list or count must also require `smr_imported_at IS NULL`. Known
sites: `list_work_orders`, `get_work_order_filter_options`, Hub tabs and
Graphs, the weekly closed report's live and frozen selection,
`count_live_legacy_work_orders` / `archive_live_legacy_work_orders`, realtime
list refresh, work-order search by number from the Hub. The editor's own
`get_work_order` / update / labor / material routes must **not** exclude SMR
rows. The builder audits with the graph (`archived_at.is_(None)` call sites)
and adds a single reusable predicate rather than copying the clause.

## SMR view (`static/pages/smr.html`, `static/views/smr.js`)

| Element | Content |
|---|---|
| Top bar | `SMR27 — BELFOR` · order count · edited count · untouched count · Δ labor $ · Δ material $ · Δ total $ · imported-at |
| Filters | ALL / EDITED / UNTOUCHED / ARCHIVED toggle buttons; EXPORT XLSX (Owner only, hidden otherwise) |
| Tile | number (large) · building + unit · assignee · Δ total $ (large) · after-minutes · after-line-count · EDITED / UNTOUCHED / ARCHIVED |
| Tile click | opens the normal editor for that order; back returns to the tiles with the filter kept |
| Empty | `NO SMR ORDERS. OWNER: IMPORT FROM INTEGRATIONS.` |

Style: `#000` background, `#fff` text and 1px rules, monospace, uppercase
labels, no radius, no shadow, no accent color; untouched tiles at 50 %
opacity. Delivered as a class ladder in `styles.css` (CSP drops inline
styles). It is a deliberate departure from `docs/design-system.md`; note it
there in one line. Nav entry `smr`, Admin+, same `PAGE_ACCESS` mechanism.

API: `GET /work-orders/smr` (Admin+) returns tiles with before / after /
delta totals and the edited flag, computed server-side from the baseline and
`work_order_totals`. One endpoint, no pagination (688 rows).

## Skilled Technician labor (SMR orders only)

The vendor sheet bills "SL hours" (skilled labor) that no app user performed.
Decisions (user):

| Decision | Value |
|---|---|
| Scope | Only when the open order carries `smr_imported_at` |
| Identity | Anonymous pool line: each click adds one more "Skilled Technician" labor line with hours; no name, nothing persists beyond the order; any number per order |
| Billing | Same labor rate; its minutes round up to the 30-minute increment **on their own**, apart from the real technicians' pooled minutes |
| Visibility | Work order editor and SMR export only; never in Hub, leaderboards, attendance, timesheets or the weekly closed report |

Data: `work_order_labor.technician_id` becomes nullable; a null technician
**is** a Skilled Technician line (no extra column). Assignment rules do not
apply to it. Claude's call; a label column would only ever hold one value.

Totals: `work_order_totals` becomes
`labor_charge(real minutes) + labor_charge(skilled minutes)`; the detail
response reports the two minute counts separately so the editor's summary
line and the export agree. The export's labor columns split into REAL and
SKILLED minutes plus the pooled total; `labor_entries` rows in the snapshot
carry `technician: "Skilled Technician"`.

Editor: a button `Add Skilled Technician` rendered **above** the existing
Technician dropdown / Actual hours / Add labor row, only on SMR orders, with
its own hours input. Entries list as `Skilled Technician · 0.50 h` with the
existing Update / Remove controls. Routes: the existing labor add / update /
delete endpoints accept a null `technician_id` only when the order is SMR and
the caller is Admin+; otherwise 422 as today.

Per-person consumers (Hub, leaderboards, report, profile timeline) join on
`users` and therefore drop null rows; the builder audits any labor sum that
does **not** join users and excludes null technicians there.

## Export (`GET /work-orders/smr/export.xlsx`, Owner)

Built with the existing openpyxl theme (`_xlsx_theme.py`). Sheets:

| Sheet | One row per | Columns |
|---|---|---|
| Orders | SMR order | every sheet column verbatim · every `EXPORT_HEADERS` column · for each numeric column: BEFORE, AFTER, DELTA · EDITED · SMR IMPORTED AT · BASELINE AT · LAST EDITED AT · LAST EDITED BY · ARCHIVED AT |
| Material Lines | material line, before and after | WORK ORDER · PHASE (BEFORE/AFTER) · item name · barcode · quantity · billable quantity · unit price · line total · created at |
| Labor Entries | labor entry, before and after | WORK ORDER · PHASE · technician (or `Skilled Technician`) · minutes · created at |
| Labor Sessions | session, before and after | WORK ORDER · PHASE · technician · start · end · minutes · capped · edited at · edited by |

BEFORE rows come from `smr_baseline`; AFTER rows from the live order through
the same serializer, so the two phases are column-identical. All SMR orders
are included regardless of archive state or filter. Money as numbers, not
strings (analytics will sum them).

## Constraints

- No new dependencies. No new tables.
- Files stay under 500 lines; `smr.js` delegates to `workOrderCardHtml` /
  presenters where a helper already exists.
- Targeted tests only before push (feedback memory). Required: import
  restore-and-baseline idempotence, Canceled skip, live-list exclusion,
  edited derivation, export phase parity, Owner gates on import and export,
  Admin gate on the view.
- Deploy is production (CI gate memory): ask before pushing main.

## Builder-check calls (Claude's, overridable)

- SMR Import is a **file upload** (same picker as "Import from CSV…"), not
  a Steel cloud capture: the sheet is a spreadsheet copy, not a
  NetFacilities download.
- Archiving an SMR order happens through the editor's existing archive
  action; tiles carry no archive button.
- `LAST EDITED BY` = the actor on the most recent labor session edit or
  note-log entry after the baseline; blank when none. No new column.
- Restore does not touch `status`; an order keeps the status it was archived
  with, and the editor already accepts any live status.

## Left to the builder

- Exact snapshot field list beyond the shape above; keep it a superset of
  what the export prints.
- Whether the SMR tile list reuses `workOrderCardHtml` or renders its own
  minimal tile (likely its own; the card is the wrong shape).
- Column order on the Orders sheet.
- Alembic revision naming and the one-line design-system note.
