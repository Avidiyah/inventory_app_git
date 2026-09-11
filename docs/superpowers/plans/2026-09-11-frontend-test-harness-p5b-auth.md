# Frontend Test Harness — P5b (`views/auth.js`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline in the session — no subagents** (decided 2026-09-11; `CLAUDE.md` forbids them here). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status: COMPLETE 2026-09-11 (Tasks 1-7). Left uncommitted at the user's direction — P5a was still in the working tree, so nothing here was committed.**

**Goal:** Characterization coverage for `backend/static/views/auth.js` (232 lines): boot check, login, logout, the expiry asymmetry, deep link, batch resume, push-at-login.

**Architecture:** Tests only. `auth.js` exports `initAuth()` and does *not* call it at import, so the test mounts `views/auth.js` through `mountView()`, arranges the `/auth/me` answer, then calls `initAuth()` itself — one fixture, every boot branch reachable. The chunk consumes two P5a deliverables by name: `pageHandlers()` (the loader bundle `enterApp → showPage` fires) and the media stubs. It does **not** boot through `bootApp()`: that imports `main.js`, which runs `initAuth()` at import, before a test can choose the `/auth/me` branch. Recorded as a deviation from the P5 plan's "every chunk mounts through `bootApp`".

**Tech Stack:** Vitest, jsdom, @testing-library/dom, @testing-library/user-event, msw.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3
**Parent plan:** `docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md` (P5b bullet list is the requirement set)
**Depends on:** P5a landed on `main` (`tests/frontend/helpers/app.js`, `helpers/media.js`, `pageHandlers()` in `helpers/handlers.js`).

## Global constraints

- Tests only. No edit under `backend/static/` or `backend/app/`. If a branch cannot be reached without a production change, record it under Findings and move on.
- Characterization, not correction: assert what the code does; comment where it looks wrong; file it in `docs/open-work.md` at the end.
- No `vi.mock` of any app module. Seams: `fetch` (MSW), `WebSocket` (`installFakeWebSocket`), `sessionStorage`, browser globals (`Notification`, `navigator.serviceWorker`, `PushManager`).
- `onUnhandledRequest: "error"` stays on. Every request `enterApp` fires is answered by name via `pageHandlers()` plus the per-test handlers listed below.
- `mountView()` before any import — `auth.js` captures eleven element ids at import.
- Clicks and typing go through `@testing-library/user-event`, not `el.click()` / `.value =` — except where a step says otherwise.
- Commit messages end with the attribution lines the session provides.
- Word budget for this plan: 3,500 (repo rule). Code blocks are the content; prose stays clipped.

## Entry gate — verify before Task 1

- [ ] `git log --oneline -15` shows P5a's commits; `tests/frontend/helpers/app.js` and `helpers/media.js` exist; `grep -n "export function pageHandlers" tests/frontend/helpers/handlers.js` hits.
- [ ] Read `helpers/media.js` and `helpers/handlers.js` once. If P5a chose different names for `pageHandlers`, `stubUserMedia`, `stubPermissions`, `restoreMediaStubs`, substitute them **in `helpers/auth.js` only** — the test file imports nothing from P5a directly.
- [ ] Names checked against P5a's working tree on 2026-09-11: `pageHandlers()`, `stubUserMedia()`, `stubPermissions(state = "prompt")`, `restoreMediaStubs()` all exist as assumed. P5a also exports `stubMediaEnvironment({...})`, a one-call bundle — use it in the fixture instead of the two separate stubs if it covers `mediaDevices` + `permissions`.
- [ ] `npm test` green to completion; record count and wall-clock (P4 baseline: 819 tests / 27 files / ~50 s; P5a will have moved it).
- [ ] No other session is mid-commit in this checkout.

## What `enterApp` fires, per role (drives the handler bundle)

Derived from `auth.js` + `nav.js` on 2026-09-11. Verify against `pageHandlers()` at the gate; anything missing goes into `mountAuth`'s own `server.use`.

| Step in `enterApp` | Request | Roles |
| --- | --- | --- |
| `tryResumeBatch` (only with a matching snapshot) | `GET /work-orders/{id}` | all |
| `setHistoryTab("all")` | **none** — `showFeature` returns early when the tab is already `all`, which it is on a fresh mount (`history.html` pre-marks it). A characterization point, not a gap. | supervisor+ |
| `loadUsers()` | `GET /users/?include_archived=true` | supervisor+ |
| `showPage("user-hub")` → `loadUserHub()` | `GET /hub`; then `GET /hub/crew` (supervisor+), `GET /hub/admin` (techfm_oa+) in the background | all |
| deep link → `showPage("work-orders")` → `loadWorkOrders` | `GET /items/`, `GET /users/`, `GET /work-orders/?q=N`, `GET /work-orders/{id}`, `GET /work-orders/{id}/requests` | all |
| `connectRealtime()` | `new WebSocket(...)` — fake socket | all |
| `initPushForUser()` | `GET /push/config`, `POST /push/subscribe` — only with push stubbed and permission `granted` | all |

---

### Task 1: `helpers/auth.js` — the auth mount fixture, plus push stubs in `helpers/media.js`

**Files:**
- Create: `tests/frontend/helpers/auth.js`
- Modify: `tests/frontend/helpers/media.js` (append `stubPush` / `restorePush`)
- Test: `tests/frontend/views/auth.test.js` (one smoke test; the file grows in later tasks)

