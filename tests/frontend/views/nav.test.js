// Characterization of `views/nav.js` -- the SPA's page router.
//
// Booted through `helpers/app.js`, so the real `main.js` composition root runs
// and every assertion here is against the module instance production wires.
// Nothing is mocked: MSW answers the page loaders, a fake class answers
// `new WebSocket`, and the camera is stubbed at the browser boundary.
//
// Where an assertion records something that looks wrong, the comment says so
// and the row is filed in docs/open-work.md. This file corrects nothing.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { bootApp, appRoot } from "../helpers/app.js";

const ROLES = ["technician", "supervisor", "techfm_oa", "admin", "owner"];

// Every page the app has, frozen. Deriving this from PAGE_ACCESS would make
// the table below a tautology; it is written out so a page added, removed or
// renamed lands here deliberately.
const PAGES = [
  "user-hub", "create-item", "saved-items", "create-user", "saved-users",
  "transaction", "mass-stage", "work-orders", "user-requests", "low-stock",
  "admin-review", "tools", "history", "integrations",
];

// Who may see what, written out per role rather than computed. This is the
// backend's route gate mirrored in the UI, so it is exactly the thing a test
// must state independently.
const VISIBLE_BY_ROLE = {
  technician: ["user-hub", "saved-items", "transaction", "work-orders", "tools"],
  supervisor: [
    "user-hub", "saved-items", "create-user", "saved-users", "transaction",
    "mass-stage", "work-orders", "tools", "history",
  ],
  techfm_oa: PAGES,
  admin: PAGES,
  owner: PAGES,
};

// The five task-domain groups in `shell-head.html`, and which pages sit in
// each. `user-hub` is in none of them -- the identity button lives in
// `#auth-bar`, outside `#main-nav`.
const GROUPS = {
  inventory: ["create-item", "saved-items", "tools"],
  field: ["transaction", "work-orders", "mass-stage"],
  people: ["create-user", "saved-users"],
  review: ["low-stock", "user-requests", "admin-review", "history"],
  integration: ["integrations"],
};

const navButton = (page) => document.querySelector(`.nav-btn[data-page="${page}"]`);
const navGroup = (name) => document.querySelector(`.nav-group[data-nav-group="${name}"]`);
const visiblePages = () =>
  Array.from(document.querySelectorAll(".nav-btn"))
    .filter((btn) => !btn.hidden)
    .map((btn) => btn.dataset.page);

describe("bootApp", () => {
  it("boots the whole spine with no unhandled request and no console error", async () => {
    const errors = [];
    const spy = vi.spyOn(console, "error").mockImplementation((...args) => errors.push(args));
    const { requestsFor } = await bootApp({ role: "owner" });

    expect(appRoot().hidden).toBe(false);
    expect(document.getElementById("login-screen").hidden).toBe(true);
    // The owner's landing page is the hub, and its loader really ran.
    expect(requestsFor("/hub")).toHaveLength(1);
    expect(errors).toEqual([]);
    spy.mockRestore();
  });
});

describe("the page table", () => {
  beforeEach(async () => { await bootApp({ role: "owner" }); });

  it("has an entry for every .page section, and no entry without one", async () => {
    const { PAGE_ACCESS } = await import("../../../backend/static/views/nav.js");
    const sections = Array.from(document.querySelectorAll(".page"))
      .map((el) => el.id.replace(/-page$/, ""))
      .sort();
    expect(Object.keys(PAGE_ACCESS).sort()).toEqual(sections);
    expect(sections).toEqual([...PAGES].sort());
  });

  it("has a nav button for every page except the hub, which is the identity button", () => {
    const wired = Array.from(document.querySelectorAll(".nav-btn")).map((b) => b.dataset.page);
    expect([...wired].sort()).toEqual([...PAGES].sort());
    // The hub's button sits in #auth-bar, not #main-nav -- but it still
    // carries `.nav-btn`, so nav.js gates and wires it with all the others.
    // nav.js's own comment says "no nav button reads this key"; it does.
    // Filed in docs/open-work.md.
    expect(navButton("user-hub").closest("#main-nav")).toBeNull();
    expect(navButton("user-hub").id).toBe("auth-user-indicator");
  });
});

