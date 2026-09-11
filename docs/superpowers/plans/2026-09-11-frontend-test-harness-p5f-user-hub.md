# Frontend Test Harness — P5f (`views/userHub.js` + `helpers/hub.js`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status: NOT STARTED. Do not begin until P5a–P5e are committed on `main` and the user gives an explicit go-ahead.**

**Goal:** Characterization coverage for `backend/static/views/userHub.js` (569 lines) — the hub tab shell — and the shared `helpers/hub.js` fixture the roadmap promises P6, so the eight `hub*.js` sub-modules become eight small test files rather than eight setups.

**Architecture:** Tests only. `userHub.js` owns one `GET /hub` fetch, the clock mount, tab switching, and the lazily fetched crew / admin / timesheets / graphs / report payloads; the sub-modules render into the panels. It imports `nav.js` and the work-order barrel (for the My Work Orders tab and the graphs drill-down) but fetches nothing at import — `loadUserHub()` is the entry point. Two timers matter: the clock's 1 s tick and the 60 s crew safety interval, both started by `loadUserHub` and stopped only by `visibilitychange` → hidden. Every test runs on fake timers and the fixture's `stopClock()` simulates the hide so the file can assert `vi.getTimerCount() === 0` in `afterEach` — the leak guard the parent plan asks for. Realtime is driven through the fake socket exactly as P2 did.

**Tech Stack:** Vitest, jsdom, @testing-library/dom, @testing-library/user-event, msw.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3
**Parent plan:** `docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md` (P5f bullets are the requirement set)
**Depends on:** P5a (`hubPayload()` factory, `pageHandlers()`, media stubs), P5d (`helpers/requests.js`), P2 (`helpers/fakeSocket.js`).

## Global constraints

- Tests only. No edit under `backend/static/` or `backend/app/`.
- Characterization, not correction.
- No `vi.mock` of any app module. Seams: `fetch` (MSW), `WebSocket` (fake), timers (fake in every test), `document.hidden` (property override in the fixture only).
- `onUnhandledRequest: "error"` stays on. The hub fires up to six endpoints by role; the fixture answers each off a factory, and a test overrides by passing `handlers` (registered first).
- `mountView()` before import — `userHub.js` captures 11 element ids at import.
- Every new factory passes the drift guard in `unit/api.endpoints.test.js` against `backend/app/schemas/hub.py`; rows added in the same commit.
- `afterEach` in `userHub.test.js` asserts `vi.getTimerCount()` is 0 after `stopClock()`.
- Commit messages end with the attribution lines the session provides.

## Entry gate — verify before Task 1