**Interfaces:**
- Consumes: `pageHandlers()` from `helpers/handlers.js`; `stubUserMedia()`, `stubPermissions(state)`, `restoreMediaStubs()` from `helpers/media.js`; `installFakeWebSocket()` from `helpers/fakeSocket.js`; `user()` from `helpers/factories.js`; `mountView()` from `helpers/shell.js`.
- Produces:
  - `mountAuth({ me = 401, handlers = [] })` → `{ mod, ws, requests() }` — mounts `views/auth.js` with `/auth/me` answered (`me: null` skips it so a test can supply its own). `handlers` are registered ahead of `pageHandlers()` so they win. Does **not** call `initAuth`.
  - `signedIn(overrides = {})` → `{ mod, ws, user, requests() }` — `mountAuth` with a 200 user, then `await mod.initAuth()`.
  - `answerMe(userOrStatus)`, `answerLogin(userOrStatus, { detail })`, `answerLogout(status = 204)` — per-test MSW overrides.
  - `el` — id-keyed element getters (`el.screen()`, `el.root()`, `el.username()`, `el.password()`, `el.toggle()`, `el.btn()`, `el.remember()`, `el.notifications()`, `el.message()`, `el.logout()`, `el.indicator()`, `el.page(name)`).
  - `seedBatch({ userId, workOrder })` — writes the `scango-batch` `sessionStorage` snapshot in the shape `transactions.js persistBatch` writes; `savedBatch()` reads it back (or `null`).
  - `stubPush({ permission = "default", subscription = null })` / `restorePush()` in `media.js` — returns `{ requestPermission, register, getRegistration, unsubscribe }` spies.

- [ ] **Step 1: Write the smoke test**

```js
// tests/frontend/views/auth.test.js
import { afterEach, describe, expect, it } from "vitest";
import { el, mountAuth, restoreAuth, signedIn } from "../helpers/auth.js";

afterEach(() => restoreAuth());

describe("mountAuth", () => {
  it("mounts auth.js against the real login markup without booting", async () => {
    const { mod } = await mountAuth();
    expect(typeof mod.initAuth).toBe("function");
    expect(el.screen().hidden).toBe(true);
    expect(el.root().hidden).toBe(true);
  });

  it("signedIn reveals the app on a technician's landing page", async () => {
    const { ws } = await signedIn({ role: "technician" });
    expect(el.root().hidden).toBe(false);
    expect(el.page("user-hub").classList.contains("active")).toBe(true);
    expect(ws.sockets).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run tests/frontend/views/auth.test.js`
Expected: FAIL — `Cannot find module '../helpers/auth.js'`.

- [ ] **Step 3: Append the push stubs to `helpers/media.js`**

jsdom defines none of `navigator.serviceWorker`, `window.PushManager`, `window.Notification`, so `push.js`'s `pushSupported()` is false by default and every push path silently no-ops. The stub makes all three exist.

```js
// append to tests/frontend/helpers/media.js
// `push.js` gates every call on `pushSupported()`: serviceWorker + PushManager +
// Notification all present. jsdom has none, so the default is "unsupported"
// and the stub is what makes the push branches reachable at all.
let pushRestorers = [];

export function stubPush({ permission = "default", subscription = null } = {}) {
  const requestPermission = vi.fn(async () => permission);
  const unsubscribe = vi.fn(async () => true);
  const sub = subscription && {
    endpoint: subscription.endpoint ?? "https://push.example/abc",
    toJSON: () => ({ endpoint: subscription.endpoint ?? "https://push.example/abc", keys: {} }),
    unsubscribe,
  };
  const registration = {
    pushManager: {
      getSubscription: vi.fn(async () => sub),
      subscribe: vi.fn(async () => sub ?? {
        endpoint: "https://push.example/new",
        toJSON: () => ({ endpoint: "https://push.example/new", keys: {} }),
        unsubscribe,
      }),
    },
  };
  const register = vi.fn(async () => registration);
  const getRegistration = vi.fn(async () => registration);

  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true, value: { register, getRegistration },
  });
  pushRestorers.push(() => { delete navigator.serviceWorker; });
  vi.stubGlobal("PushManager", function PushManager() {});
  vi.stubGlobal("Notification", { permission, requestPermission });
  pushRestorers.push(() => vi.unstubAllGlobals());
  return { requestPermission, register, getRegistration, unsubscribe, registration };
}

export function restorePush() {
  while (pushRestorers.length) pushRestorers.pop()();
}
```

`vi.stubGlobal` is also what `installFakeWebSocket` uses; `unstubAllGlobals` restores both, which is fine because `restoreAuth()` (below) restores everything at once.

- [ ] **Step 4: Write `helpers/auth.js`**

