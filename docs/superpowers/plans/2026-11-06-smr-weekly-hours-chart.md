# SMR weekly hours chart — plan (2026-11-06)

Spec: `docs/superpowers/specs/2026-11-06-smr-weekly-hours-chart-design.md`.
Budget ≤ 3,500 words. Tasks run in order; each ends green before the next.
Run pytest from `backend/` with `.\venv\Scripts\python.exe -m pytest`; Vitest
from repo root with `npm test -- tests/frontend/views/smr.test.js`.

Two spec refinements, found while planning (apply, no re-litigation):

- Invoice CSV columns follow the reconciliation workbook's *Invoice Lines*
  sheet: `Invoice,Date,Vendor,Worker,Hours` (header match case-insensitive;
  `Worker` optional and ignored). `Invoice` is the spec's `source`.
- Original's vendor: the baseline's `ASSIGNED TO` is a person, not a vendor.
  Resolve it through `smr_workers` (display name or alias, case-insensitive)
  to that worker's vendor; no match → `Unknown`. One grey "NetFacilities"
  segment is the fallback if the user prefers; not in this plan.
- Weeks are the existing ints (`week_of`, 1–7; `<1` Before W1, `>7` After W7,
  `None` undated), labelled by `rules.week_label`. Not Monday dates.

## Task 1 — model + migration

Goal: `smr_vendor_invoices` table.
Files: `backend/app/models_smr.py` (add class), `backend/alembic/versions/a1b2c3d4e5f6_smr_vendor_invoices.py` (new; `down_revision = "9b2c4d6e8f10"` — confirm it is the head with `alembic heads`), `backend/tests/test_models_smr.py` (one round-trip).
Steps:
1. `SmrVendorInvoice(Base)`: `id` UUID pk, `invoice` Text nn, `vendor` Text nn, `work_date` Date nn, `week` Integer nn, `hours` Numeric(8,2) nn, `uploaded_at` DateTime(tz) nn default `_now`, `uploaded_by_id` UUID FK users SET NULL. Index on `invoice`. No unique constraint: a re-upload deletes by `invoice` first (Task 2).
2. Migration mirrors `9b2c4d6e8f10` style; `downgrade` drops the table.
3. Export it from `models.py`'s `models_smr` import block.
Test: insert one row, read back `week == rules.week_of(work_date)`.

## Task 2 — invoice import service + route

Goal: Owner CSV upload, rerun-safe by invoice number.
Files: `backend/app/services/work_orders_smr_lines.py` (add `import_invoices`), `backend/app/schemas/work_orders_smr_lines.py` (`SmrInvoiceImportResult`: `total`, `invoices: list[str]`, `hours: Decimal`), `backend/app/routers/work_orders_smr.py` (`POST /invoices`, copy of `import_smr_targets` route body, Owner, `read_capped`), `backend/tests/test_smr_lines_routes.py`.
Steps:
1. Parse with `smr_service._read_sheet(csv_bytes, required=("Invoice", "Date", "Vendor", "Hours"))`; per row: `vendor` must be in `rules.VENDORS` else `WorkOrderStateError("Row N: unknown vendor X.")`; `rules.parse_date(..., where="Date")`; hours Decimal > 0. All rows parse before any write.
2. Delete existing rows whose `invoice` is in the file's set, insert the parsed rows with `week = rules.week_of(day)`, one commit.
3. Route: `@router.post("/invoices", response_model=SmrInvoiceImportResult, ...)`, Owner gate, `DomainError → to_http`.
Test: Owner upload of two rows → 2 rows; same file again → still 2 (replaced, not 4); a second invoice number adds; Admin → 403; bad vendor → 400 naming the row.

## Task 3 — weekly series service + route

Goal: `GET /work-orders/smr/weekly-hours` (Admin+).
Files: `backend/app/services/work_orders_smr_lines.py` (`weekly_hours`), `backend/app/schemas/work_orders_smr_lines.py` (`SmrWeeklyCell`: `week: Optional[int]`, `week_label`, `vendor`, `original`, `added`, `invoiced`, `missing` Decimals; `SmrWeeklyHoursOut`: `weeks`, `vendors`, `cells`), router (`GET /weekly-hours`, next to `/hours`), `backend/tests/test_smr_lines.py`.
Steps:
1. Original: for every work order with `smr_imported_at IS NOT NULL` (archived included, as S2): hours = (`totals.real_billed_minutes + totals.skilled_billed_minutes`) / 60 from `smr_baseline`; week = `rules.week_of(COMPLETION DATE)` via the same parse `smr_service.closed_week` uses (factor a `closed_week_number(work_order) -> Optional[int]` out of it and make `closed_week` call it); vendor = worker lookup on `source_row["ASSIGNED TO"]` (build one dict name→vendor from `smr_workers` incl. aliases, lower-cased) else `Unknown`.
2. Added: `SmrLaborLine` with `status == STATUS_CHARGED`, `rules.line_hours(line)`, keyed `(line.week, line.vendor)`.
3. Invoiced: `SmrVendorInvoice` summed by `(week, vendor)`.
4. `missing = max(invoiced - added, 0)` per cell. `weeks` = sorted ints then `None` last if present; `vendors` = those that appear, in `VENDORS` order. Emit a cell for every (week, vendor) with any nonzero figure.
Test: one SMR order, baseline 600 billed minutes, closed 06/10 (week 3), assignee matching a Green Choice worker; one charged GC line 4 h week 3; invoices GC week 3 30 h → cell `{3, Green Choice, 10, 4, 30, 26}`; an order with no close date → week `None`; Technician → 403.

