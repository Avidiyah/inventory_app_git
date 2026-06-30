# Inventory App

Self-hosted inventory and work-order staging app for barcode-tracked stock.

The current source of truth for product behavior, architecture, routes, data
model, deployment, and known gaps is:

- [docs/current-state.md](docs/current-state.md) — contracts, invariants, data
  model, deployment.
- [docs/endpoint-map.md](docs/endpoint-map.md) — every endpoint wired
  Database ↔ User View (read/write flows, table index). Start here to locate the
  files for a given endpoint without searching.
