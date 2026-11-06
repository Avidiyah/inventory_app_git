# SMR27 paper corrections import — design

Date: 2026-11-04. Status: builder-checked, awaiting the user's approval of the document. Extends the three app specs
`2026-10-23-smr-audit-workflow-design.md`, `2026-10-23-smr-target-match-design.md`
and `2026-10-27-smr-paper-check-design.md` in `inventory_app_git/docs/superpowers/specs/`.
Written in the reconciliation folder because the app is not edited from here; copy it
beside the other three when the build starts.

## Intent

The SMR27 paper review is finished for Weeks 1–7. Its result lives in
`paper_review.csv` (566 verdict rows over 517 orders, prose notes) and in Python dicts
spread over six reconciliation scripts. The TechFM app, which is the system that will
answer a Langston audit, holds 175.5 h of labor against 4,455.5 h billed, knows no
vendor, no vendor worker, no work date and no reason, and still shows all 681 SMR orders
as Untouched.

This design moves the reviewed record into the app once, in a normalized shape, with
every line answerable as **"on this day, this person (or this many unnamed people) of this
vendor worked these hours on this order, for this reason, on this piece of paper"**, with
an append-only history of every change from the import onward, and with a generated
correction block per order that is pasted into the NetFacilities follow-up field the way
receipts are today. After the import the app is the only place SMR corrections are edited;
`paper_review.csv` retires as a historical source (user, 2026-11-04).

## How extreme the gap is (read 2026-11-04 from orders.xlsx, paper_review.csv, breakdown.xlsx)

| App today | |
|---|---|
| SMR orders | 681, all Untouched, none Matched, none paper-checked |
| Labor in the app | 175.5 h, 90 entries, 12 Belfor technicians |
| Billed to Langston (Breakdown) | 4,455.5 h on 690 orders |
| Vendor field hours invoiced | 10,218.5 h |

| Reviewed record | |
|---|---|
| Verdict rows / orders | 566 / 517; 35 orders have 2–5 printings |
| Dated / undated rows | 331 / 235 |
| Justified hours recorded | 5,949 |
| Rows with unnamed or vendor-unknown lines | 466 |
| Orders up / down / unchanged vs Breakdown | 247 (+2,323.5 h) / 85 (−353 h) / 176 |
| Reviewed orders not in the app export | 8 (22648770, 23200861, 23271156, 23297400, 23341924, 23344906, 23344914, 23405507) |
| Breakdown orders never reviewed | 175 (not found, or closed after 07/12) |
| Hours charged in a week / reported not charged | 2,938 / 7,790.5 |

## What the auditor sees (user, 2026-11-04)

Paper work order in hand, NetFacilities open on the same order. In a follow-up field sits a
text block TechFM generated and someone pasted: the original NetFacilities charge, each change
as its own line with its reason beside it, the corrected total. Every charged line ties to a
name and a day on the paper.

## Goals / non-goals / anti-goals

| Goals | Non-goals | Anti-goals (failure even if it works) |
|---|---|---|
| Every verdict row and every labor line in the app, including excluded and note-only ones | Material corrections (the paper gave none; material exposure stays a report) | Any verdict, name, note or hour that exists in `paper_review.csv` and not in the app |
| Vendor workers tracked by name and date without creating app users (user) | Pushing to NetFacilities by API; the block is pasted by hand like receipts | A charged hour with no work date, no vendor, or no reason |
| Append-only history of every line from import onward | Re-checking weekly invoice caps in the app (enforced in the review; the app stores the outcome) | Pooled 30-minute rounding changing a per-person 0.5 h allocation |
| SMR charge = sum of charged lines at $62.50 | Touching the live Work Orders surfaces, Hub, attendance, leaderboards | Legacy app labor and correction lines both counting on one order |
| A generated, versioned correction block per order | Migrating the 175.5 h of legacy labor entries into lines | Decreases left out of the block |
| Export carries lines, readings, history and blocks | | |

## Decisions (as made)

