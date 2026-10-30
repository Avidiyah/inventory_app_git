// The Saved Users mount fixture.
//
// `users.js` imports nothing from `views/`, so unlike Items and Tools it can be
// the entry point of its own module graph: this is a plain `mountView`. Nothing
// loads at import either -- `loadUsers()` is the entry, and `nav.js` calls it
// on page activation -- so `openUsers()` is the shorthand for "mounted and
// loaded".

import { http, HttpResponse } from "msw";
import { server } from "./handlers.js";
import { startRecording, stopRecording, requests, requestFor, clearRequests } from "./requests.js";
import { mountView } from "./shell.js";
import { setTestUser } from "./session.js";

// Getters, not nodes: every mount replaces `document.documentElement`, so a
// captured node would be a corpse from the previous test.
const byId = (id) => () => document.getElementById(id);

export const el = {
  tbody: byId("users-tbody"), message: byId("users-message"),
  // The Add user panel sits above the table; users.js wires it at import.
  addPanel: byId("users-add"),
  firstName: byId("user-first-name"), lastName: byId("user-last-name"),
  username: byId("username"), roleSelect: byId("user-role"),
  roleHelp: byId("user-role-help"), password: byId("user-password"),
  createBtn: byId("create-user-btn"), createMessage: byId("create-user-message"),
  // Written by populateUserSelects, read by the History page.
  historySelect: byId("history-user-select"),
  // Rewritten in place by a self-edit.
  indicator: byId("auth-user-indicator"),
};

export const rows = () => Array.from(el.tbody().querySelectorAll("tr"));
export const cells = (row) => Array.from(row.querySelectorAll("td")).map((td) => td.textContent);

// Rows are keyed by the Username column, which is the one cell guaranteed
// present and unique -- the Name column can read "Name unavailable".
export const rowFor = (username) =>
  rows().find((row) => row.querySelectorAll("td")[1]?.textContent === username) ?? null;

// The Active / Archived toggle above the table. Archived rows paint only
// under the Archived scope.
export const scopeBtn = (scope) => document.querySelector(`#users-scope [data-scope="${scope}"]`);
export const showScope = (scope) => scopeBtn(scope).click();
export const search = () => document.getElementById("users-search");

// The row's action menu (menus.js): its option values, in order.
export const menuIn = (row) => row.querySelector(".action-menu");
export const actionsIn = (row) =>
  Array.from(row.querySelectorAll(".action-menu .menu-option")).map((o) => o.dataset.value);

// Open the row's menu and pick one action, through real clicks.
export async function pickAction(user, row, value) {
  await user.click(row.querySelector(".menu-trigger"));
  await user.click(row.querySelector(`.menu-option[data-value="${value}"]`));
}

export const roleOptions = () =>
  Array.from(el.roleSelect().options).map((option) => option.value);

export const historyOptions = () =>
  Array.from(el.historySelect().options).map((option) => ({
    value: option.value, label: option.textContent,
  }));

// --- request recording -----------------------------------------------------
export { requests, requestFor, clearRequests };

// --- the real overlays (dom.js) --------------------------------------------
export {
  answerConfirm, answerPasswordReset, answerUserName, answerUserRole,
} from "./dialogs.js";

// --- mount ------------------------------------------------------------------
// `currentUser` overrides go onto the signed-in user; a self-edit test needs
// the actor to BE one of the rows, so it passes the row's own id here.
export async function mountUsers({
  role = "owner", users = [], handlers = [], currentUser = {},
} = {}) {
  // `handlers` go FIRST: MSW takes the first matching handler within one
  // `use()` call, so a test's own `/users/` override must precede the default.
  // The path matches with or without `?include_archived=true`.
  server.use(
    ...handlers,
    http.get("/users/", () => HttpResponse.json(users)),
  );
  const me = await setTestUser({ role, ...currentUser });
  startRecording();
  const mod = await mountView("views/users.js");
  clearRequests();
  return { mod, currentUser: me };
}

// Mounted AND loaded, with the load's own request cleared.
export async function openUsers(options = {}) {
  const mounted = await mountUsers(options);
  await mounted.mod.loadUsers();
  clearRequests();
  return mounted;
}

export function restoreUsers() {
  stopRecording();
}
