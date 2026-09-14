// The Low Stock mount fixture.
//
// `lowStock.js` and `lowStockCard.js` import each other, but the only
// cross-binding read is `loadLowStock`, a hoisted function declaration, and
// neither calls the other at top level -- so `lowStock.js` is the entry point
// and a plain `mountView` brings both up (P7 deviation 7). Nothing loads at
// import; `loadLowStock()` is the entry and the mount calls it.
//
// The clock is pinned (`vi.setSystemTime`) because the three recency buckets
// are cut against `Date.now()`: the factory's `last_dispensed_at` is one hour
// before `LOW_STOCK_NOW`, so a default row lands in `day`, and a bucket test
// moves only that one field. The global `afterEach` restores the real clock.

import { http, HttpResponse } from "msw";
import { vi } from "vitest";
import { server } from "./handlers.js";
import { startRecording, stopRecording, requests, requestFor, clearRequests } from "./requests.js";
import { mountView } from "./shell.js";
import { setTestUser } from "./session.js";
import { connectFakeRealtime } from "./realtime.js";

export const LOW_STOCK_NOW = "2026-09-10T12:00:00Z";

const byId = (id) => () => document.getElementById(id);

export const el = {
  list: byId("low-stock-list"),
  message: byId("low-stock-message"),
  refresh: byId("low-stock-refresh"),
  tabs: byId("low-stock-tabs"),
};

export const tabBtn = (bucket) => el.tabs().querySelector(`.sub-nav-btn[data-bucket="${bucket}"]`);
export const cards = () => Array.from(el.list().querySelectorAll("details.low-stock-card"));
export const cardFor = (id) => el.list().querySelector(`details.low-stock-card[data-id="${id}"]`);
// The two message paragraphs are found by POSITION, not by class: `setMessage`
// (dom.js) writes `className = type || ""`, so `.low-stock-row-message` and
// `.low-stock-edit-message` survive only until the first message lands on
// them. The modules themselves re-find them by class on every commit, which
// is the N-P7-CHARACTERIZED finding lowStock.test.js pins.
const bodyParagraphs = (card) =>
  Array.from(card.querySelector(".low-stock-body").children).filter((c) => c.tagName === "P");
export const rowMessage = (card) => bodyParagraphs(card)[0];
export const editMessage = (card) => bodyParagraphs(card)[1];
export const thresholdInput = (card) => card.querySelector(".low-stock-threshold-input");
export const actionBtn = (card, action) => card.querySelector(`[data-action="${action}"]`);
export const listGets = () => requests().filter((r) => r.url === "/items/low-stock");

export { requests, requestFor, clearRequests };
export { answerConfirm, confirmOverlay, confirmTitle } from "./dialogs.js";

let realtime = null;

// `rows` answers every `GET /items/low-stock`, the first load and every
// background reload alike. `handlers` go FIRST so a test's own override wins.
export async function mountLowStock({
  role = "admin", rows = [], handlers = [], now = LOW_STOCK_NOW, load = true,
} = {}) {
  vi.setSystemTime(new Date(now));
  server.use(
    ...handlers,
    http.get("/items/low-stock", () => HttpResponse.json(rows)),
  );
  const currentUser = await setTestUser({ role });
  startRecording();
  const mod = await mountView("views/lowStock.js");
  if (load) await mod.loadLowStock();
  clearRequests();
  return { mod, currentUser };
}

export async function connectLowStock(activePage = "low-stock") {
  realtime = await connectFakeRealtime(activePage);
  return realtime;
}

export function restoreLowStock() {
  if (realtime) { realtime.disconnect(); realtime = null; }
  stopRecording();
}
