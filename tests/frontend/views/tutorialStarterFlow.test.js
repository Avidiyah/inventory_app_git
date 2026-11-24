// The real starters on the real player, in the real shell: tap-by-tap through
// each script the way a person does (overlay clicks inside the lit rectangle,
// Enter on overview steps). Safety (nothing but the lit tap takes input) is
// tutorialLockdown.test.js; this proves each tour completes, opens the right
// pages, marks progress once and never sends anything but GETs and its own PUTs.

import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { bootApp } from "../helpers/app.js";
import { stubClientRects } from "../helpers/starterWalk.js";

const overlay = () => document.querySelector(".tut-overlay");
const byId = (id) => document.getElementById(id);

const clickAt = (el) => {
  const r = el.getBoundingClientRect();
  overlay().dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true,
    clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }));
};

// Enter on the focused Log Out button is "next sentence / hide / next step".
const enter = () => {
  byId("logout-btn").focus();
  byId("logout-btn").dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
};

const progress = (requests) => requests().filter((c) => /^\/tutorials\/progress\//.test(c.url));
const events = (requests) => progress(requests).map((c) => JSON.stringify(c.body).match(/seen|completed/)?.[0]);

async function boot(role) {
  const app = await bootApp({ role,
    handlers: [http.put("/tutorials/progress/:key", () => new HttpResponse(null, { status: 204 }))] });
  stubClientRects();
  const tut = await import("../../../backend/static/tutorial.js");
  const { TUTORIALS } = await import("../../../backend/static/tutorials/index.js");
  tut.installTutorials({ getActivePage: app.nav.getActivePage, showPage: app.nav.showPage, tutorials: TUTORIALS });
  const tp = await import("../../../backend/static/tutorialProgress.js");
  tp.clearProgress();
  return { ...app, tut, script: (key) => TUTORIALS.starter.scripts.find((s) => s.key === key) };
}

const countIs = (k, n) => () => expect(document.querySelector(".tut-count").textContent).toBe(`${k} of ${n}`);

// Plays the visible steps as a person would; returns the pages the taps opened.
// Stops before the last step's own taps (its box stays up until Done or End).
async function play(app, key, role) {
  const list = app.tut.visibleSteps(app.script(key), role);
  app.tut.startTutorial("starter", key);
  await vi.waitFor(countIs(1, list.length));
  const opened = [];
  for (let k = 0; k < list.length; k += 1) {
    const { step, lines } = list[k];
    if (k === list.length - 1) {
      if (k > 0) expect(events(app.requests)).toEqual(["seen", "completed"]);
      break;
    }
    expect(events(app.requests), `before step ${k + 1}`).toEqual(["seen"]);
    if (step.waitTap) {
      const btn = document.querySelector(step.waitTap);
      if (!btn.getClientRects().length) clickAt([...document.querySelectorAll(step.via)].find((v) => v.getClientRects().length));
      clickAt(btn);
      opened.push(btn.dataset.page);
    } else {
      for (let t = 0; t < lines.length + 1; t += 1) enter(); // each sentence, hide, next
    }
    await vi.waitFor(countIs(k + 2, list.length));
  }
  return opened;
}

const groupPages = (group) =>
  [...document.querySelectorAll(`[data-nav-group="${group}"] .nav-btn:not([hidden])`)]
    .map((b) => b.dataset.page).filter((p) => !p.startsWith("smr"));

describe.each(["technician", "supervisor", "owner"])("%s: starters on the real player", (role) => {
  it("Field opens each page its group offers, marks seen then completed once, sends only GETs", async () => {
    const app = await boot(role);
    app.clearRequests();
    const opened = await play(app, "starter.field", role);
    expect(opened).toEqual(groupPages("field").filter((p) => opened.includes(p)));
    expect(opened.length).toBe(groupPages("field").length);
    expect(app.nav.getActivePage()).toBe(opened.at(-1));
    expect(app.requests().filter((c) => c.method !== "GET" && !/^\/tutorials\/progress\//.test(c.url))).toEqual([]);
    expect(progress(app.requests).every((c) => c.method === "PUT")).toBe(true);
    app.tut.endTutorial();
    expect(events(app.requests)).toEqual(["seen", "completed"]);
  });

  it("Menu ends with the person on Find Item", async () => {
    const app = await boot(role);
    app.clearRequests();
    const opened = await play(app, "starter.menu", role);
    expect(opened).toEqual(["saved-items"]);
    expect(app.nav.getActivePage()).toBe("saved-items");
    app.tut.endTutorial();
  });

  it("Esc after the first forwarded tap leaves it unfinished", async () => {
    const app = await boot(role);
    app.clearRequests();
    app.tut.startTutorial("starter", "starter.field");
    await vi.waitFor(() => expect(overlay()).not.toBeNull());
    const first = document.querySelector('.nav-btn[data-page="transaction"]');
    if (!first.getClientRects().length) clickAt(document.querySelector('[data-nav-group="field"] .nav-group-toggle'));
    clickAt(first);
    await vi.waitFor(() => expect(app.nav.getActivePage()).toBe("transaction"));
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(overlay()).toBeNull());
    expect(events(app.requests)).toEqual(["seen"]);
  });
});