- [ ] P5a–P5e on `main`; `helpers/requests.js`, `helpers/fakeSocket.js`, `helpers/media.js` exist; `hubPayload()` is in `helpers/factories.js` (P5a added it; `clock.total_minutes_today` is a `@computed_field` on `HubClock`, so the drift guard's top-level check does not see it — verified 2026-09-11, no action).
- [ ] `npm test` green to completion; record count and wall-clock.
- [ ] No other session mid-commit in this checkout.

## Drift from the P5 plan's P5f bullets, decided here

| Bullet | Reality | Action |
| --- | --- | --- |
| "`destroyHubGraphs` on tab change" | `destroyHubGraphs()` is an empty function by design (SVG, nothing to dispose). | Task 5 asserts a graphs → dashboard → graphs round trip re-renders without throwing; recorded, not faked. |
| "each tab's mount function called with its payload" | Module-private; observable as each panel's rendered root. | Assert the root each sub-module paints (`.hub-priorities`, `#hub-crew-mount` children, `.hub-timesheet-table`, `.hub-graphs`, `.hub-report-loading`); internals are P6's. |
| "a failing tab renders its error without taking the others down" | True per tab, with a background/foreground split. | Task 4 covers crew, admin, timesheets, graphs, report, each foreground and background. |

## Requests by role (what the fixture must answer)

| Role | On `loadUserHub()` | Lazily |
| --- | --- | --- |
| technician | `GET /hub` | `GET /work-orders/?mine=true&limit=10` (My Work Orders tab) |
| supervisor | `GET /hub`, `GET /hub/crew` | `GET /hub/timesheets[?start&end]`, work orders as above |
| techfm_oa | + `GET /hub/admin` | + `GET /hub/graphs?weeks=N`; work orders `GET /work-orders/?limit=10` (unscoped) |
| admin, owner | same as techfm_oa | + `GET /hub/report` |

---

### Task 1: Hub factories, drift rows, and `helpers/hub.js`

**Files:**
- Modify: `tests/frontend/helpers/factories.js` (append `hubCrew`, `hubAdmin`, `hubTimesheets`, `hubGraphs`), `tests/frontend/unit/api.endpoints.test.js` (four rows)
- Create: `tests/frontend/helpers/hub.js`
- Test: `tests/frontend/views/userHub.test.js` (smoke)

**Interfaces:**
- `hubCrew(overrides)`, `hubAdmin(overrides)`, `hubTimesheets(overrides)`, `hubGraphs(overrides)` → valid, minimal payloads for `/hub/crew`, `/hub/admin`, `/hub/timesheets`, `/hub/graphs`.
- `helpers/hub.js` produces:
  - `mountHub({ role = "technician", hub = null, crew = null, admin = null, timesheets = null, graphs = null, report = 500, workOrders = [], handlers = [] })` → `{ mod, currentUser, payload }`. Registers every hub endpoint off the factories (with `hub.user.role` forced to `role`), `/hub/report` as a 500 unless a payload is given, `GET /work-orders/` answering `workOrders`, and records the parsed query of every request. Installs media stubs (the hub imports `nav.js`) and fake timers. Does **not** load.
  - `openHub(opts)` → `mountHub` then `await mod.loadUserHub()`.
  - `stopClock()` — simulates `visibilitychange` with `document.hidden === true`, then restores `document.hidden`. Stops the clock tick and the safety interval; returns nothing.
  - `restoreHub()` — `stopClock()`, restore fetch, media stubs, real timers.
  - `connectHub()` — `installFakeWebSocket()`, import `realtime.js`, `setActivePageGetter(() => "user-hub")`, `connectRealtime()`, `emitOpen()`; returns `{ ws, emit(type, extra) }`.
  - `el`: `page`, `clockMount`, `tabs`, `tab(name)`, `panel(name)`, `crewMount`, `adminMount`, `prioritiesMount`.
  - `queries(fragment)` → array of parsed query objects for every recorded request whose url includes `fragment`.

- [ ] **Step 1: Write the smoke test**

```js
// tests/frontend/views/userHub.test.js
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { requestFor, requests, clearRequests } from "../helpers/requests.js";
import { connectHub, el, mountHub, openHub, queries, restoreHub, stopClock } from "../helpers/hub.js";
import { hubAdmin, hubCrew, hubGraphs, hubPayload, hubTimesheets, workOrderCard } from "../helpers/factories.js";

afterEach(() => {
  stopClock();                          // the hide: clears the tick and the safety interval
  expect(vi.getTimerCount()).toBe(0);   // checked while fake timers are still on; anything left is a leak
  restoreHub();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

describe("mountHub", () => {
  it("mounts with the dashboard tab active and nothing fetched", async () => {
    const { mod } = await mountHub();
    expect(typeof mod.loadUserHub).toBe("function");
    expect(el.tab("dashboard").classList.contains("active")).toBe(true);
    expect(requests()).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run to verify it fails** — `npx vitest run tests/frontend/views/userHub.test.js` → FAIL on the missing helper.

- [ ] **Step 3: Append the four factories**

```js
// --- Hub sub-payloads (backend/app/schemas/hub.py) --------------------------
// Minimal-but-valid: one technician on the crew board, one community in the
// graphs, one row in the timesheet. Tests override the field under test.
export function hubCrew(overrides = {}) {
  return {
    server_now: "2026-09-10T12:00:00Z",
    led: { total: 1, in_progress: 1, ready_to_complete: 0 },
    priority: { assigned: 0, unassigned: 0 },
    crew_on_clock: 0,
    crew_total: 1,
    crew_minutes_today: 0,
    technicians: [{
      user: { id: uuid(), first_name: "Crew", last_name: "One", role: "technician" },
      running_session: null, minutes_today: 0, assigned: 1, in_progress: 0, ready_to_complete: 0,
      last_worked: null, flags: [],
    }],
    attention: [],
    ...overrides,
  };
}

export function hubAdmin(overrides = {}) {
  return {
    server_now: "2026-09-10T12:00:00Z",
    supervisor_minutes_today: 0,
    technician_minutes_today: 0,
    pipeline: { created: 0, assigned: 0, in_progress: 0, ready_to_complete: 0, completed: 0, review: 0 },
    priority: { assigned: 0, unassigned: 0 },
    on_the_clock: [],
    exceptions: { inventory_recounts: 0, missing_item_price: 0, catalogue_requests: 0, admin_review_queue: 0, stale_work_orders: 0 },
    billing: { materials_total: "0", labor_total: "0", total: "0", avg_days_to_complete: null, completed_per_day: [0, 0, 0, 0, 0, 0, 0], legacy_live_count: null },
    ...overrides,
  };
}

export function hubTimesheets(overrides = {}) {
  return {
    range: { start: "2026-09-07", end: "2026-09-13" },
    rows: [{ user: { id: uuid(), first_name: "Crew", last_name: "One", role: "technician" }, days: [], total_minutes: 0 }],
    crew_totals_by_day: [],
    ...overrides,
  };
}

export function hubGraphs(overrides = {}) {
  return {
    generated_at: "2026-09-10T12:00:00Z",
    weeks: 12,
    statuses: [{ key: "assigned", label: "Assigned" }],
    communities: [{ key: "maple", label: "Maple Ridge", total: 1, counts: { assigned: 1 }, service_types: [], priorities: [] }],
    duration: { range: { start: "2026-06-18", end: "2026-09-10" }, buckets: [] },
    ...overrides,
  };
}
```

Add to the drift table: `["hubCrew", "backend/app/schemas/hub.py"], ["hubAdmin", ...], ["hubTimesheets", ...], ["hubGraphs", ...]`. The guard checks top-level keys only; nested shapes were read off the schema on 2026-09-11.

- [ ] **Step 4: Write `helpers/hub.js`**

```js
// tests/frontend/helpers/hub.js
//
// The User Hub fixture -- the shared mount helper the roadmap promises P6.
// userHub.js fetches nothing at import; loadUserHub() fires GET /hub and, by
// role, the crew and admin summaries; the other tabs fetch lazily. Every
// endpoint is answered off a factory here so a sub-module test (P6) is one
// `openHub({role, ...})` call and its assertions.
//
// Two timers start on load -- the clock's 1 s tick and the 60 s safety
// refresh -- and only `visibilitychange` (hidden) stops them. `stopClock()`
// fakes that hide; every test runs on fake timers and asserts no timer is
// left behind.

import { expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "./handlers.js";
import { mountView } from "./shell.js";
import { setTestUser } from "./session.js";
import { restoreMediaStubs, stubPermissions, stubUserMedia } from "./media.js";
import { startRecording, stopRecording, clearRequests, requests } from "./requests.js";
import { installFakeWebSocket } from "./fakeSocket.js";
import { hubAdmin, hubCrew, hubGraphs, hubPayload, hubTimesheets } from "./factories.js";

const byId = (id) => () => document.getElementById(id);
export const el = {
  page: byId("user-hub-page"), clockMount: byId("hub-clock-mount"), tabs: byId("hub-tabs"),
  tab: (name) => document.getElementById(`hub-tab-${name}`),
  panel: (name) => document.getElementById(`hub-tabpanel-${name}`),
  crewMount: byId("hub-crew-mount"), adminMount: byId("hub-admin-mount"), prioritiesMount: byId("hub-priorities-mount"),
};

export const queries = (fragment) => requests()
  .filter((r) => r.url.includes(fragment))
  .map((r) => Object.fromEntries(new URL(r.url, "http://t").searchParams));

const answer = (value, status = 200) =>
  typeof value === "number"
    ? HttpResponse.json({ detail: "hub error" }, { status: value })
    : HttpResponse.json(value, { status });

let ws = null;
let hiddenRestore = null;

export async function mountHub({
  role = "technician", hub = null, crew = null, admin = null, timesheets = null, graphs = null,
  report = 500, workOrders = [], handlers = [],
} = {}) {
  vi.useFakeTimers();
  const currentUser = await setTestUser({ role });
  const payload = hub ?? hubPayload();
  payload.user = { ...payload.user, id: currentUser.id, role };
  server.use(
    ...handlers,
    http.get("/hub/crew", () => answer(crew ?? hubCrew())),
    http.get("/hub/admin", () => answer(admin ?? hubAdmin())),
    http.get("/hub/timesheets", () => answer(timesheets ?? hubTimesheets())),
    http.get("/hub/graphs", () => answer(graphs ?? hubGraphs())),
    http.get("/hub/report", () => answer(report)),
    http.get("/hub", () => answer(payload)),
    http.get("/work-orders/", () => HttpResponse.json(workOrders)),
  );
  stubUserMedia();
  stubPermissions("prompt");
  startRecording();
  const mod = await mountView("views/userHub.js");
  clearRequests();
  return { mod, currentUser, payload };
}

export async function openHub(opts = {}) {
  const mounted = await mountHub(opts);
  await mounted.mod.loadUserHub();
  return mounted;
}

export function stopClock() {
  if (hiddenRestore) return;
  const desc = Object.getOwnPropertyDescriptor(Document.prototype, "hidden");
  Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
  document.dispatchEvent(new Event("visibilitychange"));
  hiddenRestore = () => {
    delete document.hidden;
    if (desc) Object.defineProperty(Document.prototype, "hidden", desc);
  };
}

export function restoreHub() {
  stopClock();
  if (hiddenRestore) { hiddenRestore(); hiddenRestore = null; }
  if (ws) { ws.restore(); ws = null; }
  stopRecording();
  restoreMediaStubs();
  vi.useRealTimers();
}

// Bring the realtime transport up on the hub page, as P2 did for Work Orders.
export async function connectHub() {
  ws = installFakeWebSocket();
  const realtime = await import("../../backend/static/realtime.js");
  realtime.setActivePageGetter(() => "user-hub");
  realtime.connectRealtime();
  ws.last().emitOpen();
  return {
    ws,
    emit: (type, extra = {}) => ws.last().emitMessage(JSON.stringify({ type, id: null, req: null, ...extra })),
  };
}
```

`document.hidden` lives on `Document.prototype` in jsdom; the instance override shadows it and `delete` removes the shadow. If `vi.getTimerCount()` is not 0 after `stopClock()` in the smoke test, the hide did not reach the listener — check `document.hidden` reads `true` inside the handler before touching anything else.

- [ ] **Step 5: Run the smoke test and the drift test** → PASS.
- [ ] **Step 6: Commit**

```bash
git add tests/frontend/helpers/factories.js tests/frontend/unit/api.endpoints.test.js tests/frontend/helpers/hub.js tests/frontend/views/userHub.test.js
git commit -m "test(p5f): hub factories and the shared hub fixture"
```

---

### Task 2: `loadUserHub()` per role — tabs, clock placement, requests, labels

**Files:** Modify `tests/frontend/views/userHub.test.js`.

- [ ] **Step 1: Write the tests**

```js
describe("loadUserHub by role", () => {
  it.each([
    ["technician", { timesheets: false, graphs: false, report: false }, ["/hub"], "My Work Orders (0)", "before"],
    ["supervisor", { timesheets: true, graphs: false, report: false }, ["/hub", "/hub/crew"], "My Work Orders (0)", "before"],
    ["techfm_oa", { timesheets: true, graphs: true, report: false }, ["/hub", "/hub/crew", "/hub/admin"], "Work Orders", "after"],
    ["admin", { timesheets: true, graphs: true, report: true }, ["/hub", "/hub/crew", "/hub/admin"], "Work Orders", "after"],
    ["owner", { timesheets: true, graphs: true, report: true }, ["/hub", "/hub/crew", "/hub/admin"], "Work Orders", "after"],
  ])("%s: tabs %j, requests %j, label %s, clock %s tabs", async (role, tabs, expected, label, clockPos) => {
    await openHub({ role, hub: hubPayload({ mine_total: 0 }) });
    expect(requests().map((r) => r.url)).toEqual(expected);
    expect(el.tab("timesheets").hidden).toBe(!tabs.timesheets);
    expect(el.tab("graphs").hidden).toBe(!tabs.graphs);
    expect(el.tab("report").hidden).toBe(!tabs.report);
    expect(el.tab("work-orders").textContent).toBe(label);
    const order = Array.from(el.page().children).map((c) => c.id);
    expect(order.indexOf("hub-clock-mount") < order.indexOf("hub-tabs")).toBe(clockPos === "before");
    expect(el.panel("dashboard").querySelector(".hub-priorities")).not.toBeNull();
    expect(el.clockMount().querySelector(".hub-clock-status")).not.toBeNull();
  });

  it("a technician must never fire /hub/admin or /hub/crew, even after a tab tour", async () => {
    await openHub({ role: "technician" });
    await user().click(el.tab("work-orders"));
    await user().click(el.tab("dashboard"));
    expect(requestFor("/hub/admin")).toBeNull();
    expect(requestFor("/hub/crew")).toBeNull();
  });

  it("mine_total drives the technician label; a second load updates it", async () => {
    const { mod } = await openHub({ role: "technician", hub: hubPayload({ mine_total: 3 }) });
    expect(el.tab("work-orders").textContent).toBe("My Work Orders (3)");
    server.use(http.get("/hub", () => HttpResponse.json(hubPayload({ mine_total: 5, user: { id: "same", role: "technician" } }))));
    await mod.loadUserHub();
    expect(el.tab("work-orders").textContent).toBe("My Work Orders (5)");
  });

  it("first load paints a skeleton grid in the dashboard; a return visit does not", async () => {
    let release;
    const { mod } = await mountHub({ role: "technician", handlers: [http.get("/hub", () =>
      new Promise((r) => { release = () => r(HttpResponse.json(hubPayload())); }))] });
    const first = mod.loadUserHub();
    expect(el.panel("dashboard").querySelector(".skel-grid")).not.toBeNull();
    release(); await first;
    const second = mod.loadUserHub();
    expect(el.panel("dashboard").querySelector(".skel-grid")).toBeNull();
    release(); await second;
  });

  it("a failing /hub writes the error into the clock mount and stops", async () => {
    const { mod } = await mountHub({ role: "supervisor", handlers: [http.get("/hub", () => HttpResponse.json({ detail: "x" }, { status: 500 }))] });
    await mod.loadUserHub();
    expect(el.clockMount().querySelector("p.error")).not.toBeNull();
    expect(requestFor("/hub/crew")).toBeNull();
    expect(vi.getTimerCount()).toBe(0); // nothing started
  });

  it("a user change resets to the dashboard tab and clears the lazy payloads", async () => {
    const { mod } = await openHub({ role: "supervisor" });
    await user().click(el.tab("timesheets"));
    await vi.waitFor(() => expect(requestFor("/hub/timesheets")).not.toBeNull());
    expect(el.panel("timesheets").querySelector(".hub-timesheet-table")).not.toBeNull();
    server.use(http.get("/hub", () => HttpResponse.json(hubPayload({ user: { id: "someone-else", role: "supervisor" } }))));
    clearRequests();
    await mod.loadUserHub();
    expect(el.tab("dashboard").classList.contains("active")).toBe(true);
    expect(el.panel("timesheets").children).toHaveLength(0);
  });

  it("a role downgrade off a hidden tab lands on the dashboard", async () => {
    const { mod } = await openHub({ role: "techfm_oa" });
    await user().click(el.tab("graphs"));
    await vi.waitFor(() => expect(requestFor("/hub/graphs")).not.toBeNull());
    server.use(http.get("/hub", () => HttpResponse.json(hubPayload({ user: { id: "u", role: "supervisor" } }))));
    await mod.loadUserHub();
    expect(el.tab("graphs").hidden).toBe(true);
    expect(el.tab("dashboard").classList.contains("active")).toBe(true);
    expect(el.panel("graphs").children).toHaveLength(0);
  });
});
```

The `user: { id: "same" }` override in the third test must match the id the fixture forced on the first payload; use the `payload.user.id` returned by `openHub` instead of a literal.

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/userHub.test.js
git commit -m "test(p5f): loadUserHub per role, labels, clock placement, resets"
```

---

### Task 3: Tab switching and the lazy tabs

**Files:** Modify `tests/frontend/views/userHub.test.js`.

- [ ] **Step 1: Write the tests**

```js
describe("tabs", () => {
  it("clicking a tab moves active/aria-selected and shows exactly one panel", async () => {
    await openHub({ role: "technician" });
    await user().click(el.tab("work-orders"));
    expect(el.tab("work-orders").getAttribute("aria-selected")).toBe("true");
    expect(el.tab("dashboard").getAttribute("aria-selected")).toBe("false");
    for (const name of ["dashboard", "timesheets", "work-orders", "graphs", "report"]) {
      expect(el.panel(name).hidden).toBe(name !== "work-orders");
    }
  });

  it("My Work Orders mounts the capped list: mine=true for a technician, unscoped for techfm_oa+", async () => {
    await openHub({ role: "technician", workOrders: [workOrderCard()] });
    await user().click(el.tab("work-orders"));
    await vi.waitFor(() => expect(queries("/work-orders/")).toHaveLength(1));
    expect(queries("/work-orders/")[0]).toEqual({ mine: "true", limit: "10" });
    expect(el.panel("work-orders").querySelector(".hub-wo-list")).not.toBeNull();
    restoreHub();

    await openHub({ role: "admin" });
    await user().click(el.tab("work-orders"));
    await vi.waitFor(() => expect(queries("/work-orders/")).toHaveLength(1));
    expect(queries("/work-orders/")[0]).toEqual({ limit: "10" });
  });

  it("Timesheets fetches once, then re-renders from memory; a week change refetches with start/end", async () => {
    await openHub({ role: "supervisor" });
    await user().click(el.tab("timesheets"));
    await vi.waitFor(() => expect(queries("/hub/timesheets")).toHaveLength(1));
    expect(queries("/hub/timesheets")[0]).toEqual({});
    await user().click(el.tab("dashboard"));
    await user().click(el.tab("timesheets"));
    expect(queries("/hub/timesheets")).toHaveLength(1);
    await user().click(el.panel("timesheets").querySelector(".hub-timesheet-prev"));
    await vi.waitFor(() => expect(queries("/hub/timesheets")).toHaveLength(2));
    expect(Object.keys(queries("/hub/timesheets")[1]).sort()).toEqual(["end", "start"]);
  });

  it("Graphs fetches with weeks=12, re-renders from memory on return, and a range change refetches", async () => {
    await openHub({ role: "techfm_oa" });
    await user().click(el.tab("graphs"));
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(1));
    expect(queries("/hub/graphs")[0]).toEqual({ weeks: "12" });
    expect(el.panel("graphs").querySelector(".hub-graphs")).not.toBeNull();
    await user().click(el.tab("dashboard"));
    await user().click(el.tab("graphs"));           // background refetch, from memory first
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(2));
    await user().selectOptions(el.panel("graphs").querySelector(".hub-graphs-weeks"), "26");
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(3));
    expect(queries("/hub/graphs")[2]).toEqual({ weeks: "26" });
  });

  it("Graphs: a community tab click re-renders from memory; the choice survives a range change", async () => {
    const graphs = hubGraphs({ communities: [
      { key: "maple", label: "Maple", total: 5, counts: { assigned: 5 }, service_types: [], priorities: [] },
      { key: "oak", label: "Oak", total: 1, counts: { assigned: 1 }, service_types: [], priorities: [] },
    ] });
    await openHub({ role: "admin", graphs });
    await user().click(el.tab("graphs"));
    await vi.waitFor(() => expect(el.panel("graphs").querySelector(".hub-graphs")).not.toBeNull());
    expect(el.panel("graphs").querySelector('[data-graph-tab="maple"]').classList.contains("active")).toBe(true); // largest first
    const before = queries("/hub/graphs").length;
    await user().click(el.panel("graphs").querySelector('[data-graph-tab="oak"]'));
    expect(queries("/hub/graphs")).toHaveLength(before);
    expect(el.panel("graphs").querySelector('[data-graph-tab="oak"]').classList.contains("active")).toBe(true);
    await user().selectOptions(el.panel("graphs").querySelector(".hub-graphs-weeks"), "52");
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(before + 1));
    expect(el.panel("graphs").querySelector('[data-graph-tab="oak"]').classList.contains("active")).toBe(true);
  });

  it("Graphs distribution click hands off to Work Orders with the filter", async () => {
    const { mod } = await openHub({ role: "admin", handlers: [
      http.get("/work-orders/filter-options", () => HttpResponse.json({})),
      http.get("/items/", () => HttpResponse.json([])),
      http.get("/users/", () => HttpResponse.json([])),
    ] });
    await user().click(el.tab("graphs"));
    await vi.waitFor(() => expect(el.panel("graphs").querySelector(".hub-graph-card-all")).not.toBeNull());
    await user().click(el.panel("graphs").querySelector(".hub-graph-card-all"));
    expect(document.getElementById("work-orders-page").classList.contains("active")).toBe(true);
    expect(mod).toBeTruthy();
  });

  it("Report (admin+): skeleton, then re-fetched on every re-entry", async () => {
    await openHub({ role: "admin" });
    await user().click(el.tab("report"));
    expect(el.panel("report").querySelector(".hub-report-loading")).not.toBeNull();
    await vi.waitFor(() => expect(queries("/hub/report")).toHaveLength(1));
    await user().click(el.tab("dashboard"));
    await user().click(el.tab("report"));
    await vi.waitFor(() => expect(queries("/hub/report")).toHaveLength(2));
  });

  it("a techfm_oa never fetches the report", async () => {
    await openHub({ role: "techfm_oa" });
    expect(el.tab("report").hidden).toBe(true);
    expect(requestFor("/hub/report")).toBeNull();
  });
});
```

`filter-options` needs a valid shape for the Work Orders hand-off: use `filterOptions()` from factories if `{}` fails validation in `workOrderFilters.js`.

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/userHub.test.js
git commit -m "test(p5f): tab switching and the lazy tabs"
```

---

### Task 4: Per-tab failure isolation — foreground vs background

**Files:** Modify `tests/frontend/views/userHub.test.js`.

- [ ] **Step 1: Write the tests**

```js
describe("failure isolation", () => {
  it("crew fails on first load: inline error in the crew mount; dashboard and admin still render", async () => {
    await openHub({ role: "admin", crew: 500 });
    expect(el.crewMount().querySelector("p.error").textContent).toBe("Could not load your crew.");
    expect(el.prioritiesMount().querySelector(".hub-priorities")).not.toBeNull();
    expect(el.adminMount().children.length).toBeGreaterThan(0);
  });

  it("admin fails on first load: inline error in the admin mount only", async () => {
    await openHub({ role: "admin", admin: 500 });
    expect(el.adminMount().querySelector("p.error").textContent).toBe("Could not load the company summary.");
    expect(el.crewMount().querySelector("p.error")).toBeNull();
  });

  it("a background crew failure keeps the last good board", async () => {
    await openHub({ role: "supervisor" });
    expect(el.crewMount().querySelector(".hub-crew-card")).not.toBeNull();
    server.use(http.get("/hub/crew", () => HttpResponse.json({ detail: "x" }, { status: 500 })));
    await vi.advanceTimersByTimeAsync(60000);           // safety refresh
    await vi.waitFor(() => expect(queries("/hub/crew")).toHaveLength(2));
    expect(el.crewMount().querySelector(".hub-crew-card")).not.toBeNull();
    expect(el.crewMount().querySelector("p.error")).toBeNull();
  });

  it("timesheets fail: error with a Retry that refetches the same range", async () => {
    await openHub({ role: "supervisor", timesheets: 500 });
    await user().click(el.tab("timesheets"));
    await vi.waitFor(() => expect(el.panel("timesheets").querySelector(".hub-timesheet-message.error")).not.toBeNull());
    server.use(http.get("/hub/timesheets", () => HttpResponse.json(hubTimesheets())));
    await user().click(el.panel("timesheets").querySelector(".hub-timesheet-retry"));
    await vi.waitFor(() => expect(el.panel("timesheets").querySelector(".hub-timesheet-table")).not.toBeNull());
    expect(queries("/hub/timesheets")).toHaveLength(2);
  });

  it("graphs fail: error with Retry; a later background failure keeps the last good render", async () => {
    await openHub({ role: "admin", graphs: 500 });
    await user().click(el.tab("graphs"));
    await vi.waitFor(() => expect(el.panel("graphs").querySelector(".hub-graphs-load-error")).not.toBeNull());
    server.use(http.get("/hub/graphs", () => HttpResponse.json(hubGraphs())));
    await user().click(el.panel("graphs").querySelector(".hub-graphs-retry"));
    await vi.waitFor(() => expect(el.panel("graphs").querySelector(".hub-graphs")).not.toBeNull());
    server.use(http.get("/hub/graphs", () => HttpResponse.json({ detail: "x" }, { status: 500 })));
    await vi.advanceTimersByTimeAsync(60000);
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(3));
    expect(el.panel("graphs").querySelector(".hub-graphs")).not.toBeNull();
  });

  it("an empty graphs payload is swallowed: the skeleton stays and no error shows", async () => {
    // mountHubGraphs reads `activeCommunity.key` with no communities and throws;
    // loadGraphs has already stored the payload, so its catch returns early.
    // Characterization -- file it.
    await openHub({ role: "admin", graphs: hubGraphs({ communities: [] }) });
    await user().click(el.tab("graphs"));
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(1));
    expect(el.panel("graphs").querySelector(".skel-grid")).not.toBeNull();
    expect(el.panel("graphs").querySelector(".hub-graphs-load-error")).toBeNull();
  });

  it("report fails: error with Retry", async () => {
    await openHub({ role: "owner" });                    // fixture answers /hub/report with 500
    await user().click(el.tab("report"));
    await vi.waitFor(() => expect(el.panel("report").querySelector(".hub-report-load-error")).not.toBeNull());
    expect(el.panel("report").querySelector("p.error").textContent).toBe("Could not load the daily report.");
    await user().click(el.panel("report").querySelector(".hub-report-retry"));
    await vi.waitFor(() => expect(queries("/hub/report")).toHaveLength(2));
  });
});
```

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/userHub.test.js
git commit -m "test(p5f): per-tab failure isolation, foreground and background"
```

