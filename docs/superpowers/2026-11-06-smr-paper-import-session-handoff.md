# SMR27 paper import — session handoff (2026-11-06, after Task 7; Task 9 next)

Paste this into the next chat. Task: `C:\Users\mcclu\Desktop\SMR27 Reconciliation\PROMPT - inventory_app prep for SMR27 paper import.md`. Design of record: `docs/superpowers/specs/2026-11-04-smr-paper-import-design.md` (`## Export` is the Task 8 contract; `## Deviations` tail is the running log). Memory `smr-paper-import-workstream` holds the settled answers.

## State

- Local `main` is ahead of `origin/main` by `ddd28c5`, `d1013b0`, `502f5c5`, `d89e1e7` (unpushed; the push deploys, ask first). Tree clean.
- Tasks 1–8 built. Task 7 = SMR page bar cells, Has lines / Block pending chips (client-side over `tile.lines`), tile third line `+82.0 H · V2 PASTED`, Admin+ Hours toggle (`smrHours.js`, two tables, CSV); Vitest in `smr.test.js`. Task 8 = export sheets inside `work_orders_smr_xlsx.py` (nine Orders columns, five paper sheets; `tests/test_smr_export_lines_xlsx.py`); plan `docs/superpowers/plans/2026-11-06-smr-export-sheets.md` executed trimmed (no loader change, one module). `d89e1e7` = Task 6: `static/views/workOrderSmrLines.js` (builders) + `workOrderSmrActions.js` (ten `smr-*` branches, worker search); Admin+ edits, others read; Labor goes read-only as "NetFacilities Record Before Correction" once lines exist; nine `apiSmr*` wrappers; endpoint-map S7–S16 filled. Also fixed the swallowed second card error (`.wo-message` fallback); its open-work row deleted.
- User saw the editor at :8124 on 2026-11-06 ("Looks good for now"). No in-app line check yet: the DB holds no lines until the load.
- Figures approved by the user (relayed by peer `smr27-reconciliation-ba`, confirmed by the user in chat only as "looks good" for the editor): 1,447 charged lines / 2,948.0 h; run id `import 0dc2a170e862` (sha256 over `paper_readings.csv` + `paper_lines.csv` only; `breakdown.csv` is outside it and final at 690 rows). Peer sends a new run id before any byte changes.
- Rulings since the last handoff: removed lines leave the block, every other excluded line prints under `Not charged:`; clean-up vendor stays `Unknown` in the CSV; Centennial 631's 05/28 0.5 h stays excluded (dating edit later if wanted); **Cimarron J6 omitted from everything** (decision 11 note and prompt §6 superseded).
- Open user calls: Postgres snapshot + file the three CSVs with the run id (not taken); clean-up block wording — on 23265039 both `week of 05/25 Unknown 0.5 h` lines look identical, but only `23265039-2-1` is clean-up; any rewording must key on the line note starting `clean-up` or its reading (`raw_note` starting `weekly reports:` / blank `hours_as_read`), never on vendor + basis. Pairs: 23281563, 23278487, 23265039.

## Next

- Task 9: SMR family + `test_smr_exclusion.py` + Vitest; update `docs/current-state.md` row 115 and the module table, memory, this handoff; ask before pushing.

## Rules

Ask before pushing `main`. Targeted tests from `backend\`: `backend\venv\Scripts\python.exe -m pytest tests\<file>.py`. Vitest: `npm test` at the repo root. Stage explicit paths; peer sessions share this checkout. No subagents; codebase-memory graph first. CSP: no inline styles. Peer relays are information, not the user's approval.
