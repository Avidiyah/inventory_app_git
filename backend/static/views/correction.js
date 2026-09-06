// View: correction (quantity adjust) editor on Saved Items.
//
// Layer: views. Sibling of `notes.js` and `itemEditor.js`. Opens an
// inline panel when the user clicks "Correct" on an item row,
// captures the absolute new quantity and a required reason, and
// posts to `POST /transactions/adjust` (Admin+). The panel itself is
// `correctionPanel.js`, shared with the Tools page.
//
// Public surface:
// - `openCorrection(item)` populates and reveals the panel.
// - `closeCorrection()` hides it (called on cancel, on success, and
//   by `items.js` when the open item is deleted).
// - `setOnSaved(fn)` lets the items view register a callback so the
//   table refreshes after a successful correction.

import { apiCreateCorrection } from "../api.js";
import { createCorrectionPanel } from "./correctionPanel.js";

const panel = createCorrectionPanel({
  idPrefix: "correction",
  noun: "item",
  submit: (itemId, { newQuantity, reason }) =>
    apiCreateCorrection({ itemId, newQuantity, reason }),
});

export const setOnSaved = panel.setOnSaved;
export const openCorrection = panel.open;
export const closeCorrection = panel.close;
export const getEditingCorrectionItemId = panel.getEditingId;
