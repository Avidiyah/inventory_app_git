# SMR27 paper import — session handoff (2026-11-06, after the push; Tasks 6–9 next)

Paste this into the next chat. Task: `C:\Users\mcclu\Desktop\SMR27 Reconciliation\PROMPT - inventory_app prep for SMR27 paper import.md`. Design of record: `docs/superpowers/specs/2026-11-04-smr-paper-import-design.md` (`## Deviations` tail is the running log, 19 entries). Memory `smr-paper-import-workstream` holds the settled answers.

## Goal

Prepare the app for the SMR27 paper-correction import: Tasks 1–5 (schema, domain, services, routes) are built; Tasks 6–9 (editor section, SMR page + Hours tab, export sheets, targeted run) are the go-ahead the user gave on 2026-11-06 ("Accept all of those, start with the push"). Nothing is imported until the user approves the regenerated figures and a Postgres snapshot is filed with the three CSVs and their run id.

## Done this session

- Pushed main `10ced0d` (Tasks 1–5). CI run 42234010324 was in progress; confirm it went green and that Render shows Alembic `451c56c5643a` after the next push.
- `ddd28c5` (local, unpushed): decision 13 generalised. Basis `week placement (weekly reports)` charges with a blank day and a CSV `week` (1–7); migration `451c56c5643a` widens `ck_smr_labor_lines_charged_dated` (applied locally, down/up round-tripped); the block prints `week of <Monday>` from `line.week` and never prints a `removed` line; the import compares `week` on rerun. 242 SMR-family tests green from `backend\`.
- Peer `smr27-reconciliation-ba` regenerated Step 0 on the six rulings (`Deliverable Batch`: `paper_readings.csv` 913 rows = 567 paper + 346 clean-up readings, `paper_lines.csv` 2,118, `breakdown.csv` 683). Its one contract change is built and committed: ground `read, not charged (weekly reports)`, tie-counted (82 lines: the audit/staging add and the own-week printings, which sit inside `hours_as_read`); the parser reads `week` only on the placement basis. Read-only dry run (`_parse` + `_cross_check` + `_resolve_orders`) matches the peer on every count: 1,447 charged lines / 2,948.0 h / $184,250.00; 3,476.5 h excluded; by week 437 / 314 / 337.5 / 603 / 562.5 / 530 / 164; 349 placement lines; no charged line without a week; 8 orders to create from the Breakdown. Run id for the bytes as they stand: `import 0dc2a170e862`. 631 is settled in FIX; Isaiah Smith is `note only`; Cimarron J6 has no row.

## Next: Task 6 (editor), designed, not started

- New `static/views/workOrderSmrLines.js` (builders/presenters: readings, lines table, add/edit forms, block box, totals line) and `workOrderSmrActions.js` (`handleSmrAction`, branching literally on `action === "smr-…"` so `actionCoverage.test.js` sees it; worker search on `.wo-smr-worker-search`). `renderBody` inserts the section above Labor for `detail.smr`; `laborSectionHtml` goes read-only under "NetFacilities Record Before Correction" when `smr_lines` exist.
- Ten actions: `smr-add-reading`, `smr-add-line`, `smr-edit-line`, `smr-exclude-line`, `smr-save-line`, `smr-cancel-line`, `smr-generate-block`, `smr-mark-pasted`, `smr-pick-worker`, `smr-add-worker`. Add them to the frozen `ACTIONS` list and quote each in a test under `tests/frontend/views/workOrders/`.
- `api.js`: `apiSmrAddReading`, `apiSmrAddLine`, `apiSmrEditLine`, `apiSmrSearchWorkers(q)`, `apiSmrAddWorker`, `apiSmrGenerateBlock`, `apiSmrMarkPasted`, `apiSmrHours`, `apiSmrHoursCsv`; a row each in `tests/frontend/helpers/endpointTable.js`; name each in `docs/endpoint-map.md` rows S7–S16 (the doc test requires it).
- Gate is Admin+: `roleAtLeast(getRole(), "admin")` (TechFM OA ranks below Admin; `isAdminPlus()` is the OA floor, wrong here). Factories: add `smr_readings: []`, `smr_lines: []`, `smr_block: null`, `smr_legacy_labor_minutes: 0` to `workOrderDetail`. CSS: `.wo-smr-*` beside `.wo-labor-*`; block textarea reuses `pricing-output`.

## Then

- Task 7: bar cells from `counts.with_lines/charged_hours/excluded_hours/blocks_not_pasted`; chips Has lines / Block stale or not pasted as local `matches()` over `tile.lines`; tile third line `+82.0 H · V2 PASTED`; Hours tab = `smrHours.js` toggling `#smr-tiles` with a table from `apiSmrHours` + CSV download; Vitest in `tests/frontend/views/smr.test.js`.
- Task 8: `services/work_orders_smr_xlsx.py` (orders already eager-load readings, lines, blocks): nine Orders columns + sheets Paper Readings, Labor Lines, Line History, Correction Blocks, Workers; `test_smr_export_xlsx.py`.
- Task 9: SMR family + `test_smr_exclusion.py` + Vitest; ask before pushing. Update `docs/current-state.md` row 115 and the module table, memory, this handoff.

## Rules

Ask before pushing `main`. Targeted tests from `backend\`: `backend\venv\Scripts\python.exe -m pytest tests\<file>.py`. Vitest: `npm test` at the repo root. Stage explicit paths; peer sessions share this checkout. No subagents. CSP: no inline styles.
