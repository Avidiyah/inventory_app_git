// Field-help copy for the `?` bubbles. Keys are stable ids referenced from
// markup via `data-tip`; see docs/superpowers/specs/2026-08-23-tooltips-design.md.
//
// Layer: data only. No imports, no functions -- the whole body of field-help
// copy is meant to be read and edited as prose in one place (spec D1).
//
// `label` is the accessible name of the button ("Help: <label>"); `text` is the
// bubble body. Plain text only, 1-3 sentences, no markup and no links (D5) --
// both are escaped at render time.
//
// Key naming: `<area>.<thing>`, lowercase, dot-separated. The area prefix keeps
// the registry grouped by page when sorted, which is how it gets reviewed.
export const TIPS = {
  // --- Work Orders (pages/work-orders.html) ------------------------------
  "wo.priority-vs-level": {
    label: "Priority and Priority level",
    text: "Priority is the category imported from NetFacilities. Priority level is TechFM's own High/Medium triage layered on top of it. They filter independently.",
  },

  // --- Transaction (pages/transaction.html) ------------------------------
  "txn.quick-mode": {
    label: "Quick mode",
    text: "Quick mode commits a dispense scan immediately instead of asking you to confirm each one. Add Stock always keeps its confirmation step.",
  },
};