---

### Task 5: The crew safety interval, visibility, and the clock hand-off

**Files:** Modify `tests/frontend/views/userHub.test.js`.

- [ ] **Step 1: Write the tests**

```js
describe("crew safety refresh", () => {
  it("every 60 s refetches personal (+ crew for supervisor+, + admin for techfm_oa+), in the background", async () => {
    await openHub({ role: "admin" });
    clearRequests();
    await vi.advanceTimersByTimeAsync(59999);
    expect(requests()).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    await vi.waitFor(() => expect(requests().map((r) => r.url).sort()).toEqual(["/hub", "/hub/admin", "/hub/crew"]));
    await vi.advanceTimersByTimeAsync(60000);
    await vi.waitFor(() => expect(requests()).toHaveLength(6));
  });

  it("a technician's interval refetches only /hub", async () => {
    await openHub({ role: "technician" });
    clearRequests();
    await vi.advanceTimersByTimeAsync(60000);
    await vi.waitFor(() => expect(requests().map((r) => r.url)).toEqual(["/hub"]));
  });

  it("adds graphs only while the Graphs tab is open", async () => {
    await openHub({ role: "admin" });
    await user().click(el.tab("graphs"));
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(1));
    await vi.advanceTimersByTimeAsync(60000);
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(2));
    await user().click(el.tab("dashboard"));
    await vi.advanceTimersByTimeAsync(60000);
    await vi.waitFor(() => expect(queries("/hub").length).toBeGreaterThan(2));
    expect(queries("/hub/graphs")).toHaveLength(2);
  });

  it("is cleared on hide and restarted on show only while the hub page is active", async () => {
    await openHub({ role: "supervisor" });
    stopClock();                                          // visibilitychange, hidden
    expect(vi.getTimerCount()).toBe(0);
    clearRequests();
    await vi.advanceTimersByTimeAsync(120000);
    expect(requests()).toHaveLength(0);
    // show again with the hub NOT the active page: nothing restarts
    restoreHubVisibility();
    document.dispatchEvent(new Event("visibilitychange"));
    expect(vi.getTimerCount()).toBe(0);
    // show again WITH the hub active: both timers come back
    el.page().classList.add("active");
    document.dispatchEvent(new Event("visibilitychange"));
    expect(vi.getTimerCount()).toBe(2); // clock tick + safety interval
    await vi.advanceTimersByTimeAsync(60000);
    await vi.waitFor(() => expect(requestFor("/hub/crew")).not.toBeNull());
  });

  it("a second loadUserHub does not stack a second interval", async () => {
    const { mod } = await openHub({ role: "technician" });
    await mod.loadUserHub();
    await mod.loadUserHub();
    clearRequests();
    await vi.advanceTimersByTimeAsync(60000);
    await vi.waitFor(() => expect(queries("/hub")).toHaveLength(1));
  });
});

describe("clock hand-off", () => {
  it("the clock's onChanged refreshes the whole hub (one /hub fetch serves clock and tabs)", async () => {
    const { payload } = await openHub({ role: "technician", hub: hubPayload({ startable: [{
      work_order_id: "w1", number: "7001", status: "assigned", community: null, building_number: null, unit_number: null, location: null,
    }] }), handlers: [http.post("/work-orders/:id/tracking/start", () => HttpResponse.json({}))] });
    clearRequests();
    const start = el.clockMount().querySelector(".hub-clock-start-btn");
    expect(start.dataset.action).toBe("hub-clock-start");
    await user().click(start);
    await vi.waitFor(() => expect(requestFor("/tracking/start", "POST")).not.toBeNull());
    await vi.waitFor(() => expect(requestFor("/hub", "GET")).not.toBeNull());
    expect(payload).toBeTruthy();
  });
});
```