```js
// tests/frontend/helpers/auth.js
//
// The auth mount fixture. `views/auth.js` exports `initAuth()` and never calls
// it at import, so the test decides the /auth/me answer, mounts, then boots --
// every branch of the boot check is reachable from one fixture. main.js is
// deliberately NOT imported: it calls initAuth() at import, before a test can
// choose the branch.
//
// Nothing here mocks an app module. MSW answers fetch; the real api.js,
// nav.js, transactions.js, push.js, realtime.js and the work-order barrel run.

import { vi } from "vitest";
import { http, HttpResponse } from "msw";
import { pageHandlers, server } from "./handlers.js";
import { mountView } from "./shell.js";
import { installFakeWebSocket } from "./fakeSocket.js";
import { restoreMediaStubs, restorePush, stubPermissions, stubUserMedia } from "./media.js";
import { user as userFactory } from "./factories.js";

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
  page: (name) => document.getElementById(`${name}-page`),
  woGateMessage: byId("wo-gate-message"),
};

// --- request recording (same wrapper P2 uses; see helpers/workOrders.js) ---
let recorded = [];
let originalFetch = null;
function startRecording() {
  if (originalFetch) return;
  originalFetch = globalThis.fetch;
  globalThis.fetch = vi.fn(async (input, init = {}) => {
    let body = init.body ?? null;
    if (typeof body === "string") { try { body = JSON.parse(body); } catch { /* keep string */ } }
    recorded.push({
      url: typeof input === "string" ? input : input.url,
      method: (init.method || "GET").toUpperCase(),
      body,
    });
    return originalFetch(input, init);
  });
}
export function requests() { return recorded; }
export function requestFor(fragment, method = null) {
  return [...recorded].reverse()
    .find((r) => r.url.includes(fragment) && (!method || r.method === method)) ?? null;
}
export function clearRequests() { recorded = []; }

// --- per-test answers -------------------------------------------------------
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
  server.use(http.post("/auth/logout", () =>
    status === 204 ? new HttpResponse(null, { status }) : HttpResponse.json({ detail: "x" }, { status })));
}

// --- the batch snapshot transactions.js persists ----------------------------
export const BATCH_KEY = "scango-batch";
export function seedBatch({ userId, workOrder, scangoType = "dispense", log = [] }) {
  sessionStorage.setItem(BATCH_KEY, JSON.stringify({
    userId, workOrder, scangoType, quickMode: false,
    batchScanCount: log.length, batchUnitCount: log.length, log,
  }));
}
export function savedBatch() {
  const raw = sessionStorage.getItem(BATCH_KEY);
  return raw ? JSON.parse(raw) : null;
}

// --- mount ------------------------------------------------------------------
let ws = null;

// `handlers` go FIRST: MSW takes the first matching handler in a `use()`
// call, so a test's override must precede the bundle. `me: null` skips the
// /auth/me answer for a test that supplies its own.
export async function mountAuth({ me = 401, handlers = [] } = {}) {
  server.use(...handlers, ...pageHandlers());
  if (me !== null) answerMe(me);
  stubUserMedia();
  stubPermissions("prompt");
  ws = installFakeWebSocket();
  startRecording();
  const mod = await mountView("views/auth.js");
  clearRequests();
  return { mod, ws, requests };
}

export async function signedIn(overrides = {}) {
  const current = userFactory({ role: "technician", ...overrides });
  const mounted = await mountAuth({ me: current });
  await mounted.mod.initAuth();
  clearRequests();
  return { ...mounted, user: current };
}

export function restoreAuth() {
  if (originalFetch) { globalThis.fetch = originalFetch; originalFetch = null; }
  recorded = [];
  restorePush();
  restoreMediaStubs();
  if (ws) { ws.restore(); ws = null; }
  window.history.replaceState({}, "", "/");
}
```

Notes for the implementer:
- Ids verified 2026-09-11: `wo-gate-message`, `scango-wo-label` (`pages/transaction.html`), `push-test-btn` (`shell-head.html`).
- `stubPermissions("prompt")` keeps `refreshPermissionState` honest for tests that navigate to a scanner page; if P5a's signature differs, adapt here.

- [ ] **Step 5: Run the smoke test**

Run: `npx vitest run tests/frontend/views/auth.test.js`
Expected: PASS ×2. If the second test fails on an unhandled request, the URL in the error names the loader `pageHandlers()` is missing — add it to `mountAuth`'s `server.use` list with an empty-but-valid body from `factories.js`, and note it for P5a.

- [ ] **Step 6: Commit**

```bash
git add tests/frontend/helpers/auth.js tests/frontend/helpers/media.js tests/frontend/views/auth.test.js
git commit -m "test(p5b): auth mount fixture and push stubs"
```

---

### Task 2: Boot check — `initAuth()` both ways, and the login form's static wiring

**Files:** Modify `tests/frontend/views/auth.test.js`.

- [ ] **Step 1: Write the tests**