| # | Decision | Owner |
|---|---|---|
| 1 | Source is the reviewed record, normalized in the reconciliation folder and checked by John; no re-keying from paper. | user (import discussion) |
| 2 | After the bulk load the app is the only place SMR corrections are edited; `paper_review.csv` retires. | user 2026-11-04 |
| 3 | Dated working hours are tracked per vendor worker without creating app users. | user 2026-11-04 |
| 4 | The correction reaches NetFacilities as a generated text block pasted into a follow-up field, like receipts. | user 2026-11-04 |
| 5 | Each change is a line (person or unnamed headcount, vendor, date, hours, kind, reason); overhead lines are lines. | Claude, accepted in conversation |
| 6 | The original charge is the Breakdown target already in the app (`smr_target`); the baseline stays frozen. | Claude |
| 7 | Decreases are lines too, printed with a sign. | Claude |
| 8 | Caps and banks are not re-checked by the app. | Claude, accepted |
| 9 | Charge on an SMR order with any correction line = charged lines × $62.50, no pooled rounding; legacy labor entries on that order are shown under the label **"NetFacilities Record Before Correction"** and not charged. | user 2026-11-04 |
| 10 | Undated, before-Week-1, after-07/12, awaiting-invoice and vendor-unknown lines are stored with status `excluded` and a ground; dating or resolving one in the app flips it to `charged` at once, with a history row and no second approval. | user 2026-11-04 |
| 11 | Reviewed orders missing from the app (8 numbers) are **created by the import from their Breakdown row**, marked created-by-import, so no verdict is lost. Cimarron J6 still needs an order number from the user. | user 2026-11-04 |
| 12 | After import: Admin+ add, edit, exclude lines and generate / mark-pasted blocks; Owner only runs the import and merges workers. | user 2026-11-04 |
| 13 | **Week 1 placement is a date basis of its own.** The 26 Week 1 orders placed by crew-sheet evidence (78 lines, 187.5 h) are charged with week 1 and a blank day; the correction block prints "week of 05/25"; the crew sheets are the evidence. The "charged requires a date" check allows this basis. | user 2026-11-05 |
| 14 | **Material is unchanged.** New material = billed material; the correction is labor-only. The app's +15% material figure ($98,672 against $149,961 billed, 228 orders with none logged) is shown beside it as information and never feeds the total. | user 2026-11-05 |

## Step 0 — normalize in the reconciliation folder (before the app changes)

A new script `paper_lines.py` (flat Python, openpyxl/csv, like the others) reads
`paper_review.csv` and the dicts that already hold structure (`week_supplement.P`,
`belfor_hours.OVERRIDE`, `week2_report.FIX`/`NAMED`, `weekly_summary.NOT_IN_WEEK`,
`week_supplement.UNKNOWN`/`ALIAS`, `.claude/references/people.md`) and writes two CSVs:

| File | One row per | Columns |
|---|---|---|
| `paper_readings.csv` | verdict row (printing) | `reading_id, wo, printing_no, work_date, hours_as_read, raw_note (verbatim), reviewer, csv_row` |
| `paper_lines.csv` | labor line | `line_id, reading_id, wo, work_date, vendor, worker (canonical name or blank), alias_on_paper, headcount, hours_each, kind, reason_code, status, exclusion_ground, note` |

Rules of the parse:

- Every verdict row produces a reading, even note-only ones (0 lines). Nothing is dropped.
- A line's `status` is `charged` unless its ground applies: `undated` (blank work_date), `before_week1`
  (work_date < 05/25), `after_0712`, `awaiting_invoice` (the "GC HOURS NOT CHARGED" lines), `vendor_unknown`
  (Michael, Gabriel, David), `reprint` (a second printing judged a re-print under the ±0.5 h rule: lines kept,
  0 h charged), `note_only`.
- Per reading the script asserts `sum(headcount × hours_each over non-excluded lines) == hours_as_read`
  (hours_as_read already includes overhead). Mismatches print as a list; John settles each one in the
  script's `FIX` dict with the reason, exactly as `belfor_hours.py` does today.
