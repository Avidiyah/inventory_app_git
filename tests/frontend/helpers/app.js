// The whole-app boot fixture.
//
// P2's fixture mounts one view that owns one page. These modules do not work
// that way: `views/nav.js` imports twelve views, `views/auth.js` nine, and
// `main.js` imports everything, so mounting any of them boots most of the
// frontend. Rather than build that setup three times, every P5 chunk boots
// through here.
//
// What runs is production's own entry point -- `backend/static/main.js`,
// imported after the real shell is in the document. The four cross-view
// callbacks, `installTooltips()` and `initAuth()` all execute. Nothing is
// mocked: MSW answers `fetch`, a scriptable class answers `new WebSocket`,
// and the camera is stubbed at the browser boundary (see `media.js`).
//
// The one thing this fixture asserts on its own behalf is that boot is quiet:
// `bootApp` waits for the app to be revealed, so a test that never gets there
// fails in the fixture with a clear message instead of in an assertion.

import { afterEach, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server, pageHandlers } from "./handlers.js";
import { mountShell } from "./shell.js";
import { setTestUser } from "./session.js";
import { installFakeWebSocket } from "./fakeSocket.js";
import { restoreMediaStubs, stubMediaEnvironment } from "./media.js";

// --- request recording ----------------------------------------------------
//
// Same shape as `helpers/workOrders.js`: wraps MSW's own `fetch` replacement
// so the recorder sees exactly the `init` api.js built, synchronously.

let recorded = [];
let originalFetch = null;

function startRecording() {
  if (originalFetch) return;
  originalFetch = globalThis.fetch;
  globalThis.fetch = vi.fn(async (input, init = {}) => {
    recorded.push({
      url: typeof input === "string" ? input : input.url,
      method: (init.method || "GET").toUpperCase(),
      body: parseBody(init.body),
    });
    return originalFetch(input, init);
  });
}

function parseBody(body) {
  if (typeof body !== "string") return body ?? null;
  try {
    return JSON.parse(body);
  } catch {
    return body;
  }
}

// Every recorded `(method, url, body)` since the last `clearRequests()`.
export function requests() {
  return recorded;
}

export function clearRequests() {
  recorded = [];
}

// Recorded calls whose url starts with `path` (query string ignored). The
// natural assertion for "the loader ran exactly once".
export function requestsFor(path, method = null) {
  return recorded.filter(
    (call) => call.url.split("?")[0] === path && (!method || call.method === method),
  );
}

// --- the boot itself ------------------------------------------------------

let sockets = null;

export const appRoot = () => document.getElementById("app-root");
export const loginScreen = () => document.getElementById("login-screen");

// Boot the real composition root as `role`, signed in.
//
//   role      the signed-in user's role; also what `apiMe` answers with, so
//             `state.js` and the response agree (they are two different
//             writes in production, and a test that disagreed with itself
//             would be asserting on a state the app never reaches)
//   user      extra fields for that user, merged into the factory
//   page      navigate here once boot has settled, instead of leaving the
//             role's landing page active
//   handlers  extra MSW handlers. Registered FIRST, which is what makes them
//             win: `server.use(a, b)` puts `a` ahead of `b`, and both ahead
//             of what is already registered
//   media     options for `stubMediaEnvironment`, or `false` to install none
//
// Returns the live `views/nav.js` module (the same instance `main.js` wired,
// because a relative specifier and `shell.js`'s file:// URL resolve to one
// module id under Vitest) plus the recorder.
export async function bootApp({
  role = "owner",
  user: userOverrides = {},
  page = null,
  handlers = [],
  media = {},
} = {}) {
  vi.resetModules();
  mountShell();
  if (media !== false) stubMediaEnvironment(media);
  sockets = installFakeWebSocket();

  const currentUser = await setTestUser({ role, ...userOverrides });
  server.use(
    ...handlers,
    http.get("/auth/me", () => HttpResponse.json(currentUser)),
    ...pageHandlers(),
  );
  startRecording();

  await import("../../../backend/static/main.js");

  // `main.js` calls `initAuth()` without awaiting it, so the reveal lands a
  // few microtasks later. Waiting on the DOM rather than on a promise is
  // deliberate: it is the same thing the user sees.
  await vi.waitFor(() => expect(appRoot().hidden).toBe(false));

  const nav = await import("../../../backend/static/views/nav.js");
  if (page !== null) {
    nav.showPage(page);
    await vi.waitFor(() => expect(nav.getActivePage()).toBe(page));
  }
  return { nav, currentUser, requests, requestsFor, clearRequests, sockets };
}

// The 401 path: `apiMe` refuses and the app never reveals. Used by P5b for
// the login-screen tests, and here to assert that a boot-time 401 fires no
// page loader.
export async function bootLoggedOut({ handlers = [], media = {} } = {}) {
  vi.resetModules();
  mountShell();
  if (media !== false) stubMediaEnvironment(media);
  sockets = installFakeWebSocket();

  server.use(
    ...handlers,
    http.get("/auth/me", () => HttpResponse.json({ detail: "Not authenticated" }, { status: 401 })),
    ...pageHandlers(),
  );
  startRecording();

  await import("../../../backend/static/main.js");
  await vi.waitFor(() => expect(loginScreen().hidden).toBe(false));

  const nav = await import("../../../backend/static/views/nav.js");
  return { nav, requests, requestsFor, clearRequests, sockets };
}

// --- cleanup --------------------------------------------------------------
//
// Registered here rather than in every behaviour file: importing this module
// is the declaration that a test boots the app.
afterEach(() => {
  if (originalFetch) {
    globalThis.fetch = originalFetch;
    originalFetch = null;
  }
  recorded = [];
  restoreMediaStubs();
  if (sockets) {
    sockets.restore();
    sockets = null;
  }
});