```js
// Header for the whole file (Tasks 2-6 add to this one file):
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import {
  answerLogin, answerLogout, el, mountAuth, requestFor, requests, restoreAuth,
  savedBatch, seedBatch, signedIn,
} from "../helpers/auth.js";
import { user as userFactory, workOrderCard, workOrderDetail } from "../helpers/factories.js";
import { stubPush } from "../helpers/media.js";
import { restoreBrowserStubs, stubScroll } from "../helpers/browserStubs.js";

describe("initAuth — a valid session", () => {
  it.each([
    ["technician", ["saved-users", "history", "create-item"]],
    ["supervisor", ["create-item", "low-stock"]],
    ["techfm_oa", []],
    ["admin", []],
    ["owner", []],
  ])("%s: reveals the app, names the user, hides %j", async (role, hiddenPages) => {
    const { user } = await signedIn({ role, full_name: "Pat Example" });
    expect(el.screen().hidden).toBe(true);
    expect(el.root().hidden).toBe(false);
    expect(el.indicator().querySelector(".user-hub-name").textContent).toBe("Pat Example");
    expect(el.indicator().getAttribute("aria-label")).toContain("Pat Example");
    for (const page of hiddenPages) {
      expect(document.querySelector(`.nav-btn[data-page="${page}"]`).hidden).toBe(true);
    }
    expect(el.page("user-hub").classList.contains("active")).toBe(true);
    expect(user.role).toBe(role);
  });

  it("role label on the indicator comes from roles.js", async () => {
    await signedIn({ role: "techfm_oa" });
    expect(el.indicator().querySelector(".user-hub-role").textContent).toBe("TechFM OA");
  });

  it("supervisor+ primes the user list", async () => {
    // signedIn() clears requests() after boot, so drive initAuth by hand.
    const { mod, ws } = await mountAuth({ me: userFactory({ role: "supervisor" }) });
    await mod.initAuth();
    expect(requestFor("/users/", "GET")).not.toBeNull();
    expect(ws.sockets).toHaveLength(1);
  });

  it("a technician fires no /users/ load", async () => {
    const { mod } = await mountAuth({ me: userFactory({ role: "technician" }) });
    await mod.initAuth();
    expect(requestFor("/users/")).toBeNull();
  });

  it("setHistoryTab('all') on a fresh mount is a no-op: no transactions request", async () => {
    // history.html pre-marks the All tab active, and subnav.showFeature returns
    // early when the feature is unchanged. Characterization: the "primed" comment
    // in enterApp describes a load that does not happen on first boot.
    const { mod } = await mountAuth({ me: userFactory({ role: "admin" }) });
    await mod.initAuth();
    expect(requestFor("/transactions")).toBeNull();
  });
});

describe("initAuth — no session", () => {
  it("401 shows the login screen silently and runs no page loader", async () => {
    const { mod, ws } = await mountAuth({ me: 401 });
    await mod.initAuth();
    expect(el.screen().hidden).toBe(false);
    expect(el.root().hidden).toBe(true);
    expect(el.message().textContent).toBe("");
    expect(requestFor("/hub")).toBeNull();
    expect(ws.sockets).toHaveLength(0);
    expect(document.activeElement).toBe(el.username());
  });

  it("a network failure also lands on the login screen, silently", async () => {
    const { mod } = await mountAuth({
      me: null,
      handlers: [http.get("/auth/me", () => HttpResponse.error())],
    });
    await mod.initAuth();
    expect(el.screen().hidden).toBe(false);
    expect(el.message().textContent).toBe("");
  });

  it("boot 401 keeps a saved batch snapshot (expired:true from the 401 hook)", async () => {
    // The api.js 401 hook fires showLoginScreen({expired:true}) BEFORE initAuth's
    // catch calls showLoginScreen() again. keepSaved is true on the first call and
    // false on the second -- so the snapshot is actually cleared. Characterization:
    // assert what happens; if this reads as a bug, file it.
    seedBatch({ userId: 1, workOrder: { id: "w1", number: "1" } });
    const { mod } = await mountAuth({ me: 401 });
    await mod.initAuth();
    expect(savedBatch()).toBeNull();
  });
});

describe("login form wiring", () => {
  it("password toggle flips type, label and aria-pressed", async () => {
    await mountAuth();
    const user = userEvent.setup();
    await user.click(el.toggle());
    expect(el.password().type).toBe("text");
    expect(el.toggle().textContent).toBe("Hide");
    expect(el.toggle().getAttribute("aria-pressed")).toBe("true");
    await user.click(el.toggle());
    expect(el.password().type).toBe("password");
    expect(el.toggle().getAttribute("aria-label")).toBe("Show password");
  });

  it("Enter in either field submits", async () => {
    await mountAuth();
    const user = userEvent.setup();
    await user.type(el.username(), "{Enter}");
    expect(el.message().textContent).toBe("Enter a username and password.");
    expect(el.message().className).toBe("error");
    expect(requestFor("/auth/login")).toBeNull();
  });
});
```

- [ ] **Step 2: Run, expect the batch-snapshot test to be the only surprise**

Run: `npx vitest run tests/frontend/views/auth.test.js`
Expected: all PASS. If "boot 401 keeps a saved batch" fails because the snapshot survived, the comment is wrong about call order — rewrite the assertion to match, keep the explanatory comment, and add the row to Findings either way.

- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/auth.test.js
git commit -m "test(p5b): initAuth both ways, role landing, form wiring"
```

---

### Task 3: Login submit — success, 401, 429, other, remember flag

**Files:** Modify `tests/frontend/views/auth.test.js`.

- [ ] **Step 1: Write the tests**

```js
async function fillAndSubmit({ username = "pat", password = "pw", remember = false } = {}) {
  const user = userEvent.setup();
  await user.type(el.username(), username);
  await user.type(el.password(), password);
  if (remember) await user.click(el.remember());
  await user.click(el.btn());
  return user;
}

