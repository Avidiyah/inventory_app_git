# SMR27 audit + target match — session handoff (2026-10-23)

Specs `docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md` and
`docs/superpowers/specs/2026-10-23-smr-target-match-design.md` · plans
`docs/superpowers/plans/2026-10-23-smr-audit-workflow.md`,
`docs/superpowers/plans/2026-10-23-smr-target-match.md`.

## State

| Item | Value |
|---|---|
| `main` | target match **pushed 2026-10-23** (`b78f7e7..1f58090`, 12 commits); production deploy follows CI; the user's in-app check in production is the real gate |
| Container | `inventory-local` on port 8124 rebuilt from `1f58090` |
| Dev DB | migrations `5b7c9d1e2f30` and `6c8d0e2f3a41` applied; 0 SMR rows |
| Suites | backend 2,156 passed (`-m "not e2e"`); frontend 2,499 passed |

## What shipped

Audit workflow: Owner SMR Import → closed-but-unarchived SMR orders with a
frozen baseline; SMR27 page (Admin+, Untouched default, Work Orders
search/filters, Owner export); Skilled Technician labor; four-sheet
before/after/delta workbook; SMR rows off every live surface.

Target match: Owner **SMR Labor Import** (NetFacilities card) takes the
client's Breakdown sheet and writes `smr_target` on each matching SMR order
(last duplicate wins, unknown WO#s counted not created, re-import overwrites).
`target_gap` compares billed hours (real + skilled) and material × 1.15
against it; matched = within 0.5 h / $10 below target, or anything above.
The editor shows a target line under Labor and under Materials; the SMR page
adds Matched / Short / No Target counts, remaining hours and dollars, a line
per tile, and Short + Matched filters; the Orders sheet gains target, gap and
`BREAKDOWN *` columns.

## Next

1. **In-app check (user):** rebuild `inventory-local`; Owner → Integrations →
   SMR Import with `Copy of SMR27 Work Orders - SMR27 Work Orders.csv`, then
   SMR Labor Import with `SMR27 Work Order Breakdown & Labor Hours - Work Order
   Breakdown.csv` (expect about 668 orders set, 22 unknown WO#s skipped, 1
   footer row skipped). SMR27 → Short → tile → add Skilled hours and material
   lines → watch the two target lines → Export XLSX.
2. **Production:** run both imports there once the deploy is live; the main-sheet import restores archived orders by design.
3. Deferred minors: `#smr-page` side margins on phone width; the three
   Breakdown rows whose Labor $ is not hours × $62.50 show their sheet Labor $
   in the export only; `current-state` / `endpoint-map` over word budget
   (pre-existing).
