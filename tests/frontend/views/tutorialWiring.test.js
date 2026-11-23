import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { bootApp } from "../helpers/app.js";
import { stubClientRects } from "../helpers/starterWalk.js";

const overlay = () => document.querySelector(".tut-overlay");
const box = () => document.querySelector(".tut-box");

async function boot() {
  const app = await bootApp({ role: "supervisor", page: "work-orders" });
  const tut = await import("../../../backend/static/tutorial.js");
  const showPage = vi.fn(app.nav.showPage);
  tut.installTutorials({
    getActivePage: app.nav.getActivePage,
    showPage,
    tutorials: {
      "work-orders": {
        sample: () => ({}),
        scripts: [{ key: "work-orders.demo", title: "Demo", steps: [{ target: "#work-orders-page h2", text: "Hi." }] }],
      },
    },
  });
  const start = async () => {
    document.querySelector("#work-orders-page .tut-btn").click();
    await vi.waitFor(() => expect(box()).not.toBeNull());
  };
  return { ...app, tut, showPage, start };
}

const clickAt = (el) => {
  const r = el.getBoundingClientRect();
  overlay().dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true,
    clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }));
};

// A script with no sample (like the starter tours) on the real, compact bar.
const FIND = '.nav-btn[data-page="saved-items"]';
const fixture = {
  scripts: [{ key: "fx.find", title: "Find", sample: false, steps: [
    { waitTap: FIND, via: '[data-nav-group="inventory"] .nav-group-toggle', viaText: "Open Inventory.", text: "Tap Find Item." },
    { target: "#saved-items-page", text: "This is Find Item." },
    { target: "#main-nav", text: "The menu." }] }],
};

async function bootStarter() {
  const app = await bootApp({ role: "supervisor",
    handlers: [http.post("/auth/logout", () => new HttpResponse(null, { status: 204 }))] });
  stubClientRects();
  const tut = await import("../../../backend/static/tutorial.js");
  tut.installTutorials({ getActivePage: app.nav.getActivePage, showPage: app.nav.showPage,
    tutorials: { starter: fixture } });
  const started = tut.startTutorial("starter", "fx.find");
  await vi.waitFor(() => expect(box()).not.toBeNull());
  return { ...app, tut, started };
}

describe("a script across pages (no sample)", () => {
  const text = () => document.querySelector(".tut-text").textContent;

  it("both forwarded taps open the page and the script carries on", async () => {
    const { nav } = await bootStarter();
    expect(text()).toBe("Open Inventory.");
    clickAt(document.querySelector('[data-nav-group="inventory"] .nav-group-toggle'));
    await vi.waitFor(() => expect(text()).toBe("Tap Find Item."));
    clickAt(document.querySelector(FIND));
    await vi.waitFor(() => expect(text()).toBe("This is Find Item."));
    expect(nav.getActivePage()).toBe("saved-items");
    expect(overlay()).not.toBeNull();
    document.querySelector(".tut-overlay").click();
    document.querySelector(".tut-overlay").click();
    expect(text()).toBe("The menu.");
  });

  it("any other page change ends it", async () => {
    const { nav } = await bootStarter();
    nav.showPage("history");
    expect(overlay()).toBeNull();
  });

  it("signing out inside the 3 s window ends it", async () => {
    await bootStarter();
    clickAt(document.querySelector('[data-nav-group="inventory"] .nav-group-toggle'));
    await vi.waitFor(() => expect(text()).toBe("Tap Find Item."));
    clickAt(document.querySelector(FIND));
    document.getElementById("logout-btn").click();
    await vi.waitFor(() => expect(overlay()).toBeNull());
  });
});

describe("tutorial wiring", () => {
  it("puts one pill in the page title, after any tip button, and none on other pages", async () => {
    const { tut, nav } = await boot();
    tut.installTutorials({ getActivePage: nav.getActivePage, showPage: nav.showPage,
      tutorials: { "work-orders": { scripts: [] } } });
    const btns = document.querySelectorAll("#work-orders-page h2 .tut-btn");
    expect(btns).toHaveLength(1);
    expect(btns[0].textContent).toBe("How this page works");
    expect(btns[0].nextElementSibling).toBeNull();
    expect(document.querySelector("#smr-page .tut-btn")).toBeNull();
  });

  it("leaving the page ends the tutorial without reloading work orders", async () => {
    const { nav, showPage, start } = await boot();
    await start();
    expect(showPage).toHaveBeenCalledTimes(1);
    nav.showPage("history");
    expect(overlay()).toBeNull();
    expect(showPage).toHaveBeenCalledTimes(1);
    expect(nav.getActivePage()).toBe("history");
  });

  // Sign-out also routes through showLoginScreen; its button sits under the
  // overlay, so a 401 is the only way to get there mid-tutorial.
  it("a 401 ends it", async () => {
    const { start } = await boot();
    await start();
    server.use(http.get("/hub", () => HttpResponse.json({ detail: "Not authenticated" }, { status: 401 })));
    const api = await import("../../../backend/static/api.js");
    await api.apiGetHub().catch(() => {});
    expect(overlay()).toBeNull();
  });
});
