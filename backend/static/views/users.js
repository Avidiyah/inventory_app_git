// View: users list, create-user form, and the History "by user"
// dropdown.
//
// Layer: views. `loadUsers()` refreshes the cache, repaints the users
// table (with a Role column and role-gated row actions), and
// repopulates the History user filter via `populateUserSelects()`.
//
// Authorization is mirrored from the backend for UX only: the create
// form offers just the roles the current user may assign, and each row
// shows Reset Password / Delete only when the current user outranks
// that row's role. The backend re-checks everything.

import { getUsers, setUsers, getRole } from "../state.js";
import {
  apiListUsers,
  apiCreateUser,
  apiDeleteUser,
  apiResetPassword,
} from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { setMessage } from "../dom.js";
import { assignableRoles, canManage } from "../roles.js";

const createUserBtn = document.getElementById("create-user-btn");
const createUserMessage = document.getElementById("create-user-message");
const usersTbody = document.getElementById("users-tbody");
const usernameInput = document.getElementById("username");
const userRoleSelect = document.getElementById("user-role");
const userPasswordInput = document.getElementById("user-password");
const userRoleHelp = document.getElementById("user-role-help");
const historyUserSelect = document.getElementById("history-user-select");

// Plain-language role descriptions shown under the Role select so the
// person creating an account understands what each role can do.
const ROLE_DESCRIPTIONS = {
  technician: "Scan items and do basic work.",
  supervisor: "Record stock, edit notes, view history.",
  admin: "Manage items and corrections.",
  owner: "Top-level setup.",
};

function updateRoleHelp() {
  if (!userRoleHelp || !userRoleSelect) return;
  userRoleHelp.textContent = ROLE_DESCRIPTIONS[userRoleSelect.value] || "";
}

if (userRoleSelect) userRoleSelect.addEventListener("change", updateRoleHelp);

export async function loadUsers() {
  try {
    const users = await apiListUsers();
    setUsers(users);
    renderUsersTable();
    populateRoleSelect();
    populateUserSelects();
  } catch (error) {
    console.error("Failed to load users:", error);
  }
}

function renderUsersTable() {
  const actorRole = getRole();
  usersTbody.innerHTML = "";

  getUsers().forEach(user => {
    const row = document.createElement("tr");
    const createdAt = new Date(user.created_at).toLocaleString();
    // Actions appear only for rows the current user outranks; otherwise
    // the cell is an empty placeholder (hidden, not disabled).
    const actions = canManage(actorRole, user.role)
      ? `<div class="row-actions">
           <button class="reset-pw-btn secondary-btn" data-id="${user.id}" data-name="${escapeHtml(user.username)}">Reset Password</button>
           <button class="delete-user-btn" data-id="${user.id}" data-name="${escapeHtml(user.username)}">🗑️</button>
         </div>`
      : `<span class="empty">—</span>`;
    row.innerHTML = `
      <td>${escapeHtml(user.username)}</td>
      <td>${escapeHtml(user.role)}</td>
      <td>${escapeHtml(createdAt)}</td>
      <td>${actions}</td>
    `;
    usersTbody.appendChild(row);
  });
}

// Fill the create-user role dropdown with the roles the current user is
// allowed to assign (those ranked strictly below them).
function populateRoleSelect() {
  if (!userRoleSelect) return;
  const previous = userRoleSelect.value;
  userRoleSelect.innerHTML = "";
  assignableRoles(getRole()).forEach(role => {
    const option = document.createElement("option");
    option.value = role;
    option.textContent = role.charAt(0).toUpperCase() + role.slice(1);
    userRoleSelect.appendChild(option);
  });
  if (previous && [...userRoleSelect.options].some(o => o.value === previous)) {
    userRoleSelect.value = previous;
  }
  updateRoleHelp();
}

// Repopulate the History "by user" filter, preserving the current
// selection if that user still exists.
export function populateUserSelects() {
  const previousValue = historyUserSelect.value;
  historyUserSelect.innerHTML = '<option value="" disabled selected>-- Select user --</option>';
  getUsers().forEach(user => {
    const option = document.createElement("option");
    option.value = user.id;
    option.textContent = user.username;
    historyUserSelect.appendChild(option);
  });
  if (previousValue && getUsers().some(u => u.id === previousValue)) {
    historyUserSelect.value = previousValue;
  }
}

createUserBtn.addEventListener("click", async () => {
  const username = usernameInput.value.trim();
  const role = userRoleSelect ? userRoleSelect.value : "";
  const password = userPasswordInput.value;
  setMessage(createUserMessage, "", "");

  if (!username) {
    setMessage(createUserMessage, "Username is required.", "error");
    return;
  }
  if (!role) {
    setMessage(createUserMessage, "Select a role.", "error");
    return;
  }
  if (password.length < 4) {
    setMessage(createUserMessage, "Password must be at least 4 characters.", "error");
    return;
  }

  try {
    const data = await apiCreateUser({ username, password, role });
    setMessage(createUserMessage, `User "${data.username}" created as ${data.role}.`, "success");
    usernameInput.value = "";
    userPasswordInput.value = "";
    loadUsers();
  } catch (err) {
    setMessage(createUserMessage, friendlyError(err, "Could not create the user. Try again."), "error");
  }
});

usersTbody.addEventListener("click", async (event) => {
  const target = event.target;

  if (target.classList.contains("reset-pw-btn")) {
    const userId = target.dataset.id;
    const userName = target.dataset.name;
    const newPassword = prompt(`New password for "${userName}" (at least 4 characters):`);
    if (newPassword === null) return; // cancelled
    if (newPassword.length < 4) {
      alert("Password must be at least 4 characters.");
      return;
    }
    try {
      await apiResetPassword(userId, newPassword);
      alert(`Password reset for "${userName}".`);
    } catch (err) {
      alert(friendlyError(err, "Could not reset the password. Try again."));
    }
    return;
  }

  if (!target.classList.contains("delete-user-btn")) return;

  const userId = target.dataset.id;
  const userName = target.dataset.name;

  if (!confirm(`Are you sure you want to delete user "${userName}"?`)) return;

  try {
    await apiDeleteUser(userId);
    loadUsers();
  } catch (err) {
    alert(friendlyError(err, "Could not delete the user. Try again."));
  }
});
