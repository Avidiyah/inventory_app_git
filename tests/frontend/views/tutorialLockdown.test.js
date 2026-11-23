// The user's standing rule: a tutorial never changes real data. A starter has no
// sample data, so safety comes from the player alone: while a box is up nothing
// but the lit menu control takes input, and no request leaves except the opened
// page's own GETs. Real shell, real nav, real player; only the fixture script is
// ours.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { bootApp } from "../helpers/app.js";
import { stubClientRects } from "../helpers/starterWalk.js";

const overlay = () => document.querySelector(".tut-overlay");
const box = () => document.querySelector(".tut-box");
const text = () => document.querySelector(".tut-text").textContent;
const byId = (id) => document.getElementById(id);

const INVENTORY = '[data-nav-group="inventory"] .nav-group-toggle';
const FIELD = '[data-nav-group="field"] .nav-group-toggle';
const btn = (page) => `.nav-btn[data-page="${page}"]`;

const clickAt = (el) => {
  const r = el.getBoundingClientRect();
  overlay().dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true,
    clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }));
};

// The player records its own progress (PUT /tutorials/progress/<key>: seen,
// completed) -- the tutorial's own bookkeeping, not app data. Everything else
// that leaves the page is what these tests police.
const sent = (requests) => requests().filter((c) => !/^\/tutorials\/progress\//.test(c.url));

// Enter on the focused Log Out button: on an overview step the player takes it
// as "next sentence", and it must never reach the button.
const advance = () => {
  byId("logout-btn").focus();
  byId("logout-btn").dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
};

async function start(role, steps) {
  const app = await bootApp({ role,
    handlers: [http.post("/auth/logout", () => new HttpResponse(null, { status: 204 })),
      http.put("/tutorials/progress/:key", () => new HttpResponse(null, { status: 204 }))] });
  stubClientRects();
  const tut = await import("../../../backend/static/tutorial.js");
  tut.installTutorials({ getActivePage: app.nav.getActivePage, showPage: app.nav.showPage,
    tutorials: { starter: { scripts: [{ key: "fx.lock", title: "Lock", sample: false, steps }] } } });
  app.clearRequests();
  tut.startTutorial("starter", "fx.lock");
  await vi.waitFor(() => expect(box()).not.toBeNull());
  return { ...app, tut };
}

// Everything a person (or a stray key) could do at this step, short of the one
// lit tap: nothing may change.
function assertLocked({ nav, requests }, { clickOutside = false } = {}) {
  const toggles = [...document.querySelectorAll(".nav-group-toggle")];
  const expanded = toggles.map((t) => t.getAttribute("aria-expanded"));
  const page = nav.getActivePage();
  const logout = byId("logout-btn");
  const cover = overlay();
  for (const type of ["pointerdown", "touchstart", "mousedown"]) {
    cover.dispatchEvent(new Event(type, { bubbles: true, cancelable: true }));
  }
  if (clickOutside) clickAt(logout); // the overlay covers it; outside the lit rectangle
  for (const k of ["Tab", " ", "x"]) {
    logout.focus();
    for (const type of ["keydown", "keyup"]) {
      const e = new KeyboardEvent(type, { key: k, bubbles: true, cancelable: true });
      logout.dispatchEvent(e);
      expect(e.defaultPrevented, `${type} ${JSON.stringify(k)}`).toBe(true);
    }
    if (k === "Tab" && !box().hidden) expect(box().contains(document.activeElement)).toBe(true);
  }
  expect(sent(requests)).toEqual([]);
  expect(nav.getActivePage()).toBe(page);
  expect(toggles.map((t) => t.getAttribute("aria-expanded"))).toEqual(expanded);
  expect(document.body.lastElementChild).toBe(cover);
}

const tour = (waitTap, via) => [
  { target: "#main-nav", text: "The menu." },
  { waitTap, ...(via ? { via, viaText: "Open the group." } : {}), text: "Tap it." },
  { target: "#saved-items-page", text: "A page." },
  { target: "#logout-btn", text: "Log out." },
];

describe.each([["supervisor", true], ["technician", false]])("%s: input lockdown", (role, compact) => {
  it("blocks everything but the lit menu control at every step; the taps send only GETs", async () => {
    const app = await start(role, tour(btn("saved-items"), compact ? INVENTORY : null));
    assertLocked(app);                       // step 1, overview
    advance(); advance();                    // hide the box, then step 2
    expect(text()).toBe(compact ? "Open the group." : "Tap it.");
    assertLocked(app, { clickOutside: true });
    if (compact) {
      clickAt(document.querySelector(INVENTORY));
      expect(document.querySelector(INVENTORY).getAttribute("aria-expanded")).toBe("true");
      expect(sent(app.requests)).toEqual([]); // no request between the two taps
      expect(text()).toBe("Tap it.");
      assertLocked(app, { clickOutside: true });
    }
    clickAt(document.querySelector(btn("saved-items")));
    await vi.waitFor(() => expect(text()).toBe("A page."));
    expect(app.nav.getActivePage()).toBe("saved-items");
    expect(sent(app.requests)).toEqual([]);  // Find Item loads nothing, so no GET either
    assertLocked(app);                       // step 3, overview
    advance(); advance();
    expect(text()).toBe("Log out.");
    assertLocked(app);                       // step 4, over Log Out itself
    expect(app.requests().some((c) => /logout/.test(c.url))).toBe(false);
    expect(app.requests().every((c) => c.method === "PUT" && /^\/tutorials\/progress\//.test(c.url))).toBe(true);
  });
});

describe("a page that loads data", () => {
  it("Work Orders via Field records only the page's own GETs", async () => {
    const app = await start("supervisor", [
      { waitTap: btn("work-orders"), via: FIELD, viaText: "Open Field.", text: "Tap Work Orders." },
      { target: "#work-orders-page", text: "The board." }]);
    clickAt(document.querySelector(FIELD));
    expect(sent(app.requests)).toEqual([]);
    clickAt(document.querySelector(btn("work-orders")));
    await vi.waitFor(() => expect(text()).toBe("The board."));
    await new Promise((r) => setTimeout(r, 300));
    const calls = sent(app.requests);
    expect(calls.every((c) => c.method === "GET"), JSON.stringify(calls)).toBe(true);
    // The board's loader: its list and filters, plus the item and user pickers.
    const paths = calls.map((c) => new URL(c.url, "http://x").pathname);
    expect(paths.every((p) => /^\/(work-orders|items|users)\//.test(p)), JSON.stringify(calls)).toBe(true);
    expect(paths.some((p) => p.startsWith("/work-orders/"))).toBe(true);
  });
});

describe("the cover", () => {
  it("styles.css keeps .tut-overlay fixed, full-screen and above the nav popovers", () => {
    const css = readFileSync(join(process.cwd(), "backend", "static", "styles.css"), "utf8");
    const block = css.match(/\.tut-overlay\s*\{([^}]*)\}/)?.[1] ?? "";
    expect(block).toMatch(/position:\s*fixed/);
    expect(block).toMatch(/inset:\s*0/);
    const popover = Number(css.match(/\.nav-group-menu\s*\{[^}]*z-index:\s*(\d+)/)?.[1]);
    expect(Number(block.match(/z-index:\s*(\d+)/)?.[1])).toBeGreaterThan(popover);
  });
});
