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
const confirmQtyWrap = document.getElementById("scan-confirm-qty");
const confirmQtyInput = document.getElementById("scan-confirm-qty-input");
const confirmQtyDec = document.getElementById("scan-confirm-qty-dec");
const confirmQtyInc = document.getElementById("scan-confirm-qty-inc");

// `options.quantity` (a positive number) turns this into a quantity-confirm
// (#11). `options.dismissOnly` reuses the same accessible modal as a one-button
// message. `confirmText` / `cancelText` let a caller name a specific action
// without changing the boolean resolve contract. Callers that omit all options
// get the plain yes/no behavior unchanged.
export function confirmDialog(
  message,
  { quantity = null, dismissOnly = false, confirmText = null, cancelText = null } = {}
) {
  // `qtyRequested` fixes the resolve contract (a number on Yes, false on No)
  // whenever the caller asked for a quantity; `wantsQty` additionally requires
  // the stepper markup to be present before showing/reading it. Keeping them
  // separate means a caller that requests a quantity never gets a bare `true`.
  const qtyRequested = quantity !== null && quantity !== undefined;
  const wantsQty = qtyRequested && confirmQtyWrap && confirmQtyInput;

  return new Promise((resolve) => {
    if (!confirmOverlay) {
      // No modal in the DOM -> fall back to instant confirm. In quantity mode,
      // approve the requested amount so the commit still proceeds.
      resolve(qtyRequested ? Number(quantity) : true);
      return;
    }
    // Remember focus so we can restore it on close (a11y).
    const previouslyFocused = document.activeElement;
    const originalYesText = confirmYesBtn?.textContent;
    const originalNoText = confirmNoBtn?.textContent;
    const originalNoHidden = confirmNoBtn?.hidden;
    if (confirmYesBtn) {
      if (confirmText) confirmYesBtn.textContent = confirmText;
      else if (dismissOnly) confirmYesBtn.textContent = "Close";
    }
    if (confirmNoBtn) {
      if (cancelText) confirmNoBtn.textContent = cancelText;
      confirmNoBtn.hidden = dismissOnly;
    }
    const focusables = (wantsQty
      ? [confirmQtyDec, confirmQtyInput, confirmQtyInc, confirmYesBtn, confirmNoBtn]
      : [confirmYesBtn, dismissOnly ? null : confirmNoBtn]).filter(Boolean);

    confirmTitle.textContent = message; // textContent: item name is untrusted
    if (confirmQtyWrap) confirmQtyWrap.hidden = !wantsQty;
    if (wantsQty) confirmQtyInput.value = String(quantity);
    confirmOverlay.hidden = false;
    // Focus Yes, never the number input -- focusing it pops the mobile keyboard,
    // which the +/- taps exist to avoid.
    if (confirmYesBtn) confirmYesBtn.focus();

    // Stepper (quantity mode): +/- nudge by 1 and never drop below 1; typing
    // still allows any positive amount.
    function currentQty() {
      const n = parseFloat(confirmQtyInput.value);
      return Number.isFinite(n) ? n : Number(quantity);
    }
    function stepBy(delta) { confirmQtyInput.value = String(Math.max(1, currentQty() + delta)); }
    function onDec() { stepBy(-1); }
    function onInc() { stepBy(1); }

    function cleanup() {
      if (confirmYesBtn) confirmYesBtn.removeEventListener("click", onYes);
      if (confirmNoBtn) confirmNoBtn.removeEventListener("click", onNo);
      confirmOverlay.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKey);
      if (wantsQty) {
        if (confirmQtyDec) confirmQtyDec.removeEventListener("click", onDec);
        if (confirmQtyInc) confirmQtyInc.removeEventListener("click", onInc);
      }
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
      if (confirmQtyWrap) confirmQtyWrap.hidden = true; // reset for generic reuse
      if (confirmYesBtn && originalYesText !== undefined) {
        confirmYesBtn.textContent = originalYesText;
      }
      if (confirmNoBtn) {
        if (originalNoText !== undefined) confirmNoBtn.textContent = originalNoText;
        confirmNoBtn.hidden = originalNoHidden;
      }
      cleanup();
      restoreFocus();
      if (!qtyRequested) { resolve(ok); return; }
      if (!ok) { resolve(false); return; }
      // Never resolve a non-positive count; fall back to the requested amount.
      const n = wantsQty ? currentQty() : Number(quantity);
      resolve(Number.isFinite(n) && n > 0 ? n : Number(quantity));
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
    if (wantsQty) {
      if (confirmQtyDec) confirmQtyDec.addEventListener("click", onDec);
      if (confirmQtyInc) confirmQtyInc.addEventListener("click", onInc);
    }
  });
}

