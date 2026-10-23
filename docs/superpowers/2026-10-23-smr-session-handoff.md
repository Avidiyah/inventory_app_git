# SMR27 audit workflow — session handoff (2026-10-23)

Spec `docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md` · plan
`docs/superpowers/plans/2026-10-23-smr-audit-workflow.md`.

## State

| Item | Value |
|---|---|
| Local `main` | `323870e`, 14 commits ahead of `origin/main`, **not pushed** (push deploys) |
| Container | `inventory-local` on port 8124 rebuilt from `323870e`; env copy at Git-Bash `/tmp/inventory.docker.env` |
| Dev DB | SMR migration `5b7c9d1e2f30` applied; **0 SMR rows** (the real sheet was dry-run and rolled back) |
| Suites | backend 2,132 passed; frontend 2,483 passed (incl. the new `staticImports` guard) |

## What shipped

Owner-only SMR Import (NetFacilities card) → closed-but-unarchived SMR orders
with a frozen baseline; SMR27 page (Admin+, white-on-black tiles, four
filters, Owner export); Skilled Technician labor (SMR orders, Admin+, separate
rounding); four-sheet before/after/delta workbook; SMR rows excluded from
every live surface via `services.work_orders.live_work_orders()`.

## The blank-page incident

First container build showed a blank page: `smr.js` imported `friendlyError`
from `api.js` (it lives in `format.js`). The browser refused to link the
module graph; Vitest could not see it. Fixed in `323870e` with
`tests/frontend/unit/staticImports.test.js` as the permanent guard. Diagnosis
recipe lives in memory (`vitest-misses-missing-named-exports`).

## Next

1. **In-app check (user):** log in as Owner → Integrations → SMR Import with
   `C:\Users\mcclu\Desktop\Copy of SMR27 Work Orders - SMR27 Work Orders.csv`.
   Dry run predicts 643 created / 38 opened / 0 restored / 7 skipped on the
   dev DB (production will show restores). Then SMR27 page → tile → card →
   Add Skilled Technician → Export XLSX.
2. **Push decision (user):** pushing `main` deploys. Production run of the
   import restores archived orders — that is the intended behaviour (D3).
3. Deferred minors: `#smr-page` negative side margins on phone width;
   `data-technician-id="null"` on skilled entries (unread); `current-state`
   / `endpoint-map` over word budget (pre-existing).