## Task 4 — front end: API + chart module

Goal: the chart, dependency-free SVG.
Files: `backend/static/api.js` (`apiSmrWeeklyHours`, `apiImportSmrInvoices` copied from the targets pair), `backend/static/views/smrWeeklyHours.js` (new, ≤ 250 lines), `backend/static/styles.css` (`.smr-weekly*` + one `.smr-vendor--<slug>` fill class per vendor), `tests/frontend/views/smrWeeklyHours.test.js` (new; `importView` per `vitest-view-module-instances`).
Steps:
1. `loadWeeklyHours(panel)`: fetch, then `panel.innerHTML = chartHtml(payload) + legendHtml + tableHtml`. On error `setMessage(message, friendlyError(err))` as smrHours.js does.
2. `chartHtml`: viewBox `0 0 (weeks*96+48) 260`; per week a `<g data-week>` with three bars (Original, Added, Missing) 24 px wide, 4 px gap, stacked vendor `<rect>`s with `class="smr-vendor--green-choice"` etc.; y scale `niceStep(max)` logic copied from hubGraphs.js (do not import — it is a Hub leaf); gridlines + left axis labels; bar label under each trio (`O / A / M`), week label under the group. `<title>` on each rect: `"Green Choice · 26.0 h missing"`. No `style=` attributes (CSP).
3. Legend: a row per vendor with its colour swatch; a second row naming O/A/M. Table: week rows × Original / Added / Missing / Invoiced totals, same figures as the SVG.
4. Vendor colours: Green Choice green, XXL blue, BT amber, Belfor red (TechFM primary), Unknown grey, Admin dark grey — tokens in `:root`, both themes.
Test: render fixture with two weeks and two vendors → two `g[data-week]`, six bars, four vendor-class rects, legend rows per vendor, table cell for missing reads `26.0`.

## Task 5 — SMR page wiring

Goal: panel above the search, Admin+, collapsible, Owner invoice upload.
Files: `backend/static/pages/smr.html`, `backend/static/views/smr.js`, `tests/frontend/views/smr.test.js`.
Steps:
1. HTML, directly after `#smr-bar`: `<details id="smr-weekly" class="smr-weekly" open hidden><summary>Weekly hours</summary><div id="smr-weekly-body"></div></details>`; an Owner button `#smr-invoices-btn` ("Upload invoices") + hidden file input beside the existing Hours / export buttons.
2. smr.js: in the role gate next to `hoursBtn`, unhide `#smr-weekly` for Admin+ and call `loadWeeklyHours` once; `#smr-invoices-btn` for Owner. Persist the `open` state in localStorage key `smr.weeklyOpen` on `toggle` (wrap in try/catch). After an invoice upload, reload the chart and `setMessage` the result (`"3 invoices, 412.0 h"`).
3. Test: Admin boot → `#smr-weekly` visible and populated; Technician → hidden; Owner sees the upload button, Admin does not.

## Task 6 — docs + handoff

Files: `docs/endpoint-map.md` (rows S17 `POST /work-orders/smr/invoices`, S18 `GET /work-orders/smr/weekly-hours`), `docs/current-state.md` (smr.js line: chart panel; new module line; tests table), `docs/open-work.md` (close the handoff's "vendor invoices → weekly graph" item), delete the stale item from `docs/superpowers/plans/2026-11-06-smr-paper-stage-handoff.md` §2.
Then: targeted tests only (`test_smr_lines.py test_smr_lines_routes.py test_models_smr.py` + the two Vitest files), commit on main, **ask before push** (CI gate = deploy).

## Load (user, after deploy)

Export the *Invoice Lines* sheet of `Desktop/SMR27 Reconciliation/SMR27 Timesheets.xlsx` to CSV (`Invoice,Date,Vendor,Worker,Rate,Hours`; extra `Rate` column is ignored) and upload it as Owner.
