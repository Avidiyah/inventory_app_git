# SMR27 paper stage — Session Handoff (after the card cleanup + keyed names)

**Plan:** `docs/superpowers/plans/2026-11-06-smr-paper-stage.md` · **Spec:** `docs/superpowers/specs/2026-11-06-smr-paper-stage-design.md` (Deviations section is current)
**Branch:** `main`, local only, **not pushed** (pushing deploys). `origin/main` is at `1c6e1f5`; local is 11 ahead.

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
| `ac95d23` | card cleanup — Request + Signature sections off the card (modules/routes kept, unmounted) |
| `c23d63f` | keyed names — paper lines as Labor-style entries; add row name / headcount / hours / date / vendor; worker picker gone; server links a keyed name to a live worker/alias of the vendor |

Task 7 in-app check done 2026-11-06 in Chrome: defaults, chips, Ready stamp and Not ready all behave. Test stamp on 23476746 was cleared.

Known: `test_models_smr::test_paper_correction_tables_round_trip` fails on a leftover `smr_workers` row ("Trinton Smith / XXL Construction") in the local DB — environmental; delete the row or ignore.

## Next (user, 2026-11-06) — spec/options first, then build

1. **In-app check** of the two commits above (not done yet): card without Request / Signature; Paper corrections add row keys a named hand, an unnamed one and a crew (`3× BT crew`); Edit still opens the full form; Hours tab groups an unlinked keyed name under that name.
2. **Vendor invoices → weekly hours-to-fill graph.** Import the vendor invoices (per vendor, per Mon–Sun week) and show a persistent chart: hours invoiced vs hours placed per week, so the remaining gap per week is always visible; use it to place undated orders into dated piles. Needs: an invoice model + import (shape of the invoice files unknown — ask), a `GET` for the week series, a chart on the SMR page (dataviz skill; CSP: no inline styles). The Hours tab (`S15`) already gives placed hours per week.

## Notes for the next session

- Chat/UI work in this repo: options table first, wait for the go-ahead (`feedback-ui-change-workflow`).
- `closed_week` reads the sheet's `COMPLETION DATE` from `smr_baseline.source_row`; the import never sets `completed_at`.
- Python edits via a scratchpad script run with `python -I`; long heredocs break in this Bash tool.
- Run pytest from `backend/` with `.\venv\Scripts\python.exe -m pytest`; the dev server is `python -m uvicorn app.main:app --port 8124`, started only when the user asks.
