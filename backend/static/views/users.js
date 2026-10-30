// View: users list, the Add user panel above it, and the History "by
// user" dropdown.
//
// Layer: views. `loadUsers()` refreshes the cache, repaints the users
// table (with a Role column and role-gated row actions), and
// repopulates the History user filter via `populateUserSelects()`.
//
// Authorization is mirrored from the backend for UX only: the create
// form offers just the roles the current user may assign, each row's
// action menu offers Reset Password / Archive only when the current user
// outranks that row's role, and Edit Role only for a TechFM OA or above
// acting on someone they outrank. Edit Details (name + login username)
// is offered for yourself or anyone you outrank. The backend re-checks
// everything.

import { getUsers, setUsers, getRole, getCurrentUser, setCurrentUser } from "../state.js";
import {
  apiListUsers,
  apiCreateUser,
  apiArchiveUser,
  apiRestoreUser,
  apiResetPassword,
  apiUpdateUserName,
  apiUpdateUserRole,
  apiGetHubAttendanceWeek,
} from "../api.js";
import { escapeHtml, filterRanked, friendlyError, formatUserName } from "../format.js";
import {
  setMessage,
  confirmDialog,
  confirmArchivedReuse,
  promptPasswordReset,
  promptUserName,
  promptUserRole,
} from "../dom.js";
import { assignableRoles, canManage, roleAtLeast, roleLabel } from "../roles.js";
import { actionMenuHtml, initActionMenus } from "../menus.js";
import { skeletonTableRows } from "../skeleton.js";

const createUserBtn = document.getElementById("create-user-btn");
const createUserMessage = document.getElementById("create-user-message");
const usersTbody = document.getElementById("users-tbody");
const usersMessage = document.getElementById("users-message");
const usersTable = document.getElementById("users-table");
const userProfile = document.getElementById("user-profile");
// Roles whose name opens the weekly profile, for an Admin+ viewer only.
const PROFILE_ROLES = ["technician", "supervisor", "techfm_oa", "admin"];
const usernameInput = document.getElementById("username");
const firstNameInput = document.getElementById("user-first-name");
const lastNameInput = document.getElementById("user-last-name");
const userRoleSelect = document.getElementById("user-role");
const userPasswordInput = document.getElementById("user-password");
const userRoleHelp = document.getElementById("user-role-help");
const historyUserSelect = document.getElementById("history-user-select");
const usersSearch = document.getElementById("users-search");
const usersScope = document.getElementById("users-scope");
const usersAdd = document.getElementById("users-add");
// user id -> days this week flagged for review, from the Timesheets week
// payload (Team Lead+). Empty when the fetch is skipped or fails: the list
// still paints, just without the counts.
let fixCounts = new Map();

// Plain-language role descriptions shown under the Role select so the
// person creating an account understands what each role can do.
const ROLE_DESCRIPTIONS = {
  technician: "Scan items and do basic work.",
  supervisor: "Record stock, edit notes, view history.",
  techfm_oa: "Everything an Admin does, except sending work orders to Review and changing Admin roles.",
  admin: "Manage items and corrections.",
  owner: "Top-level setup.",
};

function updateRoleHelp() {
  if (!userRoleHelp || !userRoleSelect) return;
  userRoleHelp.textContent = ROLE_DESCRIPTIONS[userRoleSelect.value] || "";
}

if (userRoleSelect) userRoleSelect.addEventListener("change", updateRoleHelp);

// The last list refresh, awaited by openUserProfile so a refresh started a
// moment earlier (nav.js's page loader) cannot repaint over the profile.
let lastLoad = Promise.resolve();
// A profile to show on the next table paint instead of hiding it (E8).
let pendingProfile = null;

export function loadUsers() {
  lastLoad = loadUsersNow();
  startFixPolling();
  return lastLoad;
}

// The to-fix counts refetch every minute while the Users page is the one on
// screen; a tick on a hidden tab or another page costs nothing, so the one
// timer simply stays armed. Same cadence as the hub's safety refresh.
const FIX_POLL_MS = 60000;
let fixPollTimer = null;
const usersPage = document.getElementById("saved-users-page");

function startFixPolling() {
  if (fixPollTimer !== null) return;
  fixPollTimer = setInterval(() => {
    if (document.hidden || !usersPage?.classList.contains("active")) return;
    void refreshFixCounts();
  }, FIX_POLL_MS);
}