describe("canAccessPage", () => {
  let nav;
  beforeEach(async () => { ({ nav } = await bootApp({ role: "owner" })); });

  it.each(ROLES)("%s sees exactly the pages the table allows", (role) => {
    const allowed = PAGES.filter((page) => nav.canAccessPage(role, page));
    expect(allowed).toEqual(VISIBLE_BY_ROLE[role]);
  });

  it("refuses an unknown page and an unknown role", () => {
    expect(nav.canAccessPage("owner", "nope")).toBe(false);
    expect(nav.canAccessPage("intern", "history")).toBe(false);
  });
});

describe("landingPageForRole", () => {
  let nav;
  beforeEach(async () => { ({ nav } = await bootApp({ role: "owner" })); });

  // The invariant the fallback exists to defend. If a landing page is ever
  // set to something its own role cannot reach, `landingPageForRole` silently
  // returns `transaction` instead -- which is a usable screen, and therefore
  // a drift nobody would notice in the field.
  it.each(ROLES)("%s lands on a page %s can actually reach", (role) => {
    const landing = nav.landingPageForRole(role);
    expect(nav.canAccessPage(role, landing)).toBe(true);
  });

  it.each(ROLES)("%s lands on the hub", (role) => {
    expect(nav.landingPageForRole(role)).toBe("user-hub");
  });

  it("falls back to transaction for a role with no entry", () => {
    expect(nav.landingPageForRole("intern")).toBe("transaction");
  });
});

describe("applyRoleVisibility", () => {
  let nav;
  beforeEach(async () => { ({ nav } = await bootApp({ role: "owner" })); });

  it.each(ROLES)("%s: exactly the allowed buttons are visible", (role) => {
    nav.applyRoleVisibility(role);
    expect(visiblePages().sort()).toEqual([...VISIBLE_BY_ROLE[role]].sort());
  });

  // The trailing-hairline rule: a group whose every button is hidden is
  // itself hidden, or its `.nav-group + .nav-group` separator would draw
  // against empty space.
  it.each(ROLES)("%s: a group with nothing visible in it is hidden", (role) => {
    nav.applyRoleVisibility(role);
    for (const [name, pages] of Object.entries(GROUPS)) {
      const anyVisible = pages.some((page) => VISIBLE_BY_ROLE[role].includes(page));
      expect(navGroup(name).hidden, `group ${name} for ${role}`).toBe(!anyVisible);
    }
  });

  // COMPACT_NAV_THRESHOLD is 5, counted over PAGE_ACCESS minus the hub.
  // Technician has four pages and stays flat; everyone else compacts.
  it.each([
    ["technician", false],
    ["supervisor", true],
    ["techfm_oa", true],
    ["admin", true],
    ["owner", true],
  ])("%s: nav-compact is %s", (role, compact) => {
    nav.applyRoleVisibility(role);
    expect(document.getElementById("main-nav").classList.contains("nav-compact")).toBe(compact);
  });

  it("closes any open group menu on a role switch", async () => {
    const toggle = navGroup("review").querySelector(".nav-group-toggle");
    await userEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");

    nav.applyRoleVisibility("technician");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.nextElementSibling.classList.contains("open")).toBe(false);
  });
});

describe("group menus", () => {
  beforeEach(async () => { await bootApp({ role: "owner" }); });

  const toggleOf = (name) => navGroup(name).querySelector(".nav-group-toggle");
  const menuOf = (name) => toggleOf(name).nextElementSibling;

  it("opens on click and closes on a second click", async () => {
    await userEvent.click(toggleOf("field"));
    expect(menuOf("field").classList.contains("open")).toBe(true);
    await userEvent.click(toggleOf("field"));
    expect(menuOf("field").classList.contains("open")).toBe(false);
  });

  it("only ever has one open", async () => {
    await userEvent.click(toggleOf("field"));
    await userEvent.click(toggleOf("people"));
    expect(menuOf("field").classList.contains("open")).toBe(false);
    expect(menuOf("people").classList.contains("open")).toBe(true);
  });

  it("closes on an outside click and on Escape", async () => {
    await userEvent.click(toggleOf("field"));
    await userEvent.click(document.getElementById("app-root"));
    expect(menuOf("field").classList.contains("open")).toBe(false);

    await userEvent.click(toggleOf("field"));
    await userEvent.keyboard("{Escape}");
    expect(menuOf("field").classList.contains("open")).toBe(false);
  });
});