- Worker names resolve through `people.md` aliases to one canonical spelling per person; `alias_on_paper`
  keeps what the paper said. Vendors are `Belfor`, `Green Choice`, `XXL Construction`, `BT Restoration`,
  `Unknown`.
- `kind` is `field`, `assessment`, `audit`, `staging` (dictation defaults: assessment = Belfor, audit and
  staging = XXL, 0.5 h, unless the note says otherwise).
- `reason_code` from the seed list below; `note` keeps the sentence of the verdict the line came from.

John checks `paper_lines.csv` in Excel against the notes, order by order, before the import. The
printed check line is `readings 566, lines N, charged h X, excluded h Y, ties 566/566`.

Seed reason codes (builder may add, never remove):

| Code | Meaning (from the verdict notes) |
|---|---|
| `crew_as_one` | a crew was captured as one individual |
| `crew_as_individuals` | crew members' hours were each added, over-counting |
| `arithmetic` | the paper's own total was wrong; lines taken as read |
| `overhead_added` | assessment / audit / staging not on the original, label only |
| `overhead_twice` | keyed two or three times, counted once ("a.t.") |
| `accurate` | billed accurately; lines record who and when |
| `over_billed` | paper supports less than billed |
| `not_on_paper` | paper names no one or no hours |
| `unit_mismatch` | the app, Breakdown and paper disagree on the unit |
| `date_found` | a date later found on previously undated paper |

## Data (app; one Alembic migration, no backfill of existing columns)

Four new tables. Plain columns, not JSONB: these rows are queried by field (by worker, by date,
by status) and edited line by line.

### `smr_workers` — people who worked, without being app users (D3)

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `display_name` | text, unique with vendor | canonical spelling from `people.md` |
| `vendor` | text | `Belfor` / `Green Choice` / `XXL Construction` / `BT Restoration` / `Unknown` |
| `user_id` | FK users, nullable, `ON DELETE SET NULL` | Belfor employees who are app users link here; nobody is created as a user |
| `aliases` | JSONB array of text | "Rye", "Trint", "Ottoman", "Ender" (Week 1) |
| `is_admin` | bool | McClure, Nesbitt, Clift, Garner: never on a line |
| `created_at`, `archived_at` | timestamptz | |

Seeded by the import from `paper_lines.csv`; Admin+ may add a worker or an alias later (history row).

### `smr_paper_readings` — one per printing read

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `work_order_id` | FK work_orders, `ON DELETE CASCADE` | |
| `printing_no` | int | 1..5 per order |
| `work_date` | date, nullable | as read |
| `hours_as_read` | numeric(6,1), nullable | the verdict's `hours` |
| `raw_note` | text | the verdict note verbatim: the prose record is never lost |
| `reviewer` | text | `JM` |
| `source` | text | `paper_review.csv row 212, import <sha256 prefix>` |
| `created_at`, `created_by_id` | | the import run / Owner |

### `smr_labor_lines` — the unit of charge

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `work_order_id` | FK work_orders, `ON DELETE CASCADE` | |
| `reading_id` | FK smr_paper_readings, nullable | null only for a line added in the app with no paper |
| `work_date` | date, nullable | null ⇒ status cannot be `charged` (DB check) |
| `vendor` | text | same set as workers |
| `worker_id` | FK smr_workers, nullable | null ⇒ unnamed |
| `alias_on_paper` | text, nullable | |
| `headcount` | int ≥ 1 | "2 BT x 3 h" is headcount 2, hours_each 3 |
| `hours_each` | numeric(6,1) | multiple of 0.5 (DB check), may be negative for an explicit credit line |
| `kind` | text | `field` / `assessment` / `audit` / `staging` |
| `reason_code` | text | seed list |
| `status` | text | `charged` / `excluded` |
| `exclusion_ground` | text, nullable | required when `excluded` (DB check) |
| `note` | text, nullable | |
| `created_at`, `created_by_id`, `updated_at`, `updated_by_id` | | |

Indexes: `(work_order_id)`, `(worker_id, work_date)`, `(work_date)`.

### `smr_line_edits` — append-only history, the `attendance_punch_edits` shape

