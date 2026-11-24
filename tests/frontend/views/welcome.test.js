// The one-time welcome: its script (spec 5.5) and the sequencing in
// views/welcome.js (spec 5.1). Driven on the real app, real player and real Hub;
// MSW answers the progress routes.

import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { bootApp } from "../helpers/app.js";
import { stubClientRects } from "../helpers/starterWalk.js";

const SEEN_ROW = { key: "welcome", seen_at: "2026-11-01T00:00:00Z", completed_at: null };
const quiet = [http.get("/tutorials/progress/me", () => HttpResponse.json([SEEN_ROW]))];
const overlay = () => document.querySelector(".tut-overlay");
const modal = () => document.querySelector(".clock-in-prompt");
const settle = () => new Promise((r) => setTimeout(r, 30));
const puts = (requests) => requests().filter((c) => c.method === "PUT" && c.url.startsWith("/tutorials/progress/"));
const events = (requests) => puts(requests).map((c) => JSON.stringify(c.body).match(/seen|completed/)?.[0]);

// A booted app whose own sign-in found the welcome already seen (so boot is
// quiet either way), then the scenario's answers and a clean slate.
async function boot(role, { me = [], put = () => HttpResponse.json({ first: true }) } = {}) {
  const app = await bootApp({ role, handlers: quiet });
  await settle();
  document.querySelector('[data-action="skip"]')?.click();
  stubClientRects();
  const tut = await import("../../../backend/static/tutorial.js");
  const { TUTORIALS } = await import("../../../backend/static/tutorials/index.js");
  tut.installTutorials({ getActivePage: app.nav.getActivePage, showPage: app.nav.showPage, tutorials: TUTORIALS });
  const tp = await import("../../../backend/static/tutorialProgress.js");
  tp.clearProgress();
  const state = await import("../../../backend/static/state.js");
  const { runWelcomeThenClockIn } = await import("../../../backend/static/views/welcome.js");
  server.use(http.get("/tutorials/progress/me", () => HttpResponse.json(me)),
    http.put("/tutorials/progress/:key", put));
  app.clearRequests();
  const user = state.getCurrentUser();
  return { ...app, tut, tp, state, user, run: (opts = { plain: true }) => runWelcomeThenClockIn(user, opts) };
}

const enter = (n = 1) => { for (let i = 0; i < n; i += 1) document.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true })); };
const clickAt = (el) => {
  const r = el.getBoundingClientRect();
  overlay().dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }));
};
const count = (k, n = 5) => () => expect(document.querySelector(".tut-count").textContent).toBe(`${k} of ${n}`);

// Plays the tour to its last step (Done not yet tapped).
async function playToLast() {
  await vi.waitFor(count(1));
  enter(5); // four sentences, hide, next
  await vi.waitFor(count(2));
  clickAt(document.getElementById("hub-tab-tutorials"));
  await vi.waitFor(count(3));
  enter(3);
  await vi.waitFor(count(4));
  enter(3);
  await vi.waitFor(count(5));
  enter(); // second sentence: Done shows on the last sentence of the last step
}

describe("the welcome script", () => {
  it("is step 1's four sentences verbatim, then four tour steps", async () => {
    const { SCRIPTS } = await import("../../../backend/static/tutorials/welcome.js");
    const [s] = SCRIPTS;
    expect(SCRIPTS.length).toBe(1);
    expect(s.key).toBe("welcome");
    expect(s.steps.length).toBe(5);
    expect(s.steps[0].target).toBeUndefined();
    expect(s.steps[0].text).toEqual([
      "Welcome to TechFM.",
      "TechFM is Technological Facilities Maintenance: our app for work orders, stock, tools and time.",
      "Each page has its own tutorial available at the top of the page.",
      "They are also in the Tutorials section, which we're about to navigate to first.",
    ]);
    for (const [i, step] of s.steps.entries()) {
      const lines = [].concat(step.text);
      expect(lines.length, `step ${i + 1}`).toBeLessThanOrEqual(i === 0 ? 4 : 3);
      for (const l of lines) expect(l.length, l).toBeLessThanOrEqual(120);
    }
  });

  it("is registered standalone, for everyone, and listed as a to-do", async () => {
    const { TUTORIALS } = await import("../../../backend/static/tutorials/index.js");
    expect(TUTORIALS.welcome.standalone).toBe(true);
    expect(TUTORIALS.welcome.sample).toBeUndefined();
    expect(TUTORIALS.welcome.scripts[0].minRole).toBe("technician");
  });
});