describe("showPage", () => {
  let nav;
  let clearRequests;
  let requestsFor;
  beforeEach(async () => {
    ({ nav, clearRequests, requestsFor } = await bootApp({ role: "owner" }));
    clearRequests();
  });

  it("moves .active on both the section and the button, and getActivePage follows", () => {
    nav.showPage("history");
    expect(document.getElementById("history-page").classList.contains("active")).toBe(true);
    expect(navButton("history").classList.contains("active")).toBe(true);
    expect(nav.getActivePage()).toBe("history");

    nav.showPage("low-stock");
    expect(document.getElementById("history-page").classList.contains("active")).toBe(false);
    expect(navButton("history").classList.contains("active")).toBe(false);
    expect(document.getElementById("low-stock-page").classList.contains("active")).toBe(true);
    expect(nav.getActivePage()).toBe("low-stock");
  });

  it("leaves exactly one section active", () => {
    nav.showPage("tools");
    expect(document.querySelectorAll(".page.active")).toHaveLength(1);
  });

  it("runs the entering page's loader exactly once", async () => {
    nav.showPage("history");
    await vi.waitFor(() => expect(requestsFor("/transactions/")).toHaveLength(1));
    expect(requestsFor("/transactions/")).toHaveLength(1);
  });

  it("runs no request for a page with no loader", async () => {
    nav.showPage("create-item");
    // Find Item is in PAGE_LOADERS but deliberately fetches nothing; Add Item
    // is not in the map at all. Neither may reach the network.
    nav.showPage("saved-items");
    expect(requestsFor("/items/")).toHaveLength(0);
  });

  it("closes an open group menu", async () => {
    const toggle = navGroup("review").querySelector(".nav-group-toggle");
    await userEvent.click(toggle);
    nav.showPage("tools");
    expect(toggle.nextElementSibling.classList.contains("open")).toBe(false);
  });

  // The bubble is `position: fixed` and body-parented, so one left open across
  // a page swap hangs over markup it has nothing to do with. Driven through
  // `showPage` rather than a nav click: a click would also be caught by
  // `installTooltips`'s own document listener, which closes it too.
  it("closes an open tooltip", async () => {
    const trigger = document.querySelector("[data-tip]");
    expect(trigger, "the shell must carry at least one static tip").not.toBeNull();
    trigger.click();
    expect(document.getElementById("tip-bubble").hidden).toBe(false);

    nav.showPage("tools");
    expect(document.getElementById("tip-bubble").hidden).toBe(true);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });
});

describe("nav buttons", () => {
  let nav;
  beforeEach(async () => { ({ nav } = await bootApp({ role: "owner" })); });

  it("a click routes to the button's page", async () => {
    await userEvent.click(navButton("mass-stage"));
    expect(nav.getActivePage()).toBe("mass-stage");
    expect(document.getElementById("mass-stage-page").classList.contains("active")).toBe(true);
  });

  it("the identity button routes to the hub like any other nav button", async () => {
    await userEvent.click(navButton("history"));
    await userEvent.click(navButton("user-hub"));
    expect(nav.getActivePage()).toBe("user-hub");
  });
});

