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
- [docs/open-work.md](docs/open-work.md) — the only backlog: every improvement
  still open, what was ruled out, and what was audited and found to be a
  non-issue.
- [docs/adding-a-notification-trigger.md](docs/adding-a-notification-trigger.md)
  — procedure: how to make a business event send a Web Push notification.
- [docs/notification-events.md](docs/notification-events.md) — the living
  register of what notifies whom: every event, who raises it, and who is told.
  Updated in the same commit as any notification change.

The docs were consolidated from ten files to four on 2026-08-10; shipped
history lives in git rather than in a doc. If any document conflicts with the
working code, trust the code and reconcile the document.
