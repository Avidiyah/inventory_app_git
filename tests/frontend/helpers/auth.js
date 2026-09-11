// The auth mount fixture.
//
// `views/auth.js` exports `initAuth()` and never calls it at import, so the
// test decides the `/auth/me` answer, mounts, then boots -- every branch of the
// boot check is reachable from one fixture. `main.js` is deliberately NOT
// imported (which is what `helpers/app.js` does instead): it calls `initAuth()`
// at import, before a test can choose the branch.
//
// Nothing here mocks an app module. MSW answers `fetch`, and the real api.js,
// nav.js, transactions.js, push.js, realtime.js and the work-order barrel all
// run.

import { http, HttpResponse } from "msw";
import { pageHandlers, server } from "./handlers.js";
import { mountView } from "./shell.js";
import { installFakeWebSocket } from "./fakeSocket.js";
import { restoreMediaStubs, restorePush, stubMediaEnvironment } from "./media.js";
import { startRecording, stopRecording, requests, requestFor, clearRequests } from "./requests.js";
import { user as userFactory } from "./factories.js";

// Getters, not nodes: every mount replaces `document.documentElement`, so a
// captured node would be a corpse from the previous test.
const byId = (id) => () => document.getElementById(id);

export const el = {
  screen: byId("login-screen"),
  root: byId("app-root"),
  username: byId("login-username"),
  password: byId("login-password"),
  toggle: byId("login-password-toggle"),
  btn: byId("login-btn"),
  remember: byId("login-remember"),
  notifications: byId("login-notifications"),
  message: byId("login-message"),
  logout: byId("logout-btn"),
  indicator: byId("auth-user-indicator"),
  woGateMessage: byId("wo-gate-message"),
  page: (name) => document.getElementById(`${name}-page`),
};

// --- request recording ------------------------------------------------------
//
// The shared recorder in `helpers/requests.js` (P5d lifted it out of here and
// `helpers/items.js`, which carried identical copies). Re-exported so this
// fixture's existing import surface is unchanged.

export { requests, requestFor, clearRequests };

// --- per-test answers -------------------------------------------------------
//
// A number is a failure status (with an optional `detail`); anything else is
// the 200 body.

const answer = (value, detail) =>
  typeof value === "number"
    ? HttpResponse.json({ detail: detail ?? "Not authenticated" }, { status: value })
    : HttpResponse.json(value);

export function answerMe(userOrStatus, { detail } = {}) {
  server.use(http.get("/auth/me", () => answer(userOrStatus, detail)));
}

export function answerLogin(userOrStatus, { detail } = {}) {
  server.use(http.post("/auth/login", () => answer(userOrStatus, detail)));
}

export function answerLogout(status = 204) {
  server.use(http.post("/auth/logout", () => (
    status === 204
      ? new HttpResponse(null, { status })
      : HttpResponse.json({ detail: "Logout failed" }, { status })
  )));
}

// --- the batch snapshot `transactions.js` persists --------------------------
//
// Written here in the exact shape `persistBatch` writes, so `readSavedBatch`
// accepts it. A hand-rolled shape that the validator rejected would make every
// resume test pass for the wrong reason.

export const BATCH_KEY = "scango-batch";

export function seedBatch({ userId, workOrder, scangoType = "dispense", log = [] }) {
  sessionStorage.setItem(BATCH_KEY, JSON.stringify({
    userId,
    workOrder,
    scangoType,
    quickMode: false,
    batchScanCount: log.length,
    batchUnitCount: log.length,
    log,
  }));
}

export function savedBatch() {
  const raw = sessionStorage.getItem(BATCH_KEY);
  return raw ? JSON.parse(raw) : null;
}

// --- mount ------------------------------------------------------------------

let ws = null;

// Mount `views/auth.js` against the real shell with `/auth/me` arranged.
// Does NOT call `initAuth()` -- that is the test's move, and the whole reason
// this fixture exists.
//
//   me        the `/auth/me` answer: a user object, or a status number
//   handlers  extra MSW handlers. Registered AHEAD of `pageHandlers()`, which
//             is what makes them win: `server.use(a, b)` puts `a` first.
export async function mountAuth({ me = 401, handlers = [] } = {}) {
  server.use(...handlers, ...pageHandlers());
  answerMe(me);
  stubMediaEnvironment({ permission: "prompt" });
  ws = installFakeWebSocket();
  startRecording();
  const mod = await mountView("views/auth.js");
  clearRequests();
  return { mod, ws, requests };
}

// `mountAuth` with a valid session, already booted. Requests are cleared after
// boot, so a test that wants to assert on what `enterApp` fired drives
// `initAuth()` by hand instead.
export async function signedIn(overrides = {}) {
  const current = userFactory({ role: "technician", ...overrides });
  const mounted = await mountAuth({ me: current });
  await mounted.mod.initAuth();
  clearRequests();
  return { ...mounted, user: current };
}

export function restoreAuth() {
  stopRecording();
  restorePush();
  restoreMediaStubs();
  if (ws) {
    ws.restore();
    ws = null;
  }
  // A deep-link test leaves `/workorder_card/<n>` in the address bar, and the
  // next mount's `soloNumberFromPath` would read it.
  window.history.replaceState({}, "", "/");
}