// A one-button informational prompt. Closing by button, Esc, or backdrop all
// resolve the same way so callers can perform a single follow-up action.
export async function messageDialog(message) {
  await confirmDialog(message, { dismissOnly: true });
}

// --- Archived-record reuse confirm/retry ------------------------------
// Runs `action(override)` -- an async API call that takes a backend "confirm
// the archived record" flag (`override_archived` for a barcode held by an
// archived item). The first attempt passes false; if the backend answers 409 (the
// record exists only in an archived/deleted form, not a live one) it shows the
// confirm modal with `message` and, on Yes, retries once with the flag true so
// the service frees / restores that archived holder and proceeds.
//
// Returns the action's resolved value on success. Throws `{ cancelled: true }`
// if the user declines (so callers can clear their status line without
// surfacing an error), and rethrows any other error unchanged so existing
// `friendlyError` handling still applies (including a live-record 400 duplicate).
export async function confirmArchivedReuse(action, message = "Barcode exists but is archived. Continue?") {
  try {
    return await action(false);
  } catch (err) {
    if (!(err && err.status === 409)) throw err;
    const ok = await confirmDialog(message);
    if (!ok) throw { cancelled: true };
    return await action(true);
  }
}

// --- Password-reset prompt --------------------------------------------
// Drives the app-level `#pw-reset-overlay` (shell-tail.html): a "new" +
// "confirm" password pair with a show/hide toggle and inline validation.
// Replaces the native `prompt()` the users view used for password resets, so
// a typo (which the old single-field flow would have accepted and silently
// locked the user out with) is caught before the reset call. Returns a
// Promise that resolves the entered password on Save, or `null` on Cancel /
// Esc / backdrop. Never resolves an invalid value -- Save re-prompts inline
// until the pair is >= MIN_PASSWORD_LENGTH and matches. Mirrors
// `confirmDialog`'s focus-trap / focus-restore behavior.
const MIN_PASSWORD_LENGTH = 4;
const pwResetOverlay = document.getElementById("pw-reset-overlay");
const pwResetTitle = document.getElementById("pw-reset-title");
const pwResetNew = document.getElementById("pw-reset-new");
const pwResetConfirm = document.getElementById("pw-reset-confirm");
const pwResetToggle = document.getElementById("pw-reset-toggle");
const pwResetMessage = document.getElementById("pw-reset-message");
const pwResetSaveBtn = document.getElementById("pw-reset-save");
const pwResetCancelBtn = document.getElementById("pw-reset-cancel");

function setPwResetVisible(visible) {
  if (!pwResetNew) return;
  pwResetNew.type = visible ? "text" : "password";
  if (pwResetToggle) {
    pwResetToggle.textContent = visible ? "Hide" : "Show";
    pwResetToggle.setAttribute("aria-pressed", visible ? "true" : "false");
    pwResetToggle.setAttribute("aria-label", visible ? "Hide password" : "Show password");
  }
}