| Column | Notes |
|---|---|
| `id`, `line_id` FK `ON DELETE CASCADE`, `edited_by_id` FK users not null, `edited_at` | |
| `field`, `old_value`, `new_value` (text) | one row per field changed; `field = "created"` / `"deleted"` for whole-line events, with the line serialized as JSON in `new_value` / `old_value` |
| `reason` | required text on every edit made in the app; the import writes the run identifier |

Deleting a line in the app is a soft event: the line row stays with `status = excluded`,
ground `removed`, and a `deleted` history row. Nothing is ever hard-deleted except by cascade from
a work order, which SMR orders never undergo.

### `smr_correction_blocks` — what was pasted

| Column | Notes |
|---|---|
| `id`, `work_order_id` FK, `version` int (1, 2, …) | |
| `text` | the generated block, verbatim |
| `generated_at`, `generated_by_id` | |
| `pasted_at`, `pasted_by_id` | nullable; set by the "Mark pasted to NetFacilities" button |
| `lines_digest` | sha256 of the charged and excluded lines the block was built from, so a stale block is detectable |

Existing columns keep their meaning: `smr_baseline` (frozen pre-audit state), `smr_target` (Breakdown
original), `smr_paper_checked_at/by` (set by the import for every order with a reading; who = the
importing Owner, when = import time, unless already set).

## Import (`POST /work-orders/smr/import-paper`, Owner)

Same shape as `import_smr_targets`: two uploaded CSVs (`paper_readings.csv`, `paper_lines.csv`),
UTF-8 / `sep=,` / header preflight, every row parsed and cross-checked before any write, one commit.

Per order touched:

1. `find_by_number`; must carry `smr_imported_at`. A number with no order (D11) is created through
   `get_or_create_work_order` from its Breakdown row (unit, closed date, service type `SMR27 - Belfor`),
   given `smr_imported_at`, a baseline taken from the empty order, and `smr_target` from the same
   Breakdown row; the reading's `source` says `created by paper import`. A number in neither the app
   nor the Breakdown aborts the import and is named.
2. Create readings, then lines, then workers it has not seen (by `display_name + vendor`), then one
   `created` history row per line naming the run.
3. Set the paper-check mark if unset.
4. Re-run the same arithmetic check as `paper_lines.py` (lines tie to `hours_as_read` per reading);
   a mismatch aborts the whole import with the reading named.

Idempotence: a second upload of the same files is a no-op (readings keyed by `work_order_id +
printing_no`, lines by `line_id` carried in the CSV as a stable key); changed rows are rejected, not
merged. After the first successful run the import route is for recovery only; edits happen in the app.

Result: `orders, readings, lines, workers_created, charged_hours, excluded_hours, unknown_numbers`.

## Charging (D9)

`work_order_totals` gains one branch: if the order has any `smr_labor_lines`, labor is
`Σ headcount × hours_each over status = charged` hours × `LABOR_RATE`, no `billed_labor_minutes`
rounding (lines are already in 0.5 h steps). Legacy `work_order_labor` entries on such an order are
returned separately as `legacy_labor_minutes` and shown in the editor under the heading
"NetFacilities Record Before Correction" (user's label; the entries were keyed in TechFM in August
and mirror what NetFacilities carried), not charged. Orders with no lines bill exactly as today. `target_gap` compares the new
labor figure to the Breakdown as it does now, so Matched / Short keep their meaning.

`WorkOrderDetail` gains `smr_lines: [SmrLineOut]`, `smr_readings: [SmrReadingOut]`,
`smr_legacy_labor_minutes`, `smr_block: Optional[SmrBlockOut]` (latest version with `stale` flag).

## Editor (SMR orders only)

A **Paper corrections** section above the existing Labor section:

- Readings listed first, each with its date, hours as read and the raw note behind a disclosure.
  **Add reading** (printing number, date, hours as read, note typed from the paper) is how paper read
  after the import, such as the post-07/12 orders, enters the app; its lines are added under it.
