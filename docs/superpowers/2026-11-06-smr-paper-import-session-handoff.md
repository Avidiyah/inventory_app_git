# SMR27 paper import — session handoff (2026-11-06, after Task 5)

Paste this into the next chat. The task is
`C:\Users\mcclu\Desktop\SMR27 Reconciliation\PROMPT - inventory_app prep for SMR27 paper import.md`;
the design of record is `docs/superpowers/specs/2026-11-04-smr-paper-import-design.md`, whose
`## Deviations` tail is the running log (append every departure, dated). Memory
`smr-paper-import-workstream` holds the settled answers.

## State of main (local, 8 commits ahead of origin, unpushed; Alembic head `8e0f2a4b5c63`)

| Commit | Content |
|---|---|
| `4f46ef8` | Task 1: spec copied + Deviations, current-state.md, endpoint-map rows S6–S16 |
| `d805b90` | Tasks 2–3: migration, `models_smr.py`, `domain/work_orders_smr_lines.py`, `domain/work_orders_smr_block.py` |
| `0ba8e95` | Task 4 WIP: schemas, import service, `work_order_totals` branch, detail/tile fields |
| `ffe69ef` | Task 4: `services/work_orders_smr_lines.py`, tiles/counts/switches, `_detail` charges the lines, `as_read` |
| `1b230b8` | Task 5: routes S6–S16 on `routers/work_orders_smr.py`, S2 switches, gates, `test_smr_lines_routes.py` |
| `f28e8b7` | Fix: an order created from the Breakdown commits with its SMR mark (rerun-safe) |

Tasks 1–5 are done and reported per the prompt's §8. 261 tests pass across the SMR family
(`test_smr_*.py`, `test_work_orders_smr_domain.py`, `test_models_smr.py`,
`test_work_order_skilled_labor.py`, `test_route_role_gates.py`, `test_receipt.py`); `app.openapi()`
builds. Nothing has been imported.

## Settled with the user on 2026-11-06 (do not re-ask)

- Decision 13 holds; `date_basis` NOT NULL default `paper`; `week` column; `kind` stored as a
  comma list; `vendor unknown` ground; third upload `breakdown`; shapes in
  `schemas/work_orders_smr_lines.py`.
- Blank `reason_code` in `paper_lines.csv` → the parser fills the seed code `as_read`; the CSV is
  not regenerated. Blank `date_basis` on an excluded line → `paper`.
- Work continues on local main. The Breakdown for the third upload is
  `Deliverable Batch\breakdown.csv`, exported from
  `C:\Users\mcclu\Desktop\SMR27 Work Order Breakdown & Labor Hours.xlsx` (sheet `Work Order
  Breakdown`, 690 rows → 683 unique numbers, all eight missing orders present).

## Open with the user

- Approve the pinned block (`tests/test_smr_block.py::test_one_full_block_verbatim`) before the
  frontend shows it. Question raised: lines removed in the app (ground `removed`) print under
  `Not charged:`; the design prints every excluded line, but a mistaken keying may not belong in
  the pasted text.
- Cimarron J6 still needs an order number (prompt §6).
- Push: ask first (deploy is production). Tasks 6–9 (editor section, SMR page + Hours tab,
  export sheets, targeted run) only when told.

## Dry run of the real files (read-only, 2026-11-06)

`_parse` + `_cross_check` over the three Deliverable Batch files: 567 readings, 1,774 lines, 683
Breakdown numbers, all ties pass; 1,185 charged lines / 2,878.5 h, 3,344.0 h excluded,
$179,906.25; 78 Week 1 placement lines; `as_read` on 1,736 lines. App run id for these bytes:
`import 8db27dbf3dfc` (readings + lines only). The reconciliation session
(`smr27-reconciliation-ba`) owns the CSVs and got the same figures.

## Rules

Ask before pushing `main`. Targeted tests only, from `backend\` (the app mounts `static` relative
to the cwd): `backend\venv\Scripts\python.exe -m pytest tests\<file>.py`. Stage explicit paths;
peer sessions share this checkout. No subagents.
