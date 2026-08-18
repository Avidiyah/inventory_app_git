// View: authentication gate (login screen, logout, post-login boot).
//
// Layer: views. Owns the #login-screen overlay and the logout control,
// and is the entry point the composition root calls on startup
// (`initAuth`). Responsibilities:
//
// 1. On boot, ask `/auth/me`. A valid session -> reveal the app, apply
//    role visibility, and run the role-appropriate initial loads. A 401
//    -> show the login screen.
// 2. Login submit -> `apiLogin`, then the same reveal-and-boot path.
// 3. Logout -> `apiLogout`, then back to the login screen.
// 4. Register the global 401 handler so an expired session anywhere in
//    the app returns the user to the login screen.

import { apiLogin, apiLogout, apiMe, setUnauthorizedHandler } from "../api.js";
import { connectRealtime, disconnectRealtime } from "../realtime.js";
import { setCurrentUser } from "../state.js";
import { setMessage } from "../dom.js";
import { friendlyError, formatUserName } from "../format.js";
import { applyRoleVisibility, canAccessPage, landingPageForRole, showPage } from "./nav.js";
import { loadUsers } from "./users.js";
import { setHistoryTab } from "./history.js";
import { resetBatch, tryResumeBatch } from "./transactions.js";
import { resetToolsView } from "./tools.js";
import { initPushForUser, resetPushView, unsubscribeThisDevice } from "./push.js";

const loginScreen = document.getElementById("login-screen");
const appRoot = document.getElementById("app-root");
const loginUsername = document.getElementById("login-username");
const loginPassword = document.getElementById("login-password");
const loginPasswordToggle = document.getElementById("login-password-toggle");
const loginBtn = document.getElementById("login-btn");
const loginRemember = document.getElementById("login-remember");
const loginMessage = document.getElementById("login-message");
const logoutBtn = document.getElementById("logout-btn");
const authUserIndicator = document.getElementById("auth-user-indicator");

// Toggle the password field between masked and plain text, and keep the
// toggle button's label/aria state in sync.
function setPasswordVisible(visible) {
  loginPassword.type = visible ? "text" : "password";
  if (loginPasswordToggle) {
    loginPasswordToggle.textContent = visible ? "Hide" : "Show";
    loginPasswordToggle.setAttribute("aria-pressed", visible ? "true" : "false");
    loginPasswordToggle.setAttribute("aria-label", visible ? "Hide password" : "Show password");
  }
}

// `expired` is passed by the global 401 handler. It only reads as a mid-batch
// timeout when the app was actually open -- a 401 during the initial boot check
// (apiMe) is just "not signed in yet", not an expiry, and must stay quiet.
function showLoginScreen({ expired = false } = {}) {
  disconnectRealtime();
  const wasInApp = !appRoot.hidden;
  setCurrentUser(null);
  resetToolsView();
  resetPushView();
  // On a timeout, keep the batch snapshot so a re-login by the same operator
  // can resume the work order (see enterApp). A deliberate logout clears it.
  resetBatch({ keepSaved: expired });
  appRoot.hidden = true;
  loginScreen.hidden = false;
  loginPassword.value = "";
  setPasswordVisible(false);
  if (expired && wasInApp) {
    // Reassure the operator their committed scans aren't lost (already in the
    // work order's history), and that signing back in resumes the batch.
    setMessage(loginMessage, "Your session timed out — any scans you already saved are safe in the work order's history. Sign in to pick up where you left off.", "");
  } else {
    setMessage(loginMessage, "", "");
  }
  loginUsername.focus();
}

