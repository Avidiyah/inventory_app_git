import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { bootApp } from "../helpers/app.js";

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

describe("tutorial wiring", () => {
  it("puts one pill in the page title, after any tip button, and none on other pages", async () => {
    const { tut, nav } = await boot();
    tut.installTutorials({ getActivePage: nav.getActivePage, showPage: nav.showPage,
      tutorials: { "work-orders": { scripts: [] } } });
    const btns = document.querySelectorAll("#work-orders-page h2 .tut-btn");
    expect(btns).toHaveLength(1);
    expect(btns[0].textContent).toBe("How this page works");
    expect(btns[0].nextElementSibling).toBeNull();
    expect(document.querySelector("#history-page .tut-btn")).toBeNull();
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
