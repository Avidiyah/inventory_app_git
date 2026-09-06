// View: tool count correction editor on the Tools page.
//
// Layer: views. Sibling of `correction.js` (items) -- the same panel
// (`correctionPanel.js`) under the `tool-correction-*` ids, posting to
// `POST /tools/{id}/adjust` when Admin+ picks "Correct Count" on a tool row.
//
// Public surface:
// - `openToolCorrection(tool)` populates and reveals the panel.
// - `closeToolCorrection()` hides it (called on cancel, on success, and by
//   tools.js when the open tool is archived).
// - `setOnSaved(fn)` lets tools.js register a callback so the table
//   refreshes after a successful correction.

import { apiAdjustTool } from "../api.js";
import { createCorrectionPanel } from "./correctionPanel.js";

const panel = createCorrectionPanel({
  idPrefix: "tool-correction",
  noun: "tool",
  submit: (toolId, { newQuantity, reason }) =>
    apiAdjustTool(toolId, { newQuantity, reason }),
});

export const setOnSaved = panel.setOnSaved;
export const openToolCorrection = panel.open;
export const closeToolCorrection = panel.close;
export const getCorrectingToolId = panel.getEditingId;
