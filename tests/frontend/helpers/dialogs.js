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

// --- the Users page's three prompt overlays (dom.js) ------------------------
//
// Same contract as `answerConfirm`: wait for the overlay, fill it, click, wait
// for it to close -- so the caller's `await` on the view's own promise resolves
// next. `null` cancels. P1's `unit/dom.prompts.test.js` owns each prompt's own
// validation and focus behaviour; these only drive them.

const overlay = (id) => document.getElementById(id);

async function shown(id) {
  await vi.waitFor(() => expect(overlay(id).hidden).toBe(false));
}

async function closed(id) {
  await vi.waitFor(() => expect(overlay(id).hidden).toBe(true));
}

export async function answerPasswordReset(password) {
  await shown("pw-reset-overlay");
  if (password === null) {
    document.getElementById("pw-reset-cancel").click();
  } else {
    document.getElementById("pw-reset-new").value = password;
    document.getElementById("pw-reset-confirm").value = password;
    document.getElementById("pw-reset-save").click();
  }
  await closed("pw-reset-overlay");
}

// Fields left out of `details` keep what the prompt prefilled, so a test that
// only changes the username says so and nothing else.
export async function answerUserName(details) {
  await shown("user-name-overlay");
  if (details === null) {
    document.getElementById("user-name-cancel").click();
  } else {
    const set = (id, value) => {
      if (value !== undefined) document.getElementById(id).value = value;
    };
    set("user-name-first", details.first);
    set("user-name-last", details.last);
    set("user-name-username", details.username);
    document.getElementById("user-name-save").click();
  }
  await closed("user-name-overlay");
}

export async function answerUserRole(role) {
  await shown("user-role-overlay");
  if (role === null) {
    document.getElementById("user-role-cancel").click();
  } else {
    const select = document.getElementById("user-role-select");
    select.value = role;
    select.dispatchEvent(new Event("change"));
    document.getElementById("user-role-save").click();
  }
  await closed("user-role-overlay");
}
