// The User Hub fixture -- the shared mount helper the roadmap promises P6.
//
// userHub.js fetches nothing at import; loadUserHub() fires GET /hub and, by
// role, the crew and admin summaries; the other tabs fetch lazily. Every
// endpoint is answered off a factory here so a sub-module test (P6) is one
// `openHub({role, ...})` call and its assertions.
//
// Two timers start on load -- the clock's 1 s tick and the 60 s safety
// refresh -- and only `visibilitychange` (hidden) stops them. `stopClock()`
// fakes that hide; every test runs on fake timers and asserts no timer is
// left behind.

import { vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "./handlers.js";
import { mountView } from "./shell.js";
import { setTestUser } from "./session.js";
import { restoreMediaStubs, stubPermissions, stubUserMedia } from "./media.js";
import { startRecording, stopRecording, clearRequests, requests } from "./requests.js";
import { installFakeWebSocket } from "./fakeSocket.js";
import { hubAdmin, hubCrew, hubGraphs, hubPayload, hubTimesheets } from "./factories.js";

// Getters, not nodes: every mount replaces `document.documentElement`.
const byId = (id) => () => document.getElementById(id);
export const el = {
  page: byId("user-hub-page"), clockMount: byId("hub-clock-mount"), tabs: byId("hub-tabs"),
  tab: (name) => document.getElementById(`hub-tab-${name}`),
  panel: (name) => document.getElementById(`hub-tabpanel-${name}`),
  crewMount: byId("hub-crew-mount"), adminMount: byId("hub-admin-mount"), prioritiesMount: byId("hub-priorities-mount"),
};

// Parsed query objects for every recorded request whose url includes `fragment`.
export const queries = (fragment) => requests()
  .filter((r) => r.url.includes(fragment))
  .map((r) => Object.fromEntries(new URL(r.url, "http://t").searchParams));

// A number is an HTTP status to fail with; anything else is the JSON body.
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
  // `handlers` go FIRST: MSW takes the first matching handler within one
  // `use()` call, so a test's override must precede the fixture defaults.
  // The specific /hub/* paths precede the bare /hub for the same reason.
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

// Simulate the tab being hidden: `document.hidden` lives on
// `Document.prototype` in jsdom, so an instance override shadows it and the
// `visibilitychange` listener reads true. Idempotent until restored.
export function stopClock() {
  if (hiddenRestore) return;
  Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
  document.dispatchEvent(new Event("visibilitychange"));
  hiddenRestore = () => { delete document.hidden; };
}

// The other half: `document.hidden` reads false again. Does NOT dispatch
// `visibilitychange`; a test that wants the show path dispatches it itself.
export function restoreHubVisibility() {
  if (hiddenRestore) { hiddenRestore(); hiddenRestore = null; }
}

export function restoreHub() {
  stopClock();
  restoreHubVisibility();
  if (ws) { ws.restore(); ws = null; }
  stopRecording();
  restoreMediaStubs();
  vi.useRealTimers();
}

// Bring the realtime transport up on the hub page, as P2 did for Work Orders.
export async function connectHub() {
  ws = installFakeWebSocket();
  const realtime = await import("../../../backend/static/realtime.js");
  realtime.setActivePageGetter(() => "user-hub");
  realtime.connectRealtime();
  ws.last().emitOpen();
  return {
    ws,
    emit: (type, extra = {}) => ws.last().emitMessage(JSON.stringify({ type, id: null, req: null, ...extra })),
  };
}