`restoreHubVisibility()` is the exported half of `stopClock()`'s restore: add it to `helpers/hub.js` as `export function restoreHubVisibility() { if (hiddenRestore) { hiddenRestore(); hiddenRestore = null; } }` and have `restoreHub()` call it. Selectors verified 2026-09-11: `.hub-timesheet-prev` / `.hub-timesheet-next` (`hubTimesheets.js:190-192`), `.hub-clock-start-btn[data-action="hub-clock-start"]` (`hubClock.js:93`).

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/helpers/hub.js tests/frontend/views/userHub.test.js
git commit -m "test(p5f): safety interval, visibility lifecycle, clock hand-off"
```

---

### Task 6: Realtime subscriptions through the fake socket

**Files:** Modify `tests/frontend/views/userHub.test.js`.

- [ ] **Step 1: Write the tests**

```js
describe("realtime", () => {
  it("labor.session.changed on the hub page refreshes crew (+ admin for techfm_oa+) in the background", async () => {
    await openHub({ role: "admin" });
    const { emit } = await connectHub();
    clearRequests();
    emit("labor.session.changed");
    await vi.waitFor(() => expect(requests().map((r) => r.url).sort()).toEqual(["/hub/admin", "/hub/crew"]));
    expect(requestFor("/hub", "GET")).toBeNull();
  });

  it("work_order.status.changed refreshes personal, crew, admin; graphs only while that tab is open", async () => {
    await openHub({ role: "admin" });
    const { emit } = await connectHub();
    clearRequests();
    emit("work_order.status.changed", { id: "w1" });
    await vi.waitFor(() => expect(requests().map((r) => r.url).sort()).toEqual(["/hub", "/hub/admin", "/hub/crew"]));
    await user().click(el.tab("graphs"));
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(1));
    emit("work_order.status.changed", { id: "w1" });
    await vi.waitFor(() => expect(queries("/hub/graphs")).toHaveLength(2));
  });

  it("user_request.changed refreshes only the personal payload", async () => {
    await openHub({ role: "supervisor" });
    const { emit } = await connectHub();
    clearRequests();
    emit("user_request.changed");
    await vi.waitFor(() => expect(requests().map((r) => r.url)).toEqual(["/hub"]));
  });

  it("a technician on work_order.status.changed refetches /hub only", async () => {
    await openHub({ role: "technician" });
    const { emit } = await connectHub();
    clearRequests();
    emit("work_order.status.changed", { id: "w1" });
    await vi.waitFor(() => expect(requests().map((r) => r.url)).toEqual(["/hub"]));
  });

  it("an unrelated event, or the hub not being the active page, does nothing", async () => {
    await openHub({ role: "admin" });
    const { emit, ws } = await connectHub();
    clearRequests();
    emit("item.changed", { id: "i1" });
    await vi.advanceTimersByTimeAsync(50);
    expect(requests()).toHaveLength(0);
    const realtime = await import("../../backend/static/realtime.js");
    realtime.setActivePageGetter(() => "history");
    emit("labor.session.changed");
    await vi.advanceTimersByTimeAsync(50);
    expect(requests()).toHaveLength(0);
    expect(ws.sockets).toHaveLength(1);
  });

  it("the personal refresh repaints the work-orders tab label and the open tab", async () => {
    await openHub({ role: "technician", hub: hubPayload({ mine_total: 1 }) });
    const { emit } = await connectHub();
    server.use(http.get("/hub", () => HttpResponse.json(hubPayload({ mine_total: 4, user: { id: "u", role: "technician" } }))));
    emit("user_request.changed");
    await vi.waitFor(() => expect(el.tab("work-orders").textContent).toBe("My Work Orders (4)"));
  });
});
```

If the envelope validator rejects `id: null` for a typed event, use `id: "x"` — P1's `realtime.test.js` documents the accepted shape; match it.

- [ ] **Step 2: Run the file, then `npm test`**; record count and wall-clock.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/userHub.test.js
git commit -m "test(p5f): realtime subscriptions through the fake socket"
```

