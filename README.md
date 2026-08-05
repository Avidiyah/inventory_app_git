# Inventory App

Self-hosted inventory and work-order staging app for barcode-tracked stock.

The current source of truth for product behavior, architecture, routes, data
model, deployment, and known gaps is the current code, backed by these
repository documents:

- [docs/current-state.md](docs/current-state.md) — contracts, invariants, data
  model, deployment.
- [docs/endpoint-map.md](docs/endpoint-map.md) — every endpoint wired
  Database ↔ User View (read/write flows, table index). Start here to locate the
  files for a given endpoint without searching.
- [docs/project-summary.md](docs/project-summary.md) — concise current-worktree
  orientation and verification baseline.
- [docs/improvement-tracker.md](docs/improvement-tracker.md) — requested
  improvements, completion status, and superseding changes.

`docs/ux-review.md` and `docs/handoff.md` are dated historical records, not
current-state authorities. If any document conflicts with the working code,
trust the code and reconcile the documents.
