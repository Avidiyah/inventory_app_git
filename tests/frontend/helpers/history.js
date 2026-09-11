// The History page fixture.
//
// history.js fetches nothing at import; loadHistory() is the only entry point
// and every request is answered off the arguments the test passed. State is
// state.js's historyState, fresh per test because setup.js resets the module
// registry.

import { vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "./handlers.js";
import { mountView } from "./shell.js";
import { setTestUser } from "./session.js";
import { startRecording, stopRecording, clearRequests, requestFor } from "./requests.js";

// Getters, not nodes: every mount replaces `document.documentElement`.
const byId = (id) => () => document.getElementById(id);
export const el = {
  page: byId("history-page"), results: byId("history-results"), tbody: byId("history-tbody"), table: byId("history-table"),
  prev: byId("history-prev-btn"), next: byId("history-next-btn"), pageInfo: byId("history-page-info"),
  woFilter: byId("history-wo-filter"), woClear: byId("history-wo-clear-btn"), woMessage: byId("history-wo-message"),
  dateFrom: byId("history-date-from"), dateTo: byId("history-date-to"), dateClear: byId("history-date-clear-btn"),
  itemSearch: byId("history-item-search"), itemResults: byId("history-item-results"), itemMessage: byId("history-item-message"),
  userSelect: byId("history-user-select"), userMessage: byId("history-user-message"),
  pricingBtn: byId("history-pricing-btn"), pricingMessage: byId("history-pricing-message"), pricingOutput: byId("history-pricing-output"),
  resultsMessage: byId("history-results-message"),
  tab: (feature) => document.querySelector(`#history-tabs .sub-nav-btn[data-feature="${feature}"]`),
  chargeHeader: () => document.querySelector("#history-table thead .admin-col"),
};
export const rowEls = () => Array.from(el.tbody().querySelectorAll("tr"));
export const cells = (i = 0) => Array.from(rowEls()[i].querySelectorAll("td")).map((td) => td.textContent.trim());
export const voidBtn = (i = 0) => rowEls()[i].querySelector(".void-txn-btn");
export const chargeCell = (i = 0) => rowEls()[i].querySelector(".charge-cell");

// `users.js` (P6) fills the select in production; here the options are
// seeded directly.
export function seedUsers(users) {
  for (const { id, label } of users) {
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = label;
    el.userSelect().appendChild(opt);
  }
}

// The most recent `GET /transactions/?...` as a plain query object.
export function lastQuery() {
  const r = requestFor("/transactions/?", "GET");
  return r ? Object.fromEntries(new URL(r.url, "http://t").searchParams) : null;
}

// Page-keyed answers for the pricing list's copy-all loop.
export function answerHistoryPages(pages) {
  const total = pages.reduce((n, p) => n + p.length, 0);
  server.use(http.get("/transactions/", ({ request }) => {
    const page = Number(new URL(request.url).searchParams.get("page"));
    return HttpResponse.json({ items: pages[page - 1] ?? [], total });
  }));
}

export async function mountHistory({ role = "supervisor", rows = [], total = null, items = [], handlers = [] } = {}) {
  // `handlers` go FIRST: MSW takes the first matching handler within one
  // `use()` call, so a test's override must precede the fixture defaults.
  server.use(
    ...handlers,
    http.get("/transactions/", () => HttpResponse.json({ items: rows, total: total ?? rows.length })),
    http.get("/items/", () => HttpResponse.json(items)),
  );
  const currentUser = await setTestUser({ role });
  startRecording();
  const mod = await mountView("views/history.js");
  clearRequests();
  return { mod, currentUser };
}

export async function openHistory(opts = {}) {
  const mounted = await mountHistory(opts);
  await mounted.mod.loadHistory();
  return mounted;
}

export function restoreHistory() {
  stopRecording();
  vi.useRealTimers();
}