---

### Task 7: Findings, docs, close-out

**Files:** Modify `docs/open-work.md`, `docs/current-state.md`, `docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md`, `docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md`.

- [ ] **Step 1: Findings.** Append to `### N-P5-CHARACTERIZED` only rows the tests confirmed. Candidates:

| Defect | Pinned by |
| --- | --- |
| `mountHubGraphs` throws on a payload with no communities (`activeCommunity.key`); `loadGraphs` has already stored the payload so the catch returns early and the tab shows a skeleton forever, no error, no Retry. | `userHub.test.js` → "an empty graphs payload is swallowed" |
| `destroyHubGraphs()` is a no-op; the "on tab change" lifecycle the parent plan names has nothing to assert. | → "Graphs: a community tab click re-renders from memory" |
| The safety interval refetches `/hub` for every role every 60 s while the page is visible, regardless of whether the socket is connected — by design per spec §6.2, recorded so the request count in P6 tests is not mistaken for a leak. | → "every 60 s refetches" |

- [ ] **Step 2: `docs/current-state.md`.** User Hub task-area row gains `tests/frontend/views/userHub.test.js`; note `tests/frontend/helpers/hub.js` as the P6 mount helper; update the Vitest count/time bullet.
- [ ] **Step 3: Parent plan + roadmap.** Tick P5f bullets; roadmap status `P5a–P5f landed`; roadmap P6 step text: replace "should get a shared mount helper" with "mount through `tests/frontend/helpers/hub.js` (`openHub({role, crew, admin, timesheets, graphs})`), built in P5f".
- [ ] **Step 4: Verify and commit** — `npm test` green.

```bash
git add docs/open-work.md docs/current-state.md docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md
git commit -m "docs: record P5f user-hub coverage and the shared hub fixture"
```

---

## Done when

- [ ] `npm test` green at every commit; count and wall-clock in the Task 6 and Task 7 commit bodies.
- [ ] Both exports exercised (`loadUserHub`, `refreshUserHub` via the clock hand-off); all three `subscribe` handlers driven through the fake socket; the safety interval asserted started, cleared, and restarted.
- [ ] `vi.getTimerCount()` is 0 after every test.
- [ ] Four new factories pass the drift guard.
- [ ] No file under `backend/` touched.

## Deliberately not in P5f

- The sub-modules' own rendering (`hubTechnician`, `hubSupervisor`, `hubAdmin`, `hubPriorities`, `hubTimesheets`, `hubGraphs`, `hubReport`, `hubClock` internals) — P6, on this fixture.
- A successful `/hub/report` payload (its nested shape is P6's `hubReport` chunk to factory).
- `reason === "reconnect"` on `work_order.status.changed` (needs the reconnect path; P1 covers reconnect scheduling).
- `openWorkOrdersFilteredByDistribution`'s effect on the Work Orders filters (P2).
- Fixing anything above.
