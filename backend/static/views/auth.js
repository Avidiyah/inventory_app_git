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
import { setCurrentUser } from "../state.js";
import { setMessage } from "../dom.js";
import { friendlyError } from "../format.js";
import { applyRoleVisibility, canAccessPage, showPage } from "./nav.js";
import { loadUsers } from "./users.js";
import { setHistoryTab } from "./history.js";
import { resetBatch } from "./transactions.js";

const loginScreen = document.getElementById("login-screen");
const appRoot = document.getElementById("app-root");
const loginUsername = document.getElementById("login-username");
const loginPassword = document.getElementById("login-password");
const loginBtn = document.getElementById("login-btn");
const loginRemember = document.getElementById("login-remember");
const loginMessage = document.getElementById("login-message");
const logoutBtn = document.getElementById("logout-btn");
const authUserIndicator = document.getElementById("auth-user-indicator");

function showLoginScreen() {
  setCurrentUser(null);
  resetBatch(); // drop any in-progress work-order batch on logout/expiry
  appRoot.hidden = true;
  loginScreen.hidden = false;
  loginPassword.value = "";
}

// Reveal the app for a logged-in user and run the initial loads they
// are allowed to see. Every role lands on the Transaction page, which
// opens on the work-order gate, so the first action after sign-in is to
// start a work order and scan -- the core job for the whole crew
// (see docs/current-state.md).
function enterApp(user) {
  setCurrentUser(user);
  resetBatch(); // start every session at the work-order gate
  loginScreen.hidden = true;
  appRoot.hidden = false;
  authUserIndicator.textContent = `${user.username} (${user.role})`;
  applyRoleVisibility(user.role);

  // History keeps its "All" sub-tab primed (and the user dropdown
  // populated via loadUsers) only for roles that can reach those pages.
  if (canAccessPage(user.role, "history")) {
    setHistoryTab("all");
  }
  if (canAccessPage(user.role, "saved-users")) {
    loadUsers();
  }

  showPage("transaction");
}

// Any 401 anywhere -> back to login. The login form's own catch still
// renders credential errors; this is idempotent if already showing.
setUnauthorizedHandler(showLoginScreen);

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
    enterApp(user);
  } catch (err) {
    if (err && err.status === 401) {
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

logoutBtn.addEventListener("click", async () => {
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
    enterApp(user);
  } catch {
    // apiMe's 401 already triggered the unauthorized handler, but show
    // the login screen explicitly so any non-401 failure lands here too.
    showLoginScreen();
  }
}