async function loadUsersNow() {
  // #9: in-progress placeholder (see loadItems for why this lives in the
  // table body rather than the #users-message slot, which carries
  // archive/restore/reset success text set just before a reload).
  usersTbody.innerHTML = skeletonTableRows(4, 5, {
    widths: ["60%", "70%", "40%", "50%"],
  });
  try {
    // Include archived users so the History "by user" filter can still
    // select a departed user; the Saved Users table marks archived rows
    // and offers Restore instead of the active-user actions.
    const [users, week] = await Promise.all([
      apiListUsers({ includeArchived: true }),
      roleAtLeast(getRole(), "supervisor")
        ? apiGetHubAttendanceWeek().catch(() => null)
        : null,
    ]);
    setUsers(users);
    fixCounts = countsFrom(week);
    renderUsersTable();
    populateRoleSelect();
    populateUserSelects();
  } catch (error) {
    // #6: surface the failure rather than logging to a console no field
    // user sees. This also runs on the post-login boot load (Users page
    // hidden) -- harmless, and the page refreshes on activation.
    usersTbody.innerHTML =
      `<tr><td colspan="4" class="error">${escapeHtml(friendlyError(error, "Could not load users. Try again."))}</td></tr>`;
  }
}

function countsFrom(week) {
  return new Map((week?.rows ?? []).map((row) => [
    row.user.id, row.days.filter((d) => d.needs_review || d.pending_review).length,
  ]));
}

// Back from a profile where a punch may just have been fixed, and every poll
// tick: refetch only the week, so the counts are current without repainting
// the list twice.
async function refreshFixCounts() {
  if (!roleAtLeast(getRole(), "supervisor")) return;
  try {
    fixCounts = countsFrom(await apiGetHubAttendanceWeek());
  } catch {
    return;
  }
  if (!usersTable.hidden) renderUsersTable();
}

function renderUsersTable() {
  if (pendingProfile) {
    const { userId, week } = pendingProfile;
    pendingProfile = null;
    void showProfile(getUsers().find((candidate) => candidate.id === userId) ?? { id: userId }, { week });
  } else {
    hideProfile();
  }
  const actorRole = getRole();
  const actorId = getCurrentUser()?.id;
  usersTbody.innerHTML = "";

  paintFixChip();
  const shown = visibleUsers();
  if (!shown.length) {
    const none = scope() === "fix" ? "Nobody needs a fix this week." : `No ${scope()} users match.`;
    usersTbody.innerHTML = `<tr><td colspan="4" class="empty">${none}</td></tr>`;
    return;
  }
  shown.forEach(user => {
    const row = document.createElement("tr");
    const isArchived = Boolean(user.archived_at);
    if (isArchived) row.classList.add("archived-user");
    const canManageUser = canManage(actorRole, user.role);
    const canEditName = actorId === user.id || canManageUser;
    // Role changes are TechFM OA+ only (on top of the usual outranks-the-target
    // rule), and pointless for an archived user, who cannot log in at all.
    const canEditRole =
      canManageUser && !isArchived && roleAtLeast(actorRole, "techfm_oa");
    const options = [];
    if (canEditName) options.push({ value: "edit-details", label: "Edit Details" });
    if (canEditRole) options.push({ value: "edit-role", label: "Edit Role" });
    if (canManageUser && isArchived) {
      options.push({ value: "restore", label: "Restore" });
    } else if (canManageUser) {
      options.push({ value: "reset-password", label: "Reset Password" });
      options.push({ value: "archive", label: "Archive", danger: true });
    }
    const actions = options.length
      ? actionMenuHtml({
        id: `user-row-actions-${user.id}`,
        ariaLabel: `Actions for ${user.username}`,
        itemId: user.id,
        options,
      })
      : `<span class="empty">—</span>`;
    const canProfile = roleAtLeast(actorRole, "supervisor") && PROFILE_ROLES.includes(user.role);
    const name = escapeHtml(formatUserName(user));
    const nameCell = canProfile
      ? `<button type="button" class="user-profile-btn hub-link-btn" data-id="${user.id}">${name}</button>`
      : name;
    const archivedTag = isArchived ? ` <span class="muted">(archived)</span>` : "";
    const toFix = fixCounts.get(user.id) || 0;
    const fixTag = toFix
      ? ` <span class="hub-hours-flag hub-hours-flag-review users-fix-count"><span aria-hidden="true">&#9888;</span> ${toFix} day${toFix === 1 ? "" : "s"} to fix</span>`
      : "";
    row.innerHTML = `
      <td data-label="Name" data-primary>${nameCell}${fixTag}${archivedTag}</td>
      <td data-label="Username">${escapeHtml(user.username)}</td>
      <td data-label="Role">${escapeHtml(roleLabel(user.role))}</td>
      <td data-label="Actions">${actions}</td>
    `;
    usersTbody.appendChild(row);
  });
}

