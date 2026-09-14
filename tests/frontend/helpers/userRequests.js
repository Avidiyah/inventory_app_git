// The User Requests mount fixture.
//
// `userRequests.js` imports only its own cards module from `views/`, so it is
// the entry point of its own graph: a plain `mountView`. Nothing loads at
// import -- `loadUserRequests()` is the entry, and `nav.js` calls it on page
// activation -- so `openUserRequests()` is the shorthand for "mounted and
// loaded".
//
// The list handler narrows by the `status` and `type` query params the way
// `routers/user_requests.py::list_user_requests` does, so a tab click reloads
// into a DIFFERENT set of cards and the assertion can be on what painted, not
// only on the URL.

import { http, HttpResponse } from "msw";
import { server } from "./handlers.js";
import { startRecording, stopRecording, requests, requestFor, clearRequests } from "./requests.js";
import { mountView } from "./shell.js";
import { setTestUser } from "./session.js";
import { connectFakeRealtime } from "./realtime.js";

const byId = (id) => () => document.getElementById(id);

export const el = {
  status: byId("user-requests-status"),
  tabs: byId("user-requests-tabs"),
  refresh: byId("user-requests-refresh"),
  list: byId("user-requests-list"),
  message: byId("user-requests-message"),
};

export const cards = () => Array.from(el.list().querySelectorAll(".user-request-card"));
export const cardFor = (id) => el.list().querySelector(`.user-request-card[data-id="${id}"]`);
export const tab = (type) => el.tabs().querySelector(`.hub-tab[data-request-type="${type}"]`);
export const tabCount = (type) => tab(type).querySelector(".user-requests-tab-count").textContent;
export const statusOptions = () => Array.from(el.status().options).map((o) => o.value);
export const panelOf = (card) => card.querySelector(".user-request-panel");
// The action buttons' class lists, tip buttons excluded (`tipHtml` renders
// a `.tip-btn` beside two of the actions).
export const actionsOf = (card) =>
  Array.from(card.querySelectorAll(".user-request-actions button"))
    .map((b) => b.className).filter((c) => c !== "tip-btn");
export const hintsOf = (card) =>
  Array.from(card.querySelectorAll(".user-request-actions .hint")).map((h) => h.textContent);
// The list GET(s) since the last clear -- the counts GET shares the prefix.
export const listRequests = () => requests().filter((r) => r.url.startsWith("/user-requests/?"));

export { requests, requestFor, clearRequests };
export { answerConfirm, confirmOverlay, confirmTitle } from "./dialogs.js";

let realtime = null;

// `requests` seeds the list, `counts` the tab labels. `handlers` go FIRST so a
// test's own `/user-requests/` override wins.
export async function mountUserRequests({
  role = "admin", requests: seeded = [], counts = {}, handlers = [],
} = {}) {
  server.use(
    ...handlers,
    http.get("/user-requests/counts", () => HttpResponse.json(counts)),
    http.get("/user-requests/", ({ request }) => {
      const params = new URL(request.url).searchParams;
      const status = params.get("status");
      const type = params.get("type");
      return HttpResponse.json(seeded.filter((r) =>
        (status === null || r.status === status) && (type === null || r.request_type === type)));
    }),
  );
  const currentUser = await setTestUser({ role });
  startRecording();
  const mod = await mountView("views/userRequests.js");
  clearRequests();
  return { mod, currentUser };
}

// Mounted AND loaded, with the load's own two requests cleared.
export async function openUserRequests(options = {}) {
  const mounted = await mountUserRequests(options);
  await mounted.mod.loadUserRequests();
  clearRequests();
  return mounted;
}

export async function connectUserRequests(activePage = "user-requests") {
  realtime = await connectFakeRealtime(activePage);
  return realtime;
}

export function restoreUserRequests() {
  if (realtime) { realtime.disconnect(); realtime = null; }
  stopRecording();
}
