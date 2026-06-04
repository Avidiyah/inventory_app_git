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
import { formatError } from "../format.js";
import { applyRoleVisibility, canAccessPage, showPage } from "./nav.js";
import { loadUsers } from "./users.js";
import { setHistoryTab } from "./history.js";

const loginScreen = document.getElementById("login-screen");
const appRoot = document.getElementById("app-root");
const loginUsername = document.getElementById("login-username");
const loginPassword = document.getElementById("login-password");
const loginBtn = document.getElementById("login-btn");
const loginMessage = document.getElementById("login-message");
const logoutBtn = document.getElementById("logout-btn");
const authUserIndicator = document.getElementById("auth-user-indicator");

function showLoginScreen() {
  setCurrentUser(null);
  appRoot.hidden = true;
  loginScreen.hidden = false;
  loginPassword.value = "";
}

// Reveal the app for a logged-in user and run the initial loads they
// are allowed to see. The default landing page is Create Item for
// Owner/Admin and Saved Items for everyone else (Supervisor/Technician
// cannot create items).
function enterApp(user) {
  setCurrentUser(user);
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

  const landing =
    (user.role === "owner" || user.role === "admin") ? "create-item" : "saved-items";
  showPage(landing);
}

// Any 401 anywhere -> back to login. The login form's own catch still
// renders credential errors; this is idempotent if already showing.
setUnauthorizedHandler(showLoginScreen);

loginBtn.addEventListener("click", async () => {
  const username = loginUsername.value.trim();
  const password = loginPassword.value;
  setMessage(loginMessage, "", "");

  if (!username || !password) {
    setMessage(loginMessage, "Enter a username and password.", "error");
    return;
  }

  try {
    const user = await apiLogin({ username, password });
    loginUsername.value = "";
    loginPassword.value = "";
    enterApp(user);
  } catch (err) {
    if (err && err.status === 401) {
      setMessage(loginMessage, "Invalid username or password.", "error");
    } else if (err && err.status !== undefined) {
      setMessage(loginMessage, formatError(err.detail, "Login failed."), "error");
    } else {
      setMessage(loginMessage, "Could not connect to the server.", "error");
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