// "active", "archived" or "fix": the pressed cell of the scope toggle.
function scope() {
  return usersScope?.querySelector('[aria-pressed="true"]')?.dataset.scope || "active";
}

const needsFix = (user) => !user.archived_at && (fixCounts.get(user.id) || 0) > 0;

// The "Needs a fix" cell carries how many active people it would show.
function paintFixChip() {
  const chip = usersScope?.querySelector(".users-scope-fix");
  if (!chip) return;
  const n = getUsers().filter(needsFix).length;
  chip.textContent = n ? `Needs a fix (${n})` : "Needs a fix";
}

// The cached list narrowed by the scope toggle and the search box (name or
// username, ranked by filterRanked like the Tools search).
function visibleUsers() {
  const current = scope();
  const inScope = current === "fix"
    ? getUsers().filter(needsFix)
    : getUsers().filter((user) => Boolean(user.archived_at) === (current === "archived"));
  const term = usersSearch?.value.trim() || "";
  return term
    ? filterRanked(inScope, (user) => [formatUserName(user), user.username], term)
    : inScope;
}

usersSearch?.addEventListener("input", () => { if (!usersTable.hidden) renderUsersTable(); });
usersScope?.addEventListener("click", (event) => {
  const btn = event.target.closest(".seg-btn");
  if (!btn) return;
  usersScope.querySelectorAll(".seg-btn").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
  if (!usersTable.hidden) renderUsersTable();
});

// Fill the create-user role dropdown with the roles the current user is
// allowed to assign (those ranked strictly below them).
function populateRoleSelect() {
  if (!userRoleSelect) return;
  const previous = userRoleSelect.value;
  userRoleSelect.innerHTML = "";
  assignableRoles(getRole()).forEach(role => {
    const option = document.createElement("option");
    option.value = role;
    option.textContent = roleLabel(role);
    userRoleSelect.appendChild(option);
  });
  if (previous && [...userRoleSelect.options].some(o => o.value === previous)) {
    userRoleSelect.value = previous;
  }
  updateRoleHelp();
}

async function showProfile(user, { week = null } = {}) {
  const { mountUserProfile } = await import("./userProfile.js");
  usersTable.hidden = true;
  userProfile.hidden = false;
  mountUserProfile(userProfile, user, {
    onBack: () => { hideProfile(); void refreshFixCounts(); }, week, page: "users",
  });
}

// The Back path from a work order (E8): re-open a profile without a click.
// The next table paint shows it; if no refresh is running, show it now.
export async function openUserProfile(userId, { week = null } = {}) {
  pendingProfile = { userId, week };
  if (!getUsers().length) await loadUsers();
  else await lastLoad;
  if (!pendingProfile) return;
  pendingProfile = null;
  await showProfile(getUsers().find((candidate) => candidate.id === userId) ?? { id: userId }, { week });
}

// Back restores the table as it was: no refetch, the cache is still current.
function hideProfile() {
  userProfile.hidden = true;
  userProfile.innerHTML = "";
  usersTable.hidden = false;
}

// Repopulate the History "by user" filter, preserving the current
// selection if that user still exists.
export function populateUserSelects() {
  const previousValue = historyUserSelect.value;
  historyUserSelect.innerHTML = '<option value="" disabled selected>-- Select user --</option>';
  getUsers().forEach(user => {
    const option = document.createElement("option");
    option.value = user.id;
    option.textContent = formatUserName(user);
    historyUserSelect.appendChild(option);
  });
  if (previousValue && getUsers().some(u => u.id === previousValue)) {
    historyUserSelect.value = previousValue;
  }
}

createUserBtn.addEventListener("click", async () => {
  const username = usernameInput.value.trim();
  const firstName = firstNameInput.value.trim();
  const lastName = lastNameInput.value.trim();
  const role = userRoleSelect ? userRoleSelect.value : "";
  const password = userPasswordInput.value;
  setMessage(createUserMessage, "", "");

  if (!firstName || !lastName) {
    setMessage(createUserMessage, "First name and last name are required.", "error");
    return;
  }
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
    const data = await apiCreateUser({ username, firstName, lastName, password, role });
    firstNameInput.value = "";
    lastNameInput.value = "";
    usernameInput.value = "";
    userPasswordInput.value = "";
    if (usersAdd) usersAdd.open = false;
    setMessage(usersMessage, `${formatUserName(data)} created as ${roleLabel(data.role)}.`, "success");
    loadUsers();
  } catch (err) {
    setMessage(createUserMessage, friendlyError(err, "Could not create the user. Try again."), "error");
  }
});