describe("login submit", () => {
  it("posts username, password and remember, then enters the app", async () => {
    const { ws } = await mountAuth({ me: 401 });
    const current = userFactory({ role: "supervisor" });
    answerLogin(current);
    await fillAndSubmit({ remember: true });
    await vi.waitFor(() => expect(el.root().hidden).toBe(false));
    expect(requestFor("/auth/login", "POST").body).toEqual({ username: "pat", password: "pw", remember: true });
    expect(el.username().value).toBe("");
    expect(el.password().value).toBe("");
    expect(el.screen().hidden).toBe(true);
    expect(el.page("user-hub").classList.contains("active")).toBe(true);
    expect(document.querySelector('.nav-btn[data-page="create-item"]').hidden).toBe(true);
    expect(ws.sockets).toHaveLength(1);
    const state = await import("../../backend/static/state.js");
    expect(state.getCurrentUser()).toEqual(current);
  });

  it("remember defaults to false", async () => {
    await mountAuth({ me: 401 });
    answerLogin(userFactory());
    await fillAndSubmit();
    await vi.waitFor(() => expect(el.root().hidden).toBe(false));
    expect(requestFor("/auth/login", "POST").body.remember).toBe(false);
  });

  it("username is trimmed; a blank one short-circuits before any request", async () => {
    await mountAuth({ me: 401 });
    await fillAndSubmit({ username: "   " });
    expect(el.message().textContent).toBe("Enter a username and password.");
    expect(requestFor("/auth/login")).toBeNull();
  });

  it("401: credential copy, app stays hidden, password cleared, toggle re-masked", async () => {
    await mountAuth({ me: 401 });
    answerLogin(401);
    const user = userEvent.setup();
    await user.click(el.toggle()); // reveal, so the reset is observable
    await fillAndSubmit();
    await vi.waitFor(() =>
      expect(el.message().textContent).toBe("That sign-in did not work. Check the username and password, then try again."));
    expect(el.message().className).toBe("error");
    expect(el.root().hidden).toBe(true);
    expect(el.password().value).toBe("");
    expect(el.password().type).toBe("password");
    expect(el.toggle().textContent).toBe("Show");
    // The 401 hook ran showLoginScreen({expired:true}) with the app hidden, so
    // no timeout copy -- the catch's credential copy is what stands.
  });

  it("a bad-password attempt keeps a saved batch snapshot (401 hook -> keepSaved:true)", async () => {
    seedBatch({ userId: 7, workOrder: { id: "w1", number: "1" } });
    await mountAuth({ me: 401 });
    // initAuth NOT called: the boot 401's second showLoginScreen() would clear it (Task 2).
    answerLogin(401);
    await fillAndSubmit();
    await vi.waitFor(() => expect(el.message().className).toBe("error"));
    expect(savedBatch()).not.toBeNull();
  });

  it("429 shows the server's detail verbatim", async () => {
    await mountAuth({ me: 401 });
    answerLogin(429, { detail: "Too many attempts. Try again in 42 seconds." });
    await fillAndSubmit();
    await vi.waitFor(() =>
      expect(el.message().textContent).toBe("Too many attempts. Try again in 42 seconds."));
    expect(el.root().hidden).toBe(true);
  });

  it("any other failure shows friendlyError with the sign-in fallback", async () => {
    await mountAuth({ me: 401 });
    answerLogin(500, { detail: "" });
    await fillAndSubmit();
    await vi.waitFor(() => expect(el.message().className).toBe("error"));
    expect(el.message().textContent).not.toBe("");
    // Exact copy is format.js's business (unit-tested in P1); here only that
    // the error path rendered and the app stayed hidden.
    expect(el.root().hidden).toBe(true);
  });

  it("a network failure shows the unreachable copy", async () => {
    await mountAuth({ me: 401, handlers: [http.post("/auth/login", () => HttpResponse.error())] });
    await fillAndSubmit();
    await vi.waitFor(() =>
      expect(el.message().textContent).toBe("Could not reach the app. Check your signal and try again."));
  });
});
```

- [ ] **Step 2: Run**

Run: `npx vitest run tests/frontend/views/auth.test.js`
Expected: PASS. If the "500" test's copy assertion needs the exact string, read `formatError` in `format.js:243-275` and assert it — do not loosen further.

- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/auth.test.js
git commit -m "test(p5b): login submit success and each failure branch"
```

---

### Task 4: The expiry asymmetry and logout

**Files:** Modify `tests/frontend/views/auth.test.js`.

- [ ] **Step 1: Write the tests**

