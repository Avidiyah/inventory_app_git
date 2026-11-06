# SMR27 paper stage — Session Handoff (after Task 7)

**Plan:** `docs/superpowers/plans/2026-11-06-smr-paper-stage.md` · **Spec:** `docs/superpowers/specs/2026-11-06-smr-paper-stage-design.md` (Deviations section is current)
**Branch:** `main`, local only, **not pushed** (pushing deploys). `origin/main` is at `1c6e1f5`; local is 8 ahead.

## Done (one commit per task)

| Commit | Task |
| --- | --- |
| `06940d2` | base — TechFM restyle, week bubbles, spec + plan committed |
| `48430ea` | 1 — `stage` / `closed_week` / `belfor_only` / `ready` on the tile; migration `9b2c4d6e8f10` (applied locally) |
| `bf8e8d0` | 2 — `PUT /work-orders/smr/{id}/ready` (Admin+, 409 `SmrNotDatedError`); detail `smr_stage` + `smr_ready` |
| `ac4d89a` | 3 — NetFacilities Status filter removed |
| `81db56b` | 4 — Stage / Pile / Flags chip rows, stage-colored tiles, stage bar |
| `f0ac478` | 5 — Ready for invoice row on the card |
| `70ac813` | 6 — export columns `STAGE`, `READY AT`, `READY BY`, `BELFOR ONLY`; docs |

Task 7 in-app check done 2026-11-06 in Chrome: defaults, chips, Ready stamp and Not ready all behave. Test stamp on 23476746 was cleared.

Known: `test_models_smr::test_paper_correction_tables_round_trip` fails on a leftover `smr_workers` row ("Trinton Smith / XXL Construction") in the local DB — environmental; delete the row or ignore.

## Next (user, 2026-11-06) — spec/options first, then build

1. **Card page: drop the Requests and Signature sections.** Not needed on work orders. Entry points: `workOrderCardHtml.js:569` (`signatureSectionHtml`), `workOrderList.js:33` (`mountWorkOrderRequests`), the `GET /work-orders/{id}/requests` fetch on card open. Check `actionCoverage.test.js` and the signature tests before deleting.
2. **Paper corrections as standard labor entries with keyed names.** Each line reads like a labor entry; the name is a free-text field filled from the paper review, no worker dropdown/search. GC and BT crews: a crew name plus a headcount for that day (`headcount` already exists on `smr_labor_lines`; `alias_on_paper` is the free-text name today, `worker_id` + the worker search in `workOrderSmrLines.js:79` are what to retire or demote). Decide what happens to `smr_workers` / S10–S12 (keep for the Hours tab's by-worker grouping, or group by the keyed name).
3. **Vendor invoices → weekly hours-to-fill graph.** Import the vendor invoices (per vendor, per Mon–Sun week) and show a persistent chart: hours invoiced vs hours placed per week, so the remaining gap per week is always visible; use it to place undated orders into dated piles. Needs: an invoice model + import (shape of the invoice files unknown — ask), a `GET` for the week series, a chart on the SMR page (dataviz skill; CSP: no inline styles). The Hours tab (`S15`) already gives placed hours per week.

## Notes for the next session

- Chat/UI work in this repo: options table first, wait for the go-ahead (`feedback-ui-change-workflow`).
- `closed_week` reads the sheet's `COMPLETION DATE` from `smr_baseline.source_row`; the import never sets `completed_at`.
- Python edits via a scratchpad script run with `python -I`; long heredocs break in this Bash tool.
- Run pytest from `backend/` with `.\venv\Scripts\python.exe -m pytest`; the dev server is `python -m uvicorn app.main:app --port 8124`, started only when the user asks.
