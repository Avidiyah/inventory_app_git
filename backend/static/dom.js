// Foundation: small DOM helpers shared by views.
//
// Layer: foundation. Lives below the views so any number of them
// can write status messages or read note-editor inputs without
// duplicating selectors.

// Set a status message and CSS class on an arbitrary element.
// Passing an empty `text` clears the line; an empty `type` removes
// any styling so the element returns to a neutral state.
export function setMessage(element, text, type) {
  element.textContent = text || "";
  element.className = type || "";
}

// The notes editor builds rows containing a single `.note-value`
// input. Reading the raw string is centralised here so the editor
// view does not have to know the internal markup.
export function getNoteValueRaw(wrapper) {
  const el = wrapper.querySelector(".note-value");
  return el ? el.value : "";
}

// --- Shared confirmation modal ----------------------------------------
// Drives the app-level `#scan-confirm-overlay` (shell-tail.html): shows
// `message`, returns a Promise that resolves true (Yes) or false (No / Esc /
// backdrop). Used by the scan-and-go commit (views/transactions.js) and the
// mass-stage load action (views/massStage.js). The decoder/caller awaits the
// whole resolve chain, so there are never stacked dialogs.
const confirmOverlay = document.getElementById("scan-confirm-overlay");
const confirmTitle = document.getElementById("scan-confirm-title");
const confirmYesBtn = document.getElementById("scan-confirm-yes");
const confirmNoBtn = document.getElementById("scan-confirm-no");

export function confirmDialog(message) {
  return new Promise((resolve) => {
    if (!confirmOverlay) {
      resolve(true); // no modal in the DOM -> fall back to instant confirm
      return;
    }
    // Remember focus so we can restore it on close (a11y).
    const previouslyFocused = document.activeElement;
    const focusables = [confirmYesBtn, confirmNoBtn].filter(Boolean);

    confirmTitle.textContent = message; // textContent: item name is untrusted
    confirmOverlay.hidden = false;
    if (confirmYesBtn) confirmYesBtn.focus();

    function cleanup() {
      if (confirmYesBtn) confirmYesBtn.removeEventListener("click", onYes);
      if (confirmNoBtn) confirmNoBtn.removeEventListener("click", onNo);
      confirmOverlay.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKey);
    }
    function restoreFocus() {
      const el = previouslyFocused;
      if (!el || typeof el.focus !== "function") return;
      // Don't re-focus a text/number field -- that re-pops the mobile keyboard.
      const tag = (el.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      try { el.focus(); } catch (_err) { /* element gone; nothing actionable */ }
    }
    function done(ok) {
      confirmOverlay.hidden = true;
      cleanup();
      restoreFocus();
      resolve(ok);
    }
    function onYes() { done(true); }
    function onNo() { done(false); }
    function onBackdrop(event) { if (event.target === confirmOverlay) done(false); }
    function onKey(event) {
      if (event.key === "Escape") { done(false); return; }
      // Trap Tab focus within the dialog while it's open.
      if (event.key === "Tab" && focusables.length) {
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const active = document.activeElement;
        if (event.shiftKey && (active === first || !focusables.includes(active))) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && (active === last || !focusables.includes(active))) {
          event.preventDefault();
          first.focus();
        }
      }
    }

    if (confirmYesBtn) confirmYesBtn.addEventListener("click", onYes);
    if (confirmNoBtn) confirmNoBtn.addEventListener("click", onNo);
    confirmOverlay.addEventListener("click", onBackdrop);
    document.addEventListener("keydown", onKey);
  });
}

// --- Archived-barcode reuse confirm/retry -----------------------------
// Runs `action(override)` -- an async API call that takes the backend's
// `override_archived` flag. The first attempt passes false; if the backend
// answers 409 (the barcode is held only by an archived/deleted item, not a
// live one) it shows the standard confirm modal and, on Yes, retries once
// with override=true so the service frees that archived holder and proceeds.
//
// Returns the action's resolved value on success. Throws `{ cancelled: true }`
// if the user declines (so callers can clear their status line without
// surfacing an error), and rethrows any other error unchanged so existing
// `friendlyError` handling still applies (including a live-item 400 duplicate).
export async function confirmArchivedReuse(action) {
  try {
    return await action(false);
  } catch (err) {
    if (!(err && err.status === 409)) throw err;
    const ok = await confirmDialog("Barcode exists but is archived. Continue?");
    if (!ok) throw { cancelled: true };
    return await action(true);
  }
}