- Lines in a table: date · vendor · worker (or `2 unnamed`) · kind · h each · status · reason · note,
  with Edit / Exclude. Add line requires date (or an exclusion ground), vendor, hours in 0.5 steps,
  kind, reason code, and a free-text reason for the history row.
- Worker picker searches `smr_workers` by name and alias; "Add worker" creates one (no user).
- A **Generate correction block** button writes a new version and shows it in a copy box like the
  receipt; **Mark pasted to NetFacilities** stamps it. The box shows `v3 · pasted 11/10/26 by JM` or
  `v4 · not yet pasted · lines changed since v3`.
- Totals line: `Billed (NetFacilities) 38.0 h · Corrected 120.0 h · Change +82.0 h · $5,125.00`.

The existing Skilled Technician and labor controls stay for orders without lines; on an order with
lines they are read-only under "NetFacilities Record Before Correction".

## The correction block (D4)

Generated by one pure function in `domain/work_orders_smr.py`, pinned by a test like
`test_receipt.py`, 41 characters wide (the destination wraps at 42). Shape (builder owns exact copy):

```
SMR27 LABOR CORRECTION v2   11/10/26
Billed in NetFacilities       38.0 h
Corrected                    120.0 h
Change                       +82.0 h
                           $5,125.00

06/20 BT Restoration x2   3.0 h each
  crew billed as one person
06/20 Belfor assessment        0.5 h
  overhead added, label only
06/22 Trinton Smith (XXL)      4.0 h
  crew billed as one person

Not charged:
  undated  Rye (Green Choice)  7.0 h
  awaiting invoice  GC x4     96.0 h

Reason text below each line. Paper on file.
```

The reason prints on the line under the charge (user wants it beside each charge; width forbids
one line). Decreases print the same way with a minus. Excluded lines print under "Not charged" with
their ground, because the auditor must see what was left out and why.

## SMR page

| Element | Change |
|---|---|
| Bar | adds `N WITH LINES` · `CHARGED 2,938.0 H` · `EXCLUDED 3,011.0 H` · `N BLOCKS NOT PASTED` |
| Filters | adds **Has lines**, **Block stale / not pasted** |
| Tile | third line becomes `+82.0 H · V2 PASTED` when lines exist |
| New tab **Hours** | hours by worker × week (Mon–Sun) and by vendor × week, charged and excluded, from `smr_labor_lines` only; this is the "dated working hours" view (D3). Read-only, Admin+; CSV download |

## Export (`export.xlsx`, Owner)

Orders sheet appends: `CORRECTED HOURS`, `CORRECTED LABOR $`, `CHANGE HOURS`, `CHANGE $`,
`EXCLUDED HOURS`, `LINES`, `READINGS`, `BLOCK VERSION`, `BLOCK PASTED AT`. New sheets:
`Paper Readings`, `Labor Lines` (every column, plus worker name and aliases), `Line History`,
`Correction Blocks` (text included), `Workers`. Money and hours as numbers.

## Workflow, import to audit (who does what)