describe("welcome, then the clock-in prompt", () => {
  it("due: PUT seen first, tour up, no modal until it ends, then the modal", async () => {
    const app = await boot("technician");
    void app.run();
    await vi.waitFor(() => expect(overlay()).not.toBeNull());
    expect(events(app.requests)).toEqual(["seen"]);
    expect(document.querySelector(".tut-title").textContent).toBe("Welcome");
    await settle();
    expect(modal()).toBeNull();
    document.querySelector('[data-tut-act="end"]').click();
    await vi.waitFor(() => expect(modal()).not.toBeNull());
    expect(events(app.requests)).toEqual(["seen"]); // End never completes
  });

  it("the PUT is recorded before the box is in the DOM", async () => {
    let boxAtPut = "unset";
    const app = await boot("technician", { put: () => { boxAtPut = document.querySelector(".tut-box"); return HttpResponse.json({ first: true }); } });
    void app.run();
    await vi.waitFor(() => expect(overlay()).not.toBeNull());
    expect(boxAtPut).toBeNull();
    app.tut.endTutorial();
  });

  it("not due (seen_at set): clock-in only, no PUT", async () => {
    const app = await boot("technician", { me: [SEEN_ROW] });
    void app.run();
    await vi.waitFor(() => expect(modal()).not.toBeNull());
    expect(overlay()).toBeNull();
    expect(puts(app.requests)).toEqual([]);
    expect(modal()).not.toBeNull();
  });

  it.each([
    ["first:false", () => HttpResponse.json({ first: false })],
    ["a 500", () => HttpResponse.json({ detail: "boom" }, { status: 500 })],
  ])("%s on the PUT: no tour, one PUT, modal still follows", async (_, put) => {
    const app = await boot("technician", { put });
    void app.run();
    await vi.waitFor(() => expect(modal()).not.toBeNull());
    expect(overlay()).toBeNull();
    expect(puts(app.requests).length).toBe(1);
    expect(modal()).not.toBeNull();
  });

  it("not plain (resumed or deep link): no tutorials request, modal follows", async () => {
    const app = await boot("technician");
    void app.run({ plain: false });
    await vi.waitFor(() => expect(modal()).not.toBeNull());
    expect(overlay()).toBeNull();
    expect(app.requests().filter((c) => c.url.startsWith("/tutorials/"))).toEqual([]);
    expect(modal()).not.toBeNull();
  });

  it("sign-out mid-tour: no clock-in prompt", async () => {
    const app = await boot("technician");
    void app.run();
    await vi.waitFor(() => expect(overlay()).not.toBeNull());
    app.state.setCurrentUser(null);
    app.tut.endTutorial({ restore: false });
    await settle();
    expect(modal()).toBeNull();
  });

  it("the Owner gets the welcome and never a modal", async () => {
    const app = await boot("owner");
    void app.run();
    await vi.waitFor(() => expect(overlay()).not.toBeNull());
    document.querySelector('[data-tut-act="end"]').click();
    await settle();
    expect(modal()).toBeNull();
  });
});

