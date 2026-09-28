// views/thresholdPrompt.js
//
// Layer: views. The low-stock threshold dialog opened from the Find Item
// row Actions menu. Owns the save call so the dialog stays open on a
// server error; resolves the updated item, or null on Cancel / Esc /
// backdrop.

import { apiSetLowStockThreshold } from "../api.js";
import { friendlyError } from "../format.js";
import { setMessage } from "../dom.js";

const overlay = document.getElementById("threshold-overlay");
const title = document.getElementById("threshold-title");
const input = document.getElementById("threshold-input");
const message = document.getElementById("threshold-message");
const saveBtn = document.getElementById("threshold-save");
const cancelBtn = document.getElementById("threshold-cancel");

export function promptThreshold(item) {
  return new Promise((resolve) => {
    if (!overlay) {
      resolve(null);
      return;
    }
    const previouslyFocused = document.activeElement;
    const focusables = [input, saveBtn, cancelBtn];
    title.textContent = `Low-stock threshold for "${item.name}"`;
    input.value = String(item.low_stock_threshold ?? "");
    setMessage(message, "", "");
    saveBtn.disabled = false;
    overlay.hidden = false;
    input.focus();
    input.select();

    function done(value) {
      overlay.hidden = true;
      saveBtn.removeEventListener("click", submit);
      cancelBtn.removeEventListener("click", onCancel);
      overlay.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKey);
      if (previouslyFocused && typeof previouslyFocused.focus === "function") {
        try { previouslyFocused.focus(); } catch (_err) { /* element removed */ }
      }
      resolve(value);
    }
    async function submit() {
      const raw = input.value.trim();
      const value = Number(raw);
      if (!/^\d+$/.test(raw) || value < 1) {
        setMessage(message, "Threshold must be a whole number of at least 1.", "error");
        return;
      }
      saveBtn.disabled = true;
      try {
        done(await apiSetLowStockThreshold(item.id, value));
      } catch (err) {
        saveBtn.disabled = false;
        setMessage(message, friendlyError(err, "Could not save that threshold."), "error");
      }
    }
    function onCancel() { done(null); }
    function onBackdrop(event) { if (event.target === overlay) done(null); }
    function onKey(event) {
      if (event.key === "Escape") { done(null); return; }
      if (event.key === "Enter" && event.target === input) {
        event.preventDefault();
        submit();
        return;
      }
      if (event.key === "Tab") {
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }

    saveBtn.addEventListener("click", submit);
    cancelBtn.addEventListener("click", onCancel);
    overlay.addEventListener("click", onBackdrop);
    document.addEventListener("keydown", onKey);
  });
}