| # | Stage | Human | App / script | Left behind |
|---|---|---|---|---|
| 0 | Normalize (this folder) | John checks `paper_lines.csv` against each verdict note in Excel; settles mismatches and unmapped names in `FIX`; reruns until every reading ties | `paper_lines.py` writes the two CSVs, prints `readings 566, lines N, charged h X, excluded h Y, ties 566/566`, lists mismatches and unmapped names | the two CSVs and their sha256; a Workflow doc entry with the printed line |
| 1 | Build and deploy | John approves the plan; asks before main | migration adds the four tables; no data changes | Alembic head; tests green |
| 2 | Import | Owner uploads the two CSVs from the NetFacilities card; reads the result counts against the Stage 0 line; stops on any difference | preflight, parse all, tie check, create the 8 missing orders from the Breakdown, workers, readings, lines, one `created` history row per line, paper-check mark; one commit or nothing | history rows naming the run; `source` on every reading; result summary logged |
| 3 | Verify the load | John exports and ties Labor Lines to the Status Report (2,938 h charged on 337 orders, per week); compares the Hours tab per vendor and week to the invoice banks once; spot-checks orders in the editor against the paper | SMR bar: with lines, charged h, excluded h; export sheets; Hours tab | the export file kept with the Final Draft sources |
| 4 | Work the remainder in the app | Admin+ opens an order, adds a reading or a line, dates an undated line, flips awaiting-invoice lines when the GC invoice arrives, adds Cimarron J6 once it has a number; a reason on every edit | DB checks refuse a charged line with no date or hours off the 0.5 step; every edit writes history; dating flips status to charged | `smr_line_edits` |
| 5 | Generate, paste, mark | Admin+ clicks Generate, copies the block, pastes it into the NetFacilities follow-up field, saves there, clicks Mark pasted; works the "Block stale / not pasted" filter to zero | renders v(n) from current lines, stores text and digest; flags stale when lines change after a paste; old versions kept | `smr_correction_blocks` |
| 6 | Finish the order | Admin archives from the SMR view when lines are in, block pasted | archived orders stay in the SMR view and export | archive stamp |
| 7 | Deliver | John sends the export (Orders, Labor Lines, Readings, Line History, Correction Blocks, Workers) beside the invoices and crew sheets already in the Final Draft | Owner export | the backing for every pasted block |
| 8 | Audit | the Langston auditor reads the block in NetFacilities against the paper in hand; asks Belfor for a line's backing | Belfor answers from Line History (who, when, why), the reading's raw note, the Hours tab for the vendor-week against the invoice, and the block version digest proving the pasted text matches the lines | nothing new; everything above is already written |

## Constraints

- No new dependencies. Four new tables, one migration. Files under 500 lines: `work_orders_smr.py`
  service is at 366, router 146, domain 324, so the lines service, block renderer and import go in
  new modules (`services/work_orders_smr_lines.py`, `services/work_orders_smr_import.py`,
  `domain/work_orders_smr_block.py`).
- Flat Python, no new abstractions; reuse `_read_sheet`, `append_note_log`, `_xlsx_theme`, the
  `attendance_punch_edits` pattern, the receipt's `pricing_line` helpers.
- Tests before push: parse ties; import idempotent and all-or-nothing; charge rule with and without
  lines; legacy entries not charged when lines exist; status/date DB checks; history row on every
  edit; block renderer pinned at 41 chars; export sheets; Owner/Admin gates; worker FK nulls on
  user delete.
- Deploy is production: ask before pushing main.
- The reconciliation scripts keep running on `paper_review.csv` for the Weeks 1–7 PDFs already
  delivered; they are not rewritten to read the app.

## Builder-check calls (Claude's, overridable)

- Headcount × hours_each, not one line per unnamed person: the paper says "2 BT x 3 h", so the record does.
- Belfor-employee lines are charged lines with vendor `Belfor` (user 2026-10-28: hours stay on the
  order); the Hours tab separates them from vendor totals.
- A re-print reading keeps its lines at status `excluded / reprint` so the names it adds are not lost.
- The paper-check mark is set by the import for every order with a reading; it stays a working flag.
- The block prints excluded lines. Hiding them would hide the 7,790.5 h the reports already disclose.
- `work_order_totals` branch, not a parallel totals function: every consumer (editor, tiles, export,
  target gap) must agree.

## Step 0 spike findings (2026-11-05, throwaway sheet built from the live CSV)

A first-pass parser over `paper_review.csv` ties 538 of the 539 readings that carry hours to their hours
column, with 0 vendor-total mismatches; the one left (Centennial 631, 23288055) is a per-line multi-week note
that needs a human read. Rules the notes forced, which Step 0 and the import must keep:

- A line can carry **its own date** inside the note ("4 h on 06/06", "(1) dated 05/26: ..."), different from
  the reading's date. Such a line is charged by its own date and does not count toward the reading's hours
  when it falls in another week; if another printing of the same order has that date, the line is excluded as
  "counted on the printing of that date" so the order is not charged twice.
