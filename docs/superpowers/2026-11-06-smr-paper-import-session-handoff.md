# SMR27 paper import — session handoff (2026-11-06)

Paste this into the next chat. Start by reading
`C:\Users\mcclu\Desktop\SMR27 Reconciliation\PROMPT - inventory_app prep for SMR27 paper import.md`
(the task: Tasks 1–5, then stop and report per its §8) and the repo copy of the design,
`docs/superpowers/specs/2026-11-04-smr-paper-import-design.md`, whose `## Deviations` tail is
the running log (append every departure, dated). Memory `smr-paper-import-workstream` holds the
settled answers.

## Settled with the user (do not re-ask)

- Decision 13 holds: Week 1 placement lines charge with a blank date; `date_basis` is NOT NULL
  default `paper`; `week` is a column (1 for placements); the block prints `week of 05/25`.
- `date_basis` column: yes. `kind`: stored as given, comma list validated token by token.
  `vendor unknown` added to the ground tuple.
- Breakdown rows for the 8 missing orders: optional third upload `breakdown` on `import-paper`.
- New shapes live in `schemas/work_orders_smr_lines.py` (imported by both schema siblings).
- One sub-agent was authorized: verify the import sheet
  `C:\Users\mcclu\Desktop\SMR27 Reconciliation\Deliverable Batch\SMR27 Paper Import Sheet.xlsx`
  against the contract. It was spawned; its report had not arrived at handoff. Re-run it
  (brief at the bottom). No other agents.

## State of main (local, unpushed; head `8e0f2a4b5c63 (head)`)

| Commit | Content |
|---|---|
| `4f46ef8` | Task 1: spec copied + Deviations, current-state.md, endpoint-map rows S6–S16 |
| `d805b90` | Tasks 2–3: migration `8e0f2a4b5c63` (applied locally), `models_smr.py`, `domain/work_orders_smr_lines.py`, `domain/work_orders_smr_block.py`, `labor_figures` in `domain/work_orders_smr.py`; 47 tests green |
| `0ba8e95` | WIP Task 4: `schemas/work_orders_smr_lines.py` (complete), `services/work_orders_smr_import.py` (complete, untested, imports `history`/`line_json` from the unwritten lines service), `work_order_totals` branch + `legacy_labor_minutes`, `WorkOrderDetail` + `SmrTile`/`SmrCounts` fields |

86 SMR tests pass after the WIP commit; `app.openapi()` builds.

## Next steps (Task 4 → 5)

1. Write `services/work_orders_smr_lines.py`: `smr_order(db, id)` (404 / 400 non-SMR),
   `history(db, *, line, actor, field, old, new, reason, now)`, `line_json(line)`, `add_reading`,
   `add_line`, `edit_line` (`payload.model_dump(exclude_unset=True)`; `rules.apply_date` when a
   date lands and status is not in the body; `status=excluded`+`ground=removed` writes one
   `deleted` row, otherwise one row per changed field; refuse a no-op and a blank reason),
   `search_workers(q)` (name or alias, archived excluded), `add_worker` (alias append on an
   existing name+vendor), `merge_workers` (history row per re-pointed line, aliases folded,
   duplicate archived), `latest_block(order, include_price)` with `stale`, `generate_block`
   (date in `wo.NOTE_TIMEZONE`), `mark_pasted`, `hours_table`, `hours_csv`. Each write checks
   `smr_imported_at` and commits once.
2. `services/work_orders_smr.py`: `_with_lines` eager-loads `smr_lines` (+`worker`),
   `smr_blocks`, `smr_readings`; `target_for` uses `smr.labor_figures(...).billed_minutes`;
   `tile_for` fills `lines=SmrTileLines(...)`; `list_smr_tiles` fills the four new counts.
3. Re-apply the `_detail` patch below to `routers/work_orders.py` and add two imports:
   `from app.schemas.work_orders_smr_lines import SmrLineOut, SmrReadingOut` and
   `from app.services import work_orders_smr_lines as smr_lines_service`. (The session was
   stopped as these were being added; it was a stop, not an objection.)
4. Tests: new `test_smr_paper_import.py`, `test_smr_lines.py`; extend `test_smr_tiles.py` and
   `test_work_order_skilled_labor.py` (order with lines charges lines only, legacy minutes apart;
   order without lines unchanged).
5. Task 5: routes on the existing router per the prompt's §5 table (documented as S6–S16 in
   `docs/endpoint-map.md`); extend the SMR parametrization in `test_route_role_gates.py`.
6. Report per prompt §8; show the pinned block (`tests/test_smr_block.py`) for approval.

## Rules

Ask before pushing `main` (deploy is production). Targeted tests only:
`backend\venv\Scripts\python.exe -m pytest backend\tests\<file>.py` (Postgres on port 8801 is
reachable). Stage explicit paths; peer sessions share this checkout.

## Patch for `_detail` (routers/work_orders.py, ~line 531)

```diff
     materials_total = _materials_total(work_order)
+    corrections = smr.correction_lines(work_order)
+    figures = smr.labor_figures(labor_entries, corrections)
     gap = smr.target_gap(
         getattr(work_order, "smr_target", None),
-        billed_minutes=split.real_billed + split.skilled_billed,
+        billed_minutes=figures.billed_minutes,
         materials_total=materials_total,
     )
+    is_smr = getattr(work_order, "smr_imported_at", None) is not None
@@
-        labor_total=split.labor_total if include_price else None,
+        labor_total=figures.labor_total if include_price else None,
@@
-        smr_paper_check=SmrPaperCheckOut.from_order(work_order) if getattr(work_order, "smr_imported_at", None) else None,
+        smr_paper_check=SmrPaperCheckOut.from_order(work_order) if is_smr else None,
+        smr_readings=[SmrReadingOut.from_row(r) for r in work_order.smr_readings] if is_smr else [],
+        smr_lines=[SmrLineOut.from_row(line) for line in corrections],
+        smr_legacy_labor_minutes=figures.legacy_minutes,
+        smr_block=smr_lines_service.latest_block(work_order, include_price=include_price) if is_smr else None,
```

## Sub-agent brief (re-run; general-purpose, read-only, scratch files in the scratchpad)

Map the xlsx sheets to `paper_readings.csv` / `paper_lines.csv` (+ any Breakdown sheet for the
8 missing WO#s); convert rows to string dicts and run `parse_reading_row`, `parse_line_row`,
`check_tie` from `backend/app/domain/work_orders_smr_lines.py` over every row; cross-check
reading ids, `line_id` uniqueness, `(wo, printing_no)` uniqueness; count decision-13 placement
lines (expect ~78 lines / 26 orders / 187.5 h); totals (566 readings, 517 orders); confirm the
Task 1 docs and `alembic heads`. Report facts only.