export function promptPasswordReset(username) {
  return new Promise((resolve) => {
    if (!pwResetOverlay) {
      resolve(null); // no modal in the DOM -> cannot prompt
      return;
    }
    const previouslyFocused = document.activeElement;
    const focusables = [pwResetNew, pwResetConfirm, pwResetToggle, pwResetSaveBtn, pwResetCancelBtn].filter(Boolean);

    pwResetTitle.textContent = `New password for "${username}"`;
    pwResetNew.value = "";
    pwResetConfirm.value = "";
    setPwResetVisible(false);
    setMessage(pwResetMessage, "", "");
    pwResetOverlay.hidden = false;
    pwResetNew.focus();

    function cleanup() {
      pwResetSaveBtn.removeEventListener("click", onSave);
      pwResetCancelBtn.removeEventListener("click", onCancel);
      if (pwResetToggle) pwResetToggle.removeEventListener("click", onToggle);
      pwResetOverlay.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKey);
    }
    function restoreFocus() {
      const el = previouslyFocused;
      if (!el || typeof el.focus !== "function") return;
      const tag = (el.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      try { el.focus(); } catch (_err) { /* element gone; nothing actionable */ }
    }
    function done(value) {
      pwResetOverlay.hidden = true;
      // Clear the fields so a plaintext password isn't left sitting in the DOM.
      pwResetNew.value = "";
      pwResetConfirm.value = "";
      setPwResetVisible(false);
      cleanup();
      restoreFocus();
      resolve(value);
    }
    function submit() {
      const pw = pwResetNew.value;
      if (pw.length < MIN_PASSWORD_LENGTH) {
        setMessage(pwResetMessage, `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`, "error");
        return;
      }
      if (pw !== pwResetConfirm.value) {
        setMessage(pwResetMessage, "Passwords do not match.", "error");
        return;
      }
      done(pw);
    }
    function onSave() { submit(); }
    function onCancel() { done(null); }
    function onToggle() { setPwResetVisible(pwResetNew.type === "password"); }
    function onBackdrop(event) { if (event.target === pwResetOverlay) done(null); }
    function onKey(event) {
      if (event.key === "Escape") { done(null); return; }
      // Enter from either password field submits (the Save button submits on
      // its own via the browser's default button activation).
      if (event.key === "Enter" && (event.target === pwResetNew || event.target === pwResetConfirm)) {
        event.preventDefault();
        submit();
        return;
      }
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

    pwResetSaveBtn.addEventListener("click", onSave);
    pwResetCancelBtn.addEventListener("click", onCancel);
    if (pwResetToggle) pwResetToggle.addEventListener("click", onToggle);
    pwResetOverlay.addEventListener("click", onBackdrop);
    document.addEventListener("keydown", onKey);
  });
}

// Explicit first/last-name (and optionally username) editor used by the Users
// page. Legacy accounts have NULL names after migration, so this is the
// remediation path that avoids inventing identity from a login username.
//
// Pass `{ allowUsername: true }` to also expose the login username; the
// resolved object then carries `username`, and omits it otherwise so callers
// can leave the login name untouched.
const userNameOverlay = document.getElementById("user-name-overlay");
const userNameTitle = document.getElementById("user-name-title");
const userNameFirst = document.getElementById("user-name-first");
const userNameLast = document.getElementById("user-name-last");
const userNameUsername = document.getElementById("user-name-username");
const userNameUsernameLabel = document.getElementById("user-name-username-label");
const userNameUsernameHelp = document.getElementById("user-name-username-help");
const userNameMessage = document.getElementById("user-name-message");
const userNameSave = document.getElementById("user-name-save");
const userNameCancel = document.getElementById("user-name-cancel");

export function promptUserName(user, { allowUsername = false } = {}) {
  return new Promise((resolve) => {
    if (!userNameOverlay) {
      resolve(null);
      return;
    }
    const editUsername = allowUsername && Boolean(userNameUsername);
    const previouslyFocused = document.activeElement;
    const focusables = [userNameFirst, userNameLast];
    if (editUsername) focusables.push(userNameUsername);
    focusables.push(userNameSave, userNameCancel);
    userNameTitle.textContent = editUsername
      ? `Edit "${user.username}"`
      : `Edit name for "${user.username}"`;
    userNameFirst.value = user.first_name || "";
    userNameLast.value = user.last_name || "";
    if (userNameUsername) {
      userNameUsername.value = user.username || "";
      userNameUsername.hidden = !editUsername;
      if (userNameUsernameLabel) userNameUsernameLabel.hidden = !editUsername;
      if (userNameUsernameHelp) userNameUsernameHelp.hidden = !editUsername;
    }
    setMessage(userNameMessage, "", "");
    userNameOverlay.hidden = false;
    userNameFirst.focus();

    function cleanup() {
      userNameSave.removeEventListener("click", onSave);
      userNameCancel.removeEventListener("click", onCancel);
      userNameOverlay.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKey);
    }
    function done(value) {
      userNameOverlay.hidden = true;
      cleanup();
      if (previouslyFocused && typeof previouslyFocused.focus === "function") {
        try { previouslyFocused.focus(); } catch (_err) { /* element removed */ }
      }
      resolve(value);
    }
    function submit() {
      const firstName = userNameFirst.value.trim();
      const lastName = userNameLast.value.trim();
      if (!firstName || !lastName) {
        setMessage(userNameMessage, "First name and last name are required.", "error");
        return;
      }
      if (!editUsername) {
        done({ firstName, lastName });
        return;
      }
      const username = userNameUsername.value.trim();
      if (!username) {
        setMessage(userNameMessage, "Username is required.", "error");
        return;
      }
      done({ firstName, lastName, username });
    }
    function onSave() { submit(); }
    function onCancel() { done(null); }
    function onBackdrop(event) { if (event.target === userNameOverlay) done(null); }
    function onKey(event) {
      if (event.key === "Escape") { done(null); return; }
      if (event.key === "Enter" && focusables.includes(event.target) && event.target.tagName === "INPUT") {
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

    userNameSave.addEventListener("click", onSave);
    userNameCancel.addEventListener("click", onCancel);
    userNameOverlay.addEventListener("click", onBackdrop);
    document.addEventListener("keydown", onKey);
  });
}

// Role editor used by the Users page (Admin+ only). `options` is the list of
// roles the caller is allowed to assign, most-senior first, as
// `{ value, label, description }` -- built by the view so this module stays
// free of the role vocabulary. Resolves the chosen role, or null on
// Cancel / Esc / backdrop / no assignable roles / unchanged selection.
const userRoleOverlay = document.getElementById("user-role-overlay");
const userRoleTitle = document.getElementById("user-role-title");
const userRoleSelect = document.getElementById("user-role-select");
// Distinct from the create-user form's own #user-role-help.
const userRoleHelp = document.getElementById("user-role-modal-help");
const userRoleMessage = document.getElementById("user-role-message");
const userRoleSave = document.getElementById("user-role-save");
const userRoleCancel = document.getElementById("user-role-cancel");

export function promptUserRole(user, options = []) {
  return new Promise((resolve) => {
    if (!userRoleOverlay || !options.length) {
      resolve(null);
      return;
    }
    const previouslyFocused = document.activeElement;
    const focusables = [userRoleSelect, userRoleSave, userRoleCancel];

    userRoleTitle.textContent = `Change role for "${user.username}"`;
    userRoleSelect.innerHTML = "";
    options.forEach(({ value, label }) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      userRoleSelect.appendChild(option);
    });
    // Start on the role the user already holds when it is assignable, so
    // Save is a deliberate change rather than a default one.
    if (options.some(o => o.value === user.role)) userRoleSelect.value = user.role;
    setMessage(userRoleMessage, "", "");
    updateHelp();
    userRoleOverlay.hidden = false;
    userRoleSelect.focus();

    function updateHelp() {
      const chosen = options.find(o => o.value === userRoleSelect.value);
      userRoleHelp.textContent = chosen ? chosen.description || "" : "";
    }
    function cleanup() {
      userRoleSave.removeEventListener("click", onSave);
      userRoleCancel.removeEventListener("click", onCancel);
      userRoleSelect.removeEventListener("change", updateHelp);
      userRoleOverlay.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKey);
    }
    function done(value) {
      userRoleOverlay.hidden = true;
      cleanup();
      if (previouslyFocused && typeof previouslyFocused.focus === "function") {
        try { previouslyFocused.focus(); } catch (_err) { /* element removed */ }
      }
      resolve(value);
    }
    function submit() {
      const role = userRoleSelect.value;
      if (!role) {
        setMessage(userRoleMessage, "Select a role.", "error");
        return;
      }
      // Saving the current role would revoke the user's sessions for no
      // change, so treat it as a cancel.
      done(role === user.role ? null : role);
    }
    function onSave() { submit(); }
    function onCancel() { done(null); }
    function onBackdrop(event) { if (event.target === userRoleOverlay) done(null); }
    function onKey(event) {
      if (event.key === "Escape") { done(null); return; }
      if (event.key === "Enter" && event.target === userRoleSelect) {
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

    userRoleSave.addEventListener("click", onSave);
    userRoleCancel.addEventListener("click", onCancel);
    userRoleSelect.addEventListener("change", updateHelp);
    userRoleOverlay.addEventListener("click", onBackdrop);
    document.addEventListener("keydown", onKey);
  });
}