describe("walking the tour", () => {
  it("Done on the last step completes it and leaves the person on Tutorials, Starter sub-tab", async () => {
    const app = await boot("technician");
    void app.run();
    await playToLast();
    expect(events(app.requests)).toEqual(["seen", "completed"]);
    expect(document.querySelector(".tut-title").textContent).toBe("On every page");
    expect(document.querySelector(".tut-pill").textContent).toBe("Tutorial complete");
    enter(); // any tap on the last box closes it as done
    await vi.waitFor(() => expect(document.getElementById("hub-tab-tutorials").getAttribute("aria-selected")).toBe("true"));
    await vi.waitFor(() => expect(document.querySelector('[data-tut-sub="starter"]').classList.contains("active")).toBe(true));
    await vi.waitFor(() => expect(modal()).not.toBeNull());
  });

  it("End on the way leaves the person on the Hub tab they started on", async () => {
    const app = await boot("technician");
    void app.run();
    await vi.waitFor(count(1));
    enter(5);
    await vi.waitFor(count(2));
    clickAt(document.getElementById("hub-tab-tutorials"));
    await vi.waitFor(count(3));
    document.querySelector('[data-tut-act="end"]').click();
    await vi.waitFor(() => expect(document.getElementById("hub-tab-home").getAttribute("aria-selected")).toBe("true"));
    expect(events(app.requests)).toEqual(["seen"]);
  });

  it("every step's target exists on the Hub, for all five roles", async () => {
    const { SCRIPTS } = await import("../../../backend/static/tutorials/welcome.js");
    for (const role of ["technician", "supervisor", "techfm_oa", "admin", "owner"]) {
      const app = await boot(role);
      app.tut.installTutorials({ getActivePage: app.nav.getActivePage, showPage: app.nav.showPage, tutorials: (await import("../../../backend/static/tutorials/index.js")).TUTORIALS }); // the full registry: later tests start "welcome"
      document.getElementById("hub-tab-tutorials").click();
      for (const step of SCRIPTS[0].steps) {
        const sel = step.waitTap || step.target;
        if (sel) expect(document.querySelector(sel), `${role}: ${sel}`).not.toBeNull();
      }
    }
  }, 30000);

  it("phone: step 2 lights the section picker first, then the Tutorials tab", async () => {
    const app = await boot("technician");
    const base = Element.prototype.getClientRects;
    Element.prototype.getClientRects = function () {
      const inTabs = this.closest?.("#hub-tabs");
      if (inTabs && !document.getElementById("hub-picker").classList.contains("open")) return [];
      return base.call(this);
    };
    try {
      void app.run();
      await vi.waitFor(count(1));
      enter(5);
      await vi.waitFor(() => expect(document.querySelector(".tut-text").textContent).toBe("Tap here to open the list of sections."));
      clickAt(document.getElementById("hub-picker-toggle"));
      await vi.waitFor(() => expect(document.querySelector(".tut-text").textContent).toMatch(/^Tap Tutorials/));
      app.tut.endTutorial();
    } finally {
      Element.prototype.getClientRects = base;
    }
  });

  it("a manual run from the tab, once seen, sends no seen", async () => {
    const app = await boot("technician", { me: [SEEN_ROW] });
    await app.tp.loadProgress();
    document.getElementById("hub-tab-tutorials").click();
    void app.tut.startTutorial("welcome", "welcome");
    await vi.waitFor(count(1));
    app.tut.endTutorial();
    expect(events(app.requests)).toEqual([]);
  });
});

// The real sign-in funnel (auth.js enterApp) runs the welcome, then the prompt.
describe("enterApp wiring", () => {
  const due = [http.get("/tutorials/progress/me", () => HttpResponse.json([])),
    http.put("/tutorials/progress/:key", () => HttpResponse.json({ first: true }))];

  it("a plain sign-in with the welcome due shows the tour, the modal only after it", async () => {
    const app = await bootApp({ role: "technician", handlers: due });
    await vi.waitFor(() => expect(overlay()).not.toBeNull());
    expect(modal()).toBeNull();
    expect(events(app.requests)).toEqual(["seen"]);
    document.querySelector('[data-tut-act="end"]').click();
    await vi.waitFor(() => expect(modal()).not.toBeNull());
  });

  it("a plain sign-in with it already seen goes straight to the modal", async () => {
    const app = await bootApp({ role: "technician" }); // default handlers: welcome seen
    await vi.waitFor(() => expect(modal()).not.toBeNull());
    expect(overlay()).toBeNull();
    expect(puts(app.requests)).toEqual([]);
  });

  it("a shared work-order link skips it with no progress write", async () => {
    window.history.replaceState({}, "", "/workorder_card/4242");
    try {
      const app = await bootApp({ role: "supervisor", handlers: [...due,
        http.get("/work-orders/", () => HttpResponse.json([]))] });
      await settle();
      expect(overlay()).toBeNull();
      expect(puts(app.requests)).toEqual([]);
    } finally {
      window.history.replaceState({}, "", "/");
    }
  });
});
