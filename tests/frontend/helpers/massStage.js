// The Mass Stage fixture.
//
// massStage.js fetches nothing at import; loadStages() fetches the reference
// data and the summary list, and each stage's detail loads when its
// <details> opens -- jsdom dispatches `toggle` asynchronously, so openCard()
// waits for the module to mark the card loaded.

import { expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "./handlers.js";
import { mountView } from "./shell.js";
import { setTestUser } from "./session.js";
import { restoreMediaStubs, stubPermissions, stubUserMedia } from "./media.js";
import { startRecording, stopRecording, clearRequests } from "./requests.js";

// Getters, not nodes: every mount replaces `document.documentElement`.
const byId = (id) => () => document.getElementById(id);
export const el = {
  list: byId("mass-stage-list"), listMessage: byId("mass-stage-list-message"),
  communitySelect: byId("mass-stage-community-select"), communityNew: byId("mass-stage-community-new"),
  buildingInput: byId("mass-stage-building-input"), createBtn: byId("mass-stage-create-btn"),
  createMessage: byId("mass-stage-create-message"),
};
export const groupEls = () => Array.from(el.list().querySelectorAll("details.community-group"));
export const cardEls = () => Array.from(el.list().querySelectorAll("details.stage-card"));
export const card = (stageId) => el.list().querySelector(`details.stage-card[data-stage-id="${stageId}"]`);
export const stageMessage = (cardEl) => cardEl.querySelector(".ms-stage-message");
export const slotEls = (cardEl) => Array.from(cardEl.querySelectorAll("details.room-card"));

// Mutable so a test can change what a refresh returns (an add-item test
// seeds the new row before clicking Add).
export const state = { stages: [], details: new Map() };

export function respond(method, path, body, { status = 200 } = {}) {
  server.use(http[method.toLowerCase()](path, () =>
    body === null && status === 204 ? new HttpResponse(null, { status }) : HttpResponse.json(body, { status })));
}

export async function mountMassStage({ role = "supervisor", stages = [], details = [], items = [], users = [], handlers = [] } = {}) {
  state.stages = stages;
  state.details = new Map(details.map((d) => [String(d.id), d]));
  // `handlers` go FIRST: MSW takes the first matching handler within one
  // `use()` call, so a test's override must precede the fixture defaults.
  server.use(
    ...handlers,
    http.get("/mass-stages/:id", ({ params }) => {
      const d = state.details.get(params.id);
      return d ? HttpResponse.json(d) : HttpResponse.json({ detail: "Not found" }, { status: 404 });
    }),
    http.get("/mass-stages/", () => HttpResponse.json(state.stages)),
    http.get("/items/", () => HttpResponse.json(items)),
    http.get("/users/", () => HttpResponse.json(users)),
  );
  stubUserMedia();
  stubPermissions("prompt");
  await setTestUser({ role });
  startRecording();
  const mod = await mountView("views/massStage.js");
  clearRequests();
  return { mod };
}

export async function openStages(opts = {}) {
  const mounted = await mountMassStage(opts);
  await mounted.mod.loadStages({ refreshReferenceData: true });
  clearRequests();
  return mounted;
}

// Open a community group (if closed) and a stage card; wait for its detail.
export async function openCard(stageId) {
  const c = card(stageId);
  const group = c.closest("details.community-group");
  if (group && !group.open) group.open = true;
  c.open = true;
  await vi.waitFor(() => expect(c.dataset.loaded).toBe("1"));
  return c;
}

export function restoreMassStage() {
  stopRecording();
  restoreMediaStubs();
}