usersTbody.addEventListener("click", async (event) => {
  const target = event.target;
  if (!target.classList.contains("user-profile-btn")) return;
  const user = getUsers().find((candidate) => candidate.id === target.dataset.id);
  if (user) await showProfile(user);
});

// Every pick resolves the user from the cache first, so a stale row (the
// table is rebuilt on every load, so only a race) sends nothing.
initActionMenus(usersTbody, async (action, userId) => {
  const user = getUsers().find((candidate) => candidate.id === userId);
  if (!user) return;
  setMessage(usersMessage, "", "");
  if (action === "edit-details") return editDetails(user);
  if (action === "edit-role") return editRole(user);
  if (action === "reset-password") return resetPassword(user);
  if (action === "restore") return restoreUser(user);
  if (action === "archive") return archiveUser(user);
});

async function editDetails(user) {
  const details = await promptUserName(user, { allowUsername: true });
  if (!details) return;
  try {
    const updated = await apiUpdateUserName(user.id, details);
    if (getCurrentUser()?.id === user.id) {
      setCurrentUser(updated);
      const indicator = document.getElementById("auth-user-indicator");
      if (indicator) {
        indicator.querySelector(".user-hub-name").textContent = formatUserName(updated);
        indicator.querySelector(".user-hub-role").textContent = roleLabel(updated.role);
        indicator.setAttribute(
          "aria-label",
          `Your hub — ${formatUserName(updated)}, ${roleLabel(updated.role)}`
        );
      }
    }
    document.dispatchEvent(new Event("user-names-updated"));
    // Name the account by its *new* username: after a username change the
    // old one no longer identifies anything.
    setMessage(usersMessage, `Updated "${updated.username}".`, "success");
    loadUsers();
  } catch (err) {
    setMessage(usersMessage, friendlyError(err, "Could not update the user's details."), "error");
  }
}

async function editRole(user) {
  // Same set the create form offers -- the roles this actor outranks --
  // which is also exactly what the backend will accept.
  const options = assignableRoles(getRole()).map(role => ({
    value: role,
    label: roleLabel(role),
    description: ROLE_DESCRIPTIONS[role] || "",
  }));
  const role = await promptUserRole(user, options);
  if (!role) return; // cancelled, or unchanged
  try {
    const updated = await apiUpdateUserRole(user.id, role);
    setMessage(
      usersMessage,
      `"${updated.username}" is now ${roleLabel(updated.role)}. They will need to sign in again.`,
      "success",
    );
    loadUsers();
  } catch (err) {
    setMessage(usersMessage, friendlyError(err, "Could not change the user's role."), "error");
  }
}

async function resetPassword(user) {
  // The modal validates length and confirmation before resolving, so a
  // returned value is always a valid password; null means cancelled.
  const newPassword = await promptPasswordReset(user.username);
  if (newPassword === null) return; // cancelled
  try {
    await apiResetPassword(user.id, newPassword);
    setMessage(usersMessage, `Password reset for "${user.username}".`, "success");
  } catch (err) {
    setMessage(usersMessage, friendlyError(err, "Could not reset the password. Try again."), "error");
  }
}

async function restoreUser(user) {
  try {
    await apiRestoreUser(user.id);
    setMessage(usersMessage, `Restored "${user.username}".`, "success");
    loadUsers();
  } catch (err) {
    setMessage(usersMessage, friendlyError(err, "Could not restore the user. Try again."), "error");
  }
}

// Archive (soft delete): the user can no longer log in, but their
// history is preserved and they can be restored later.
async function archiveUser(user) {
  const userName = user.username;
  if (!(await confirmDialog(`Archive user "${userName}"? They will no longer be able to log in, but their history is kept and they can be restored.`))) return;
  try {
    // The server refuses with 409 while the user still holds tools (an
    // archived user disappears from the custody workflow). Confirming the
    // second prompt retries with force, checking those tools in first.
    await confirmArchivedReuse(
      (force) => apiArchiveUser(user.id, { forceReturnTools: force }),
      `"${userName}" still has tools checked out. Check them all in now and archive?`,
    );
    setMessage(usersMessage, `Archived "${userName}".`, "success");
    loadUsers();
  } catch (err) {
    if (err && err.cancelled) {
      setMessage(usersMessage, "", "");
      return;
    }
    setMessage(usersMessage, friendlyError(err, "Could not archive the user. Try again."), "error");
  }
}