// Reveal the app for a logged-in user and run the initial loads they
// are allowed to see. The landing page is role-specific (see
// landingPageForRole in nav.js): technicians open on Transaction and its
// work-order gate so their first action is to start a work order and scan,
// supervisors open on Work Orders, admins/owners on History.
//
// A resumed batch overrides that -- the operator was mid-scan when the
// session dropped, so drop them straight back on Transaction regardless
// of role (see docs/current-state.md).
//
// `resume: true` is passed from the boot-check path (initAuth, a still-valid
// session cookie after a reload/tab-eviction/phone-sleep) and from an explicit
// login submit. Either way the actual resume is gated by tryResumeBatch, which
// only proceeds when a snapshot survived (preserved on a timeout, cleared on a
// deliberate logout) AND the re-authenticating user owns it AND the work order
// is still active -- so a clean logout, a different user, or a stale WO all
// fall through to a fresh gate.
async function enterApp(user, { resume = false } = {}) {
  setCurrentUser(user);
  const resumed = resume && await tryResumeBatch(user.id);
  if (!resumed) {
    resetBatch(); // start every session at the work-order gate
  }
  loginScreen.hidden = true;
  appRoot.hidden = false;
  authUserIndicator.textContent = `${formatUserName(user)} (${user.role})`;
  applyRoleVisibility(user.role);

  // History keeps its "All" sub-tab primed (and the user dropdown
  // populated via loadUsers) only for roles that can reach those pages.
  if (canAccessPage(user.role, "history")) {
    setHistoryTab("all");
  }
  if (canAccessPage(user.role, "saved-users")) {
    loadUsers();
  }

  showPage(resumed ? "transaction" : landingPageForRole(user.role));
  connectRealtime();

  // Not awaited: a push subscription is not required for the app to be
  // usable, and iOS can take a moment over the service-worker
  // registration. Re-binds this device's endpoint to the user who just
  // logged in, which is what keeps a shared phone from delivering the
  // previous account's notifications.
  initPushForUser();
}

// Any 401 anywhere -> back to login. The login form's own catch still
// renders credential errors; this is idempotent if already showing. The
// `expired` flag turns on the reassurance copy, but only when the app was
// actually open (see showLoginScreen).
setUnauthorizedHandler(() => showLoginScreen({ expired: true }));

loginBtn.addEventListener("click", async () => {
  const username = loginUsername.value.trim();
  const password = loginPassword.value;
  const remember = loginRemember.checked;
  setMessage(loginMessage, "", "");

  if (!username || !password) {
    setMessage(loginMessage, "Enter a username and password.", "error");
    return;
  }

  try {
    const user = await apiLogin({ username, password, remember });
    loginUsername.value = "";
    loginPassword.value = "";
    // resume: true so a re-login after a timeout picks the work order back up;
    // tryResumeBatch no-ops for a clean logout / different user / stale WO.
    await enterApp(user, { resume: true });
  } catch (err) {
    if (err && err.status === 429) {
      // Throttled after repeated failures. The backend's detail already
      // names the wait, and it is more useful than the generic copy --
      // show it verbatim rather than a credential error, which would
      // read as "wrong password" and prompt another immediate attempt.
      setMessage(loginMessage, friendlyError(err, "Too many sign-in attempts. Wait a moment and try again."), "error");
    } else if (err && err.status === 401) {
      setMessage(loginMessage, "That sign-in did not work. Check the username and password, then try again.", "error");
    } else {
      setMessage(loginMessage, friendlyError(err, "Sign in failed."), "error");
    }
  }
});

// Submit on Enter from either field.
[loginUsername, loginPassword].forEach(input => {
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") loginBtn.click();
  });
});

if (loginPasswordToggle) {
  loginPasswordToggle.addEventListener("click", () => {
    setPasswordVisible(loginPassword.type === "password");
  });
}

logoutBtn.addEventListener("click", async () => {
  // Before `apiLogout`, because dropping the subscription is an
  // authenticated call -- after the session is gone the server would
  // refuse it and the device would keep receiving.
  await unsubscribeThisDevice();
  try {
    await apiLogout();
  } catch {
    // Even if the call fails (e.g. already expired), the local session
    // is gone -- fall through to the login screen.
  }
  showLoginScreen();
});

// Boot entry point, called by main.js. Decides login-screen vs app.
export async function initAuth() {
  try {
    const user = await apiMe();
    await enterApp(user, { resume: true });
  } catch {
    // apiMe's 401 already triggered the unauthorized handler, but show
    // the login screen explicitly so any non-401 failure lands here too.
    showLoginScreen();
  }
}