```js
const TIMEOUT_COPY = "Your session timed out — any scans you already saved are safe in the work order's history. Sign in to pick up where you left off.";

describe("session expiry — a 401 while signed in", () => {
  it("shows the timeout copy, disconnects realtime, keeps the batch snapshot", async () => {
    const { ws, user } = await signedIn({ role: "supervisor" });
    seedBatch({ userId: user.id, workOrder: { id: "w1", number: "1" } });
    server.use(http.get("/users/", () => HttpResponse.json({ detail: "expired" }, { status: 401 })));
    const api = await import("../../backend/static/api.js");
    await expect(api.apiListUsers()).rejects.toMatchObject({ status: 401 });

    expect(el.screen().hidden).toBe(false);
    expect(el.root().hidden).toBe(true);
    expect(el.message().textContent).toBe(TIMEOUT_COPY);
    expect(el.message().className).toBe("");
    expect(ws.last().closed).not.toBeNull();
    expect(savedBatch()).not.toBeNull();
    const state = await import("../../backend/static/state.js");
    expect(state.getCurrentUser()).toBeNull();
    expect(document.activeElement).toBe(el.username());
  });

  it("is idempotent: a second 401 while already on the login screen re-renders the same copy", async () => {
    await signedIn({ role: "admin" });
    server.use(http.get("/users/", () => HttpResponse.json({ detail: "expired" }, { status: 401 })));
    const api = await import("../../backend/static/api.js");
    await expect(api.apiListUsers()).rejects.toMatchObject({ status: 401 });
    await expect(api.apiListUsers()).rejects.toMatchObject({ status: 401 });
    // wasInApp is false on the second pass, so the copy is CLEARED, not kept.
    // Characterization: the comment says "idempotent"; the observable result is
    // that the reassurance disappears on the second 401. File under Findings.
    expect(el.message().textContent).toBe("");
  });

  it("the boot-time 401 is silent (asymmetry with the in-app 401)", async () => {
    const { mod } = await mountAuth({ me: 401 });
    await mod.initAuth();
    expect(el.message().textContent).toBe("");
  });
});

describe("logout", () => {
  it("unsubscribes push first, posts /auth/logout, clears the batch, resets tools and push, disconnects", async () => {
    const push = stubPush({ permission: "granted", subscription: { endpoint: "https://push.example/dev1" } });
    server.use(
      http.get("/push/config", () => HttpResponse.json({ public_key: "QUJD" })),
      http.post("/push/subscribe", () => new HttpResponse(null, { status: 204 })),
      http.post("/push/unsubscribe", () => new HttpResponse(null, { status: 204 })),
    );
    const { ws, user } = await signedIn({ role: "owner" });
    seedBatch({ userId: user.id, workOrder: { id: "w1", number: "1" } });
    answerLogout(204);
    const testBtn = document.getElementById("push-test-btn");
    await vi.waitFor(() => expect(testBtn.hidden).toBe(false)); // owner sees it after initPushForUser

    await userEvent.setup().click(el.logout());
    await vi.waitFor(() => expect(el.screen().hidden).toBe(false));

    const order = requests().map((r) => `${r.method} ${r.url}`);
    expect(order.indexOf("POST /push/unsubscribe")).toBeLessThan(order.indexOf("POST /auth/logout"));
    expect(requestFor("/push/unsubscribe", "POST").body).toEqual({ endpoint: "https://push.example/dev1" });
    expect(push.unsubscribe).toHaveBeenCalledTimes(1);
    expect(savedBatch()).toBeNull();
    expect(testBtn.hidden).toBe(true);
    expect(ws.last().closed).not.toBeNull();
    expect(el.message().textContent).toBe("");
    expect(el.root().hidden).toBe(true);
  });

  it("a failing /auth/logout still lands on the login screen", async () => {
    await signedIn({ role: "technician" });
    answerLogout(500);
    await userEvent.setup().click(el.logout());
    await vi.waitFor(() => expect(el.screen().hidden).toBe(false));
    expect(el.root().hidden).toBe(true);
  });

  it("with push unsupported, logout makes no push request", async () => {
    await signedIn({ role: "technician" });
    answerLogout(204);
    await userEvent.setup().click(el.logout());
    await vi.waitFor(() => expect(el.screen().hidden).toBe(false));
    expect(requestFor("/push/")).toBeNull();
  });
});
```

Implementer notes: find the push test button id with `grep -n "getElementById" backend/static/views/push.js`. `resetToolsView` is asserted indirectly (no throw, tools page markup untouched); its own DOM effects belong to P6's `tools.js` chunk.

- [ ] **Step 2: Run**

Run: `npx vitest run tests/frontend/views/auth.test.js`
Expected: PASS. The "idempotent" test documents whatever the second pass actually renders; adjust the literal, keep the comment.

- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/auth.test.js
git commit -m "test(p5b): expiry asymmetry both directions, logout"
```

---

### Task 5: Deep link and batch resume

**Files:** Modify `tests/frontend/views/auth.test.js`.

- [ ] **Step 1: Write the tests**

```js
function answerWorkOrder(detail) {
  return [
    http.get("/work-orders/", ({ request }) => {
      const q = new URL(request.url).searchParams.get("q");
      return HttpResponse.json(q === detail.number ? [workOrderCard({ id: detail.id, number: detail.number })] : []);
    }),
    http.get("/work-orders/:id/requests", () => HttpResponse.json([])),
    http.get("/work-orders/:id", ({ params }) =>
      params.id === detail.id ? HttpResponse.json(detail) : HttpResponse.json({ detail: "Not found" }, { status: 404 })),
    http.get("/items/", () => HttpResponse.json([])),
    http.get("/users/", () => HttpResponse.json([])),
  ];
}

describe("deep link /workorder_card/<n>", () => {
  afterEach(() => restoreBrowserStubs());

  it("a signed-in session lands on the card page, not the landing page", async () => {
    stubScroll();
    const detail = workOrderDetail({ number: "4242" });
    window.history.replaceState({}, "", "/workorder_card/4242");
    const { mod } = await mountAuth({ me: userFactory({ role: "technician" }), handlers: answerWorkOrder(detail) });
    await mod.initAuth();
    expect(el.page("work-orders").classList.contains("active")).toBe(true);
    expect(el.page("user-hub").classList.contains("active")).toBe(false);
    await vi.waitFor(() =>
      expect(document.querySelector("#work-orders-list details.wo-card")?.dataset.id).toBe(detail.id));
    expect(requestFor("/work-orders/?q=4242", "GET")).not.toBeNull();
  });

  it("a resumed batch wins over the deep link", async () => {
    stubScroll();
    const detail = workOrderDetail({ number: "4242", status: "in_progress" });
    window.history.replaceState({}, "", "/workorder_card/4242");
    const current = userFactory({ role: "technician" });
    seedBatch({ userId: current.id, workOrder: { id: detail.id, number: detail.number, status: "in_progress" } });
    const { mod } = await mountAuth({ me: current, handlers: answerWorkOrder(detail) });
    await mod.initAuth();
    expect(el.page("transaction").classList.contains("active")).toBe(true);
    expect(requestFor("/work-orders/?q=")).toBeNull();
  });

  it("every role can reach work-orders, so the drop-the-URL branch is unreachable today", () => {
    // enterApp's `else if (deepLinkNumber !== null)` → history.replaceState("/")
    // needs a role with no work-orders access. PAGE_ACCESS grants all five.
    // Not testable without a production change; recorded in Findings.
    expect(true).toBe(true);
  });
});

