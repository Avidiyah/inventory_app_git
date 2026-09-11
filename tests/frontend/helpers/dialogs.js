// The shared confirm modal (dom.js `confirmDialog`, markup in shell-tail.html).
//
// A gated action resolves through the REAL overlay; a test answers it here.
// Stubbing dom.js instead would skip the wiring these tests exist to pin.

import { expect, vi } from "vitest";

export const confirmOverlay = () => document.getElementById("scan-confirm-overlay");
export const confirmTitle = () => document.getElementById("scan-confirm-title").textContent;

export async function answerConfirm(yes = true) {
  await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(false));
  document.getElementById(yes ? "scan-confirm-yes" : "scan-confirm-no").click();
  await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(true));
}

// Quantity mode: `steps` > 0 clicks "+" that many times, < 0 clicks "-";
// `type` replaces the field's value outright. Then Yes (default) or No.
export async function answerConfirmQuantity({ steps = 0, type = null, yes = true } = {}) {
  await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(false));
  expect(document.getElementById("scan-confirm-qty").hidden).toBe(false);
  if (type !== null) document.getElementById("scan-confirm-qty-input").value = String(type);
  const btn = document.getElementById(steps > 0 ? "scan-confirm-qty-inc" : "scan-confirm-qty-dec");
  for (let i = 0; i < Math.abs(steps); i += 1) btn.click();
  document.getElementById(yes ? "scan-confirm-yes" : "scan-confirm-no").click();
  await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(true));
}