describe("scanner lifecycle", () => {
  let nav;
  const input = (id) => document.getElementById(id);

  beforeEach(async () => {
    ({ nav } = await bootApp({ role: "owner" }));
  });

  // `reset()` clears the scanner's input, chooser and message. The input is an
  // `<input type="file">`, whose value cannot be set to anything but the empty
  // string, so the chooser and the message carry the observation.
  function dirty(prefix) {
    input(`${prefix}-scan-chooser`).innerHTML = "<button>pick</button>";
    input(`${prefix}-scan-chooser`).hidden = false;
    input(`${prefix}-scan-message`).textContent = "Could not read that barcode.";
  }

  function isClean(prefix) {
    return input(`${prefix}-scan-chooser`).innerHTML === ""
      && input(`${prefix}-scan-chooser`).hidden === true
      && input(`${prefix}-scan-message`).textContent === "";
  }

  it("resets the leaving page's scanner", () => {
    nav.showPage("transaction");
    dirty("txn");
    nav.showPage("history");
    expect(isClean("txn")).toBe(true);
  });

  it("does not reset when the same page is shown twice", () => {
    nav.showPage("transaction");
    dirty("txn");
    nav.showPage("transaction");
    expect(isClean("txn")).toBe(false);
  });

  // The create-item entry drives BOTH tab widgets, so neither camera can be
  // left running by a page swap.
  it("resets both Add Item tab scanners on leave", () => {
    nav.showPage("create-item");
    dirty("item");
    dirty("tool");
    nav.showPage("history");
    expect(isClean("item")).toBe(true);
    expect(isClean("tool")).toBe(true);
  });

  it("refreshes the entering page's permission state", async () => {
    // `refreshPermissionState` reveals the Scan button when the browser
    // supports live capture. `helpers/media.js` stubs ZXing + getUserMedia +
    // permissions, so this is the supported branch.
    const scanBtn = input("txn-scan-scan-btn");
    scanBtn.hidden = true;
    nav.showPage("transaction");
    await vi.waitFor(() => expect(scanBtn.hidden).toBe(false));
  });

  it("does not touch a page that has no scanner", () => {
    nav.showPage("transaction");
    dirty("txn");
    // history -> low-stock: neither is a scanner page, so the txn scanner is
    // only reset by the first leave, not by every later swap.
    nav.showPage("history");
    expect(isClean("txn")).toBe(true);
    dirty("txn");
    nav.showPage("low-stock");
    expect(isClean("txn")).toBe(false);
  });
});

describe("visibilitychange", () => {
  let nav;
  let hidden = false;

  beforeEach(async () => {
    ({ nav } = await bootApp({ role: "owner" }));
    hidden = false;
    Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
  });

  afterEach(() => {
    delete document.hidden;
  });

  const hide = () => {
    hidden = true;
    document.dispatchEvent(new Event("visibilitychange"));
  };

  // `stopLive()` on an idle scanner still re-hides the torch button and
  // re-enables Upload, which is how "it reached this scanner" is observable
  // without a camera. Two scanners on two different pages prove the loop runs
  // over every registered entry, not just the active page's.
  it("stops every registered scanner, not just the active page's", () => {
    for (const prefix of ["txn", "items", "tools", "item", "tool"]) {
      document.getElementById(`${prefix}-scan-torch-btn`).hidden = false;
      document.getElementById(`${prefix}-scan-upload-btn`).disabled = true;
    }
    nav.showPage("transaction");
    hide();
    for (const prefix of ["txn", "items", "tools", "item", "tool"]) {
      expect(document.getElementById(`${prefix}-scan-torch-btn`).hidden, prefix).toBe(true);
      expect(document.getElementById(`${prefix}-scan-upload-btn`).disabled, prefix).toBe(false);
    }
  });

  // Deliberate, and documented in nav.js: tabbing back should find the
  // section's message/chooser state as it was.
  it("does not reset -- the section keeps its message and chooser state", () => {
    nav.showPage("transaction");
    document.getElementById("txn-scan-message").textContent = "Aim at a barcode…";
    document.getElementById("txn-scan-chooser").innerHTML = "<button>pick</button>";
    hide();
    expect(document.getElementById("txn-scan-message").textContent).toBe("Aim at a barcode…");
    expect(document.getElementById("txn-scan-chooser").innerHTML).toBe("<button>pick</button>");
  });

  it("does nothing when the tab becomes visible", () => {
    nav.showPage("transaction");
    document.getElementById("txn-scan-torch-btn").hidden = false;
    hidden = false;
    document.dispatchEvent(new Event("visibilitychange"));
    expect(document.getElementById("txn-scan-torch-btn").hidden).toBe(false);
  });
});