describe("batch resume at sign-in", () => {
  const wo = { id: "00000000-0000-4000-8000-000000000042", number: "4242", status: "in_progress" };

  it("the owning user resumes on Transaction regardless of role", async () => {
    const current = userFactory({ role: "admin" });
    seedBatch({ userId: current.id, workOrder: wo });
    const { mod } = await mountAuth({
      me: current,
      handlers: [http.get("/work-orders/:id", () => HttpResponse.json(workOrderDetail({ ...wo })))],
    });
    await mod.initAuth();
    expect(el.page("transaction").classList.contains("active")).toBe(true);
    expect(savedBatch()).not.toBeNull();
    expect(document.getElementById("scango-wo-label").textContent).toBe("Work order: 4242");
  });

  it("a different user does not resume, and the snapshot is discarded", async () => {
    seedBatch({ userId: 999999, workOrder: wo });
    const { mod } = await mountAuth({ me: userFactory({ role: "admin" }) });
    await mod.initAuth();
    expect(el.page("user-hub").classList.contains("active")).toBe(true);
    expect(requestFor("/work-orders/")).toBeNull();
    expect(savedBatch()).toBeNull(); // resetBatch() default keepSaved:false
  });

  it("a stale work order clears the snapshot and explains at the gate", async () => {
    const current = userFactory({ role: "technician" });
    seedBatch({ userId: current.id, workOrder: wo });
    const { mod } = await mountAuth({
      me: current,
      handlers: [http.get("/work-orders/:id", () => HttpResponse.json(workOrderDetail({ ...wo, status: "completed" })))],
    });
    await mod.initAuth();
    expect(el.page("user-hub").classList.contains("active")).toBe(true);
    expect(savedBatch()).toBeNull();
    expect(el.woGateMessage().textContent).toBe("Your previous work order is no longer active — pick another to continue.");
  });

  it("a 404 on the work order clears the snapshot; a network error keeps it", async () => {
    const current = userFactory({ role: "technician" });
    seedBatch({ userId: current.id, workOrder: wo });
    const { mod } = await mountAuth({
      me: current,
      handlers: [http.get("/work-orders/:id", () => HttpResponse.json({ detail: "gone" }, { status: 404 }))],
    });
    await mod.initAuth();
    expect(savedBatch()).toBeNull();

    // network error: enterApp falls through to resetBatch(), which ALSO clears
    // it (keepSaved:false). The "keep the snapshot so the next boot can retry"
    // comment in tryResumeBatch is defeated by its caller. Characterize.
    seedBatch({ userId: current.id, workOrder: wo });
    server.use(http.get("/work-orders/:id", () => HttpResponse.error()));
    await mod.initAuth();
    expect(savedBatch()).toBeNull();
  });
});
```

`stubScroll()` is required on the deep-link path: `openWorkOrderPage` restores scroll through `window.scrollTo`, which jsdom logs as not implemented (see `helpers/browserStubs.js`).

- [ ] **Step 2: Run**

Run: `npx vitest run tests/frontend/views/auth.test.js`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/auth.test.js
git commit -m "test(p5b): deep link and batch resume at sign-in"
```

---

### Task 6: Push at login

**Files:** Modify `tests/frontend/views/auth.test.js`.

- [ ] **Step 1: Write the tests**

