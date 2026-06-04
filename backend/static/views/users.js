// View: users list, create-user form, and the user dropdowns
// embedded in the transaction form and the history filter.
//
// Layer: views. `loadUsers()` is the single public entry point
// -- it refreshes the cache, repaints the users table, and
// repopulates every `<select>` that lists users via
// `populateUserSelects()`. Called by `main.js` on boot and by
// this view itself after a create/delete.
//
// The select-population path also toggles the transaction form's
// save button: if the user list goes empty, the form is locked
// with a hint message until at least one user exists.

import { getUsers, setUsers } from "../state.js";
import { apiListUsers, apiCreateUser, apiDeleteUser } from "../api.js";
import { escapeHtml, formatError } from "../format.js";
import { setMessage } from "../dom.js";

const createUserBtn = document.getElementById("create-user-btn");
const createUserMessage = document.getElementById("create-user-message");
const usersTbody = document.getElementById("users-tbody");
const usernameInput = document.getElementById("username");
const transactionUser = document.getElementById("transaction-user");
const historyUserSelect = document.getElementById("history-user-select");
const transactionSection = document.getElementById("transaction-section");
const transactionMessage = document.getElementById("transaction-message");
const saveTransactionBtn = document.getElementById("save-transaction-btn");

export async function loadUsers() {
  try {
    const users = await apiListUsers();
    setUsers(users);

    usersTbody.innerHTML = "";
    users.forEach(user => {
      const row = document.createElement("tr");
      const createdAt = new Date(user.created_at).toLocaleString();
      row.innerHTML = `
        <td>${escapeHtml(user.username)}</td>
        <td>${escapeHtml(createdAt)}</td>
        <td>
          <div class="row-actions">
            <button class="delete-user-btn" data-id="${user.id}" data-name="${escapeHtml(user.username)}">🗑️</button>
          </div>
        </td>
      `;
      usersTbody.appendChild(row);
    });

    populateUserSelects();
  } catch (error) {
    console.error("Failed to load users:", error);
  }
}

export function populateUserSelects() {
  populateSelect(transactionUser);
  populateSelect(historyUserSelect);

  if (!transactionSection.hidden) {
    if (getUsers().length === 0) {
      saveTransactionBtn.disabled = true;
      setMessage(transactionMessage, "Create a user first to record transactions.", "error");
    } else if (transactionMessage.textContent === "Create a user first to record transactions.") {
      saveTransactionBtn.disabled = false;
      setMessage(transactionMessage, "", "");
    }
  }
}

function populateSelect(selectEl) {
  const previousValue = selectEl.value;
  selectEl.innerHTML = '<option value="" disabled selected>-- Select user --</option>';
  getUsers().forEach(user => {
    const option = document.createElement("option");
    option.value = user.id;
    option.textContent = user.username;
    selectEl.appendChild(option);
  });
  if (previousValue && getUsers().some(u => u.id === previousValue)) {
    selectEl.value = previousValue;
  }
}

createUserBtn.addEventListener("click", async () => {
  const username = usernameInput.value.trim();
  setMessage(createUserMessage, "", "");

  if (!username) {
    setMessage(createUserMessage, "Username is required.", "error");
    return;
  }

  try {
    const data = await apiCreateUser({ username });
    setMessage(createUserMessage, `User "${data.username}" created successfully.`, "success");
    usernameInput.value = "";
    loadUsers();
  } catch (err) {
    if (err && err.status !== undefined) {
      setMessage(createUserMessage, formatError(err.detail, "An error occurred."), "error");
    } else {
      setMessage(createUserMessage, "Could not connect to the server.", "error");
    }
  }
});

usersTbody.addEventListener("click", async (event) => {
  const target = event.target;
  if (!target.classList.contains("delete-user-btn")) return;

  const userId = target.dataset.id;
  const userName = target.dataset.name;

  if (!confirm(`Are you sure you want to delete user "${userName}"?`)) return;

  try {
    await apiDeleteUser(userId);
    loadUsers();
  } catch (err) {
    alert(err && err.detail ? err.detail : "Failed to delete user.");
  }
});
