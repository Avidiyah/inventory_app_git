// The Work Orders mount fixture.
//
// `views/workOrders.js` needs four responses before it will paint anything
// (`GET /work-orders/`, `/work-orders/filter-options`, `/items/`, `/users/`)
// and a fifth (`/work-orders/{id}/requests`, fired by `mountWorkOrderRequests`)
// before a card body settles. With `onUnhandledRequest: "error"` on, a test
// that forgets one fails for the wrong reason. This module answers all five
// off one mutable `state`, so the behaviour files carry assertions and not
// setup.
//
// Nothing here mocks an app module: MSW answers `fetch`, and the real
// api.js / dom.js / format.js / realtime.js all execute.

import { afterEach, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "./handlers.js";
import { mountView } from "./shell.js";
import { setTestUser } from "./session.js";
import { filterOptions as filterOptionsFactory, workOrderDetail } from "./factories.js";

// What the handlers answer with. Mutated in place so a test can change a
// response between two loads (see `seedList`) without re-registering.
export const state = {
  cards: [],
  details: new Map(),
  requests: [],
  filterOptions: null,
  items: [],
  users: [],
  lookup: { found: false },
  // Set by a test that wants the list request to fail or to hang.
  listResponder: null,
};

// --- request recording ----------------------------------------------------
//
// Wraps MSW's own `fetch` replacement, so the recorder sees exactly the
// `init` api.js built (method, JSON body) and MSW still answers the call.
// Synchronous by construction, which `lastRequest()` depends on: MSW's
// `request:start` event would hand back a body only after an await.
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

// Every recorded `(method, url, body)`, oldest first.
export function requests() {
  return recorded;
}

export function lastRequest() {
  return recorded.at(-1) ?? null;
}

// The most recent call whose url contains `fragment` (and method matches, if
// given). Preferred over `lastRequest()` for an action that also refreshes:
// the refresh GET is what actually lands last.
export function requestFor(fragment, method = null) {
  return (
    [...recorded]
      .reverse()
      .find((call) => call.url.includes(fragment) && (!method || call.method === method)) ?? null
  );
}

export function clearRequests() {
  recorded = [];
}

// --- handlers -------------------------------------------------------------

// Order matters: MSW takes the first matching handler, and `/work-orders/:id`
// would otherwise swallow `filter-options`, `lookup` and `export`.
function installHandlers() {
  server.use(
    http.get("/work-orders/filter-options", () =>
      HttpResponse.json(state.filterOptions ?? filterOptionsFactory())),
    http.get("/work-orders/lookup", () => HttpResponse.json(state.lookup)),
    http.get("/work-orders/:id/requests", () => HttpResponse.json(state.requests)),
    http.get("/work-orders/:id", ({ params }) => {
      const detail = state.details.get(params.id);
      if (!detail) return HttpResponse.json({ detail: "Not found" }, { status: 404 });
      return HttpResponse.json(detail);
    }),
    http.get("/work-orders/", () =>
      (state.listResponder ? state.listResponder() : HttpResponse.json(state.cards))),
    http.get("/items/", () => HttpResponse.json(state.items)),
    http.get("/users/", () => HttpResponse.json(state.users)),
  );
}

// Register one extra response for this test. `path` is relative, exactly as
// api.js issues it.
export function respond(method, path, body, { status = 200 } = {}) {
  const verb = http[method.toLowerCase()];
  server.use(verb(path, () => (
    body === null && status === 204
      ? new HttpResponse(null, { status })
      : HttpResponse.json(body, { status })
  )));
}

// --- mount ----------------------------------------------------------------

// `cards` seeds the list; `details` seeds `GET /work-orders/{id}` (a detail is
// keyed by its own id, so pass detail objects, not pairs). `load: false`
// imports the module without fetching, for the tests that drive the first
// load themselves.
export async function mountWorkOrders({
  role = "admin",
  cards = [],
  details = [],
  filterOptions = null,
  items = [],
  users = [],
  requests: workOrderRequests = [],
  lookup = { found: false },
  load = true,
} = {}) {
  state.cards = cards;
  state.details = new Map(details.map((detail) => [String(detail.id), detail]));
  state.requests = workOrderRequests;
  state.filterOptions = filterOptions;
  state.items = items;
  state.users = users;
  state.lookup = lookup;
  state.listResponder = null;

  const currentUser = await setTestUser({ role });
  installHandlers();
  startRecording();
  const mod = await mountView("views/workOrders.js");
  if (load) await mod.loadWorkOrders();
  clearRequests();
  return { mod, cards, currentUser };
}

// Replace what the next list load answers with.
export function seedList(cards) {
  state.cards = cards;
}

// Replace (or add) what `GET /work-orders/{id}` answers with.
export function seedDetail(detail) {
  state.details.set(String(detail.id), detail);
  return detail;
}

// --- card interaction -----------------------------------------------------

export const listEl = () => document.getElementById("work-orders-list");
export const cardEls = () => Array.from(listEl().querySelectorAll("details.wo-card"));

function resolveCard(target) {
  const cards = cardEls();
  if (typeof target === "number") return cards[target];
  return cards.find((el) => el.querySelector(".wo-title")?.textContent === `WO ${target}`);
}

// Open a card the way a user does: clicking a summary navigates to the card
// page (`openWorkOrderPage`), which paints the detail expanded as the only
// card in the list. Every delegated action still fires off `listEl`, so this
// is the right fixture for the action tests -- it is what production does.
export async function openCard(target = 0, detail = null) {
  const cardEl = resolveCard(target);
  if (!cardEl) throw new Error(`No rendered card for ${target}`);
  if (detail) seedDetail(detail);
  else if (!state.details.has(cardEl.dataset.id)) {
    throw new Error(`No detail seeded for ${cardEl.dataset.id}`);
  }
  cardEl.querySelector("summary.wo-summary").click();
  await vi.waitFor(() => {
    const body = listEl().querySelector("details.wo-card .wo-body");
    expect(body?.querySelector(".wo-details")).not.toBeNull();
  });
  // The open's own detail fetch is setup, not evidence: leaving it recorded
  // makes "the action refreshed the card" satisfiable by the open itself.
  clearRequests();
  return listEl().querySelector("details.wo-card");
}

// Expand a card in place, without leaving the list. Not a user path -- a
// summary click navigates -- but the only way to assert on a *list* that has
// one card's body painted (held-card realtime behaviour, the deferred
// refresh, `RECENT_LIMIT` with an open row).
export async function expandCard(target = 0, detail = null) {
  const cardEl = resolveCard(target);
  if (!cardEl) throw new Error(`No rendered card for ${target}`);
  if (detail) seedDetail(detail);
  cardEl.open = true;
  await vi.waitFor(() => expect(cardEl.querySelector(".wo-details")).not.toBeNull());
  clearRequests();
  return cardEl;
}

// The one card on screen (list or card page).
export const card = () => listEl().querySelector("details.wo-card");
export const cardBody = () => card()?.querySelector(".wo-body");

// The card's status line, found POSITIONALLY rather than by `.wo-message`.
// `setMessage` assigns `element.className = type`, which strips the class the
// selector would need -- so after the first message the element is
// `<p class="error">`, and `.wo-message` matches nothing. That is a real
// defect (filed in docs/open-work.md, and characterized in actions.test.js);
// this helper has to see the element in both states.
export const message = () => {
  const body = cardBody();
  const last = body?.lastElementChild;
  return last && last.tagName === "P" ? last : null;
};

// --- the shared confirm modal ---------------------------------------------
//
// `confirmDialog` resolves through the real shell modal in dom.js, so a test
// that clicks a gated action must answer it. Stubbing the module instead
// would skip the very wiring P4 has to preserve.
export const confirmOverlay = () => document.getElementById("scan-confirm-overlay");

export async function answerConfirm(yes = true) {
  await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(false));
  document.getElementById(yes ? "scan-confirm-yes" : "scan-confirm-no").click();
  await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(true));
}

// A `messageDialog` is the same overlay with only the one button.
export async function dismissMessageDialog() {
  await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(false));
  const text = document.getElementById("scan-confirm-title").textContent;
  document.getElementById("scan-confirm-yes").click();
  await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(true));
  return text;
}

// --- cleanup --------------------------------------------------------------
//
// Registered here rather than in every behaviour file: importing this module
// is the declaration that a test uses the fixture, and the alternative is the
// same four lines copied eight times.
afterEach(() => {
  if (originalFetch) {
    globalThis.fetch = originalFetch;
    originalFetch = null;
  }
  recorded = [];
  state.cards = [];
  state.details = new Map();
  state.requests = [];
  state.filterOptions = null;
  state.items = [];
  state.users = [];
  state.lookup = { found: false };
  state.listResponder = null;
});