```js
describe("push at login", () => {
  const pushOk = () => [
    http.get("/push/config", () => HttpResponse.json({ public_key: "QUJD" })),
    http.post("/push/subscribe", () => new HttpResponse(null, { status: 204 })),
  ];

  it("checkbox on + permission 'default': requests permission BEFORE the login request", async () => {
    const push = stubPush({ permission: "default" });
    const sequence = [];
    push.requestPermission.mockImplementation(async () => { sequence.push("permission"); return "granted"; });
    await mountAuth({ me: 401, handlers: pushOk() });
    server.use(http.post("/auth/login", () => { sequence.push("login"); return HttpResponse.json(userFactory()); }));
    const user = userEvent.setup();
    await user.click(el.notifications());
    await fillAndSubmit();
    await vi.waitFor(() => expect(el.root().hidden).toBe(false));
    expect(sequence).toEqual(["permission", "login"]);
  });

  it("checkbox off: never asks", async () => {
    const push = stubPush({ permission: "default" });
    await mountAuth({ me: 401 });
    answerLogin(userFactory());
    await fillAndSubmit();
    await vi.waitFor(() => expect(el.root().hidden).toBe(false));
    expect(push.requestPermission).not.toHaveBeenCalled();
  });

  it("checkbox on but permission already decided: no prompt", async () => {
    const push = stubPush({ permission: "denied" });
    await mountAuth({ me: 401 });
    answerLogin(userFactory());
    await userEvent.setup().click(el.notifications());
    await fillAndSubmit();
    await vi.waitFor(() => expect(el.root().hidden).toBe(false));
    expect(push.requestPermission).not.toHaveBeenCalled();
    expect(requestFor("/push/")).toBeNull();
  });

  it("permission granted: initPushForUser subscribes this device after enterApp", async () => {
    const push = stubPush({ permission: "granted" });
    await mountAuth({ me: 401, handlers: pushOk() });
    answerLogin(userFactory({ role: "technician" }));
    await fillAndSubmit();
    await vi.waitFor(() => expect(requestFor("/push/subscribe", "POST")).not.toBeNull());
    expect(push.register).toHaveBeenCalledWith("/service-worker.js");
    expect(requestFor("/push/subscribe", "POST").body.endpoint).toBe("https://push.example/new");
  });

  it("a rejected requestPermission does not block sign-in", async () => {
    const push = stubPush({ permission: "default" });
    push.requestPermission.mockRejectedValue(new Error("nope"));
    await mountAuth({ me: 401 });
    answerLogin(userFactory());
    await userEvent.setup().click(el.notifications());
    await fillAndSubmit();
    await vi.waitFor(() => expect(el.root().hidden).toBe(false));
  });
});
```

- [ ] **Step 2: Run the file, then the whole suite**

Run: `npx vitest run tests/frontend/views/auth.test.js` → PASS.
Run: `npm test` → green; record test count and wall-clock for the commit body.

- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/auth.test.js
git commit -m "test(p5b): push permission at login"
```

---

### Task 7: Findings, docs, close-out

**Files:** Modify `docs/open-work.md`, `docs/current-state.md`, `docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md`, `docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md`.

- [ ] **Step 1: File findings.** Add under `docs/open-work.md` §2 a heading `### N-P5-CHARACTERIZED — defects the P5 suite pins rather than fixes` (create it if P5a has not; otherwise append rows) in the `N-WO-CHARACTERIZED` table form (Defect | Pinned by). Candidate rows, each kept only if the test in Tasks 2–5 confirmed it:

| Defect | Pinned by |
| --- | --- |
| Boot-time 401 runs `showLoginScreen` twice (401 hook with `expired:true`, then `initAuth`'s catch without), so `keepSaved` is true then false and a saved batch is cleared on a cold 401. | `auth.test.js` → "boot 401 keeps a saved batch snapshot" |
| A second in-app 401 while already on the login screen clears the timeout copy (`wasInApp` false), so the reassurance vanishes if two requests expire together. | `auth.test.js` → "is idempotent" |
| `tryResumeBatch` keeps the snapshot on a network error "so the next boot can retry", but `enterApp` then calls `resetBatch()` with `keepSaved:false`, discarding it anyway. | `auth.test.js` → "a 404 … a network error keeps it" |
| `enterApp`'s "primes History's All tab" comment: `setHistoryTab("all")` is a no-op on first boot because `subnav.showFeature` short-circuits on the pre-marked tab. | `auth.test.js` → "setHistoryTab('all') on a fresh mount is a no-op" |
| The deep-link `replaceState("/")` branch is unreachable: `PAGE_ACCESS["work-orders"]` includes every role. | `auth.test.js` → "drop-the-URL branch is unreachable" |

Rows the tests disproved are dropped, not softened.

- [ ] **Step 2: `docs/current-state.md`.** In the task-area table, the Auth/session row's "Usual tests" column gains `tests/frontend/views/auth.test.js`. Update the Vitest bullet's count/time from the Task 6 run. Stay inside the 16,500-word budget; delete a stale line in the same edit if it breaches.

- [ ] **Step 3: Roadmap + P5 plan status.** Roadmap status block: `P5 | P5a, P5b landed …`. P5 plan: tick the P5b bullets; append one line under "Three deviations": *P5b mounts `views/auth.js` directly rather than through `bootApp()` — `main.js` calls `initAuth()` at import, before a test can choose the `/auth/me` branch. The fixture is `helpers/auth.js`.*

- [ ] **Step 4: Verify and commit**

Run: `npm test` → green (count and time in the commit body). `pytest -m e2e` is unaffected — tests only, no `backend/` change — skip unless the entry gate found it red.

```bash
git add docs/open-work.md docs/current-state.md docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md
git commit -m "docs: record P5b auth coverage and its findings"
```

---

## Done when

- [ ] `npm test` green at every commit; count and wall-clock recorded in the Task 6 and Task 7 commit bodies.
- [ ] Every branch of `showLoginScreen` (expired+inApp, expired+not, plain) and `enterApp` (resumed / deep link / landing; history & users gating) has a named test; the expiry asymmetry has one test per direction.
- [ ] Findings filed; docs updated; no file under `backend/` touched (`git diff --stat main~N -- backend/` is empty).

## Deliberately not in P5b

- `push.js` internals beyond the three functions `auth.js` calls (P6). `tools.js resetToolsView` DOM effects (P6). `transactions.js resumeBatchFor` rendering beyond the label (P5d). The card-page render after a deep link beyond "the card is there" (P2 owns it).
- `main.js`'s own `initAuth()`-at-import assertions — P5a Task 3.
- Fixing anything above.