- **Week 1 orders placed by crew sheets** (the `week_supplement.P` map) have no paper date: their lines are
  charged in Week 1 with date basis "Week 1 placement (crew sheets, Supplement)" and a blank date. The
  design's "charged requires a work date" check allows this basis as the one exception (decision 13,
  user 2026-11-05).
- Admin names on paper (McClure) become lines with vendor `Admin`, excluded, ground "admin, never charged".
- Re-print readings keep their lines at 0 h charged; the Scholars 2232 Green Choice lines are excluded as
  "awaiting invoice" on every printing, including the one whose note has no marker.
- Restatements inside a note ("Per person: ...", "crews as read: ...", "Each package = ...", "replaces the
  2026-10-29 reading (...)") are not lines; the parser masks them. A "paper names no one" remainder is one
  Unknown-vendor line with reason `not_on_paper`, not a parse failure.
- Order-level rule used by the sheet: **new hours = charged lines when the order has any, else the billed
  hours stand**. Undated, not-found and note-only orders therefore show no change; excluded hours sit in
  their own column. New material = billed material; the app's +15% material is shown beside it and never
  feeds the total (decision 14, user 2026-11-05).

Sheet layout (one row per charge line, order columns repeated, `First line` flag, SUMIFS totals on row 1;
Orders tab = one row per order; Readings tab = the verdict rows verbatim with the parse result). **Built 2026-11-06**
(user approved the layout): `paper_lines.py` + `smr_people.py` write `Deliverable Batch\paper_readings.csv` and
`paper_lines.csv`; `paper_import_sheet.py` writes `Deliverable Batch\SMR27 Paper Import Sheet.xlsx`. Readings the
parser cannot tie are settled by the user in `paper_lines.FIX`, keyed `(wo, printing_no)`. Still open before the
load: Centennial 631, and the per-week differences against the delivered Week Reports (see the Workflow doc,
2026-11-06).

## Builder check (2026-11-04, read inline; no subagent)

Four questions came back; all answered by the user and folded into decisions 9–12. Still open and
not blocking: Cimarron J6 needs an order number before its crew-sheet rows can become lines.

## Left to the builder

- Exact block copy and alignment within 41 characters; exact editor copy.
- Whether `SmrLineOut` and friends live in `schemas/work_orders_smr.py` (likely).
- Alembic revision id; `docs/endpoint-map.md` lines; `docs/current-state.md` row update.
- The Hours tab's layout; it may reuse the SMR page's filter row.

## Deviations

- 2026-11-06 · Five tables, not four. The Data section lists five (`smr_workers`, `smr_paper_readings`, `smr_labor_lines`, `smr_line_edits`, `smr_correction_blocks`); built as listed.
- 2026-11-06 · New schemas live in `schemas/work_orders_smr_lines.py` (user), not `schemas/work_orders_smr.py` as "Left to the builder" guessed: `WorkOrderDetail` needs them without an import cycle and `schemas/work_orders.py` stays under 500 lines.
- 2026-11-06 · Breakdown rows for the eight missing orders come from an optional third upload `breakdown` on `POST /work-orders/smr/import-paper` (user). The targets import never stores unknown WO#s, so the app has no copy of those rows.
- 2026-11-06 · The five tables are SQLAlchemy classes in `backend/app/models_smr.py`, imported at the foot of `models.py` (1,234 lines, past its budget).
- 2026-11-06 · `smr_labor_lines.import_key` (text, nullable, unique) holds the CSV `line_id`, the import's idempotence key; null for a line added in the app.
- 2026-11-06 · `smr_labor_lines.date_basis` (text, not null, default `paper`) and `week` (int, nullable) are columns, per decision 13 and the build prompt; the Data table predates them. The charged check reads `status <> 'charged' OR work_date IS NOT NULL OR date_basis = 'Week 1 placement (crew sheets, Supplement)'`.
- 2026-11-06 · Line vocabulary (vendors, kinds, grounds, reason codes, date bases), the status rules, `week_of`, the tie check and the CSV row parsers live in `domain/work_orders_smr_lines.py`, a module the design does not name: `domain/work_orders_smr.py` (324 lines) has no room and `domain/work_orders_smr_block.py` is the renderer.
- 2026-11-06 · `vendor unknown` added to the exclusion-ground tuple (user; decision 10 names it, the draft list lacked it). `kind` is stored as given, a comma list validated token by token (user).
- 2026-11-06 · User FKs the design leaves unspecified (`created_by_id`, `updated_by_id`, `generated_by_id`, `pasted_by_id`, and `smr_labor_lines.reading_id`) are `ON DELETE SET NULL`; `smr_line_edits.edited_by_id` is a plain not-null FK like `attendance_punch_edits`.
- 2026-11-06 · `as_read` added to the seed reason codes ("hours as read on the paper"); the import fills it where `paper_lines.csv` leaves `reason_code` blank (1,736 of 1,774 lines; user 2026-11-06, over regenerating the CSV or allowing a blank). The seed list is builder-extendable by design.
- 2026-11-06 · Blank `date_basis` on an excluded line is stored as `paper` (user 2026-11-06; 575 such lines in the current CSV).
- 2026-11-06 · A line's worker must be live (not merged away) and of the line's vendor, checked in `add_line` / `edit_line`; the design is silent, and the Hours tab's vendor × week would otherwise disagree with the worker's own vendor.
- 2026-11-06 · A worker merge writes one `worker_id` history row per re-pointed line (old and new ids as text); the design asks for a row per line without naming the field.
- 2026-11-06 · The SMR page's "Has lines" and "Block stale / not pasted" filters are `has_lines` and `block_stale_or_unpasted` boolean query params on `GET /work-orders/smr`, applied after the list's own predicates.
- 2026-11-06 · The Breakdown rows for the third upload come from `C:\Users\mcclu\Desktop\SMR27 Work Order Breakdown & Labor Hours.xlsx` (sheet `Work Order Breakdown`, 690 rows, 4,455.5 h), exported to `Deliverable Batch\breakdown.csv` (user 2026-11-06); the Paper Import Sheet workbook has no Breakdown sheet.
- 2026-11-06 · "One commit or nothing" holds for readings, lines, workers and history, not for a reviewed order created from the Breakdown: `get_or_create_work_order` (the creator the build prompt names) commits on its own, so the created order's `smr_imported_at`, baseline and target are committed with it. A run that fails after that point is rerun as is; the order is then found as an SMR order and completed idempotently.
- 2026-11-06 · Decision 13 generalised (user, after the 61 h gap decomposition): a second placement basis `week placement (weekly reports)` charges with a blank day, for the hours only the weekly reports place (the 0.5 h clean-up on 342 orders, 171 h; the no-name undated lines, 3.5 h). `paper_lines.csv` carries `week` (1–7), read for this basis only (a date always wins); such lines hang on a dedicated reading per order with `hours_as_read` blank, so the tie check skips them. Migration `451c56c5643a` widens `ck_smr_labor_lines_charged_dated` to either placement basis with `week IS NOT NULL`; the block prints `week of <that Monday>` and sorts the line into its week. The 30 h XXL audit/staging and 74.5 h own-week printings stay lines, excluded `read, not charged (user)` with a note; the 8.5 h Belfor-only Young Hall lines stay charged. The editor cannot yet add a week placement without a date (no `week` on `SmrLineIn`; the rule answers 400 "needs its week").
- 2026-11-06 · A line removed in the app (ground `removed`) does not print in the block at all; history keeps it. The design printed every excluded line under `Not charged:`. Its hours still count in the tiles' excluded figure.
- 2026-11-06 · New ground `read, not charged (weekly reports)`, tie-counted: the audit/staging add on the 30 accurately billed orders (60 lines, 30 h) and the printings dated into a week no report carries (22 lines, 75 h) are inside `hours_as_read` on dated readings, so `read, not charged (user)` (outside the figure, not counted) would fail the tie on 39 readings. The block shortens it to `not charged (reports)`. The parser reads the `week` column only on the week placement basis; on every other basis it is ignored whatever it holds (the regenerated files once carried `Before W1` there).
