// views/subnav.js is 75 lines of DOM-only code with no fetch and no state, so
// it gets a unit file rather than a view one (P6 deviation 3). Three view
// modules drive it -- History (P5e), Items (P5c) and Tools (P6e) -- and each
// pins its own host wiring; what is left is the helper's own contract.
//
// The real shell supplies the production cases (Tools' three features, Low
// Stock's `.sub-nav` of buttons carrying `data-bucket` instead of
// `data-feature`); the variations the shell has no example of -- an `.active`
// marker that is not on the first button, a page with no `.sub-nav` -- are
// built by hand here rather than asserted against markup that does not exist.

import { afterEach, describe, expect, it, vi } from "vitest";
import { userEvent } from "@testing-library/user-event";
import { importView, mountShell } from "../helpers/shell.js";

const built = [];

afterEach(() => {
  while (built.length) built.pop().remove();
});

async function subnav() {
  mountShell();
  return importView("views/subnav.js");
}

// A `.page` shaped the way the convention's docblock describes it.
// `activeIndex: -1` leaves no button pre-marked; `withNav: false` drops the
// `.sub-nav` wrapper and leaves the buttons loose in the page.
function buildPage({ features = ["a", "b", "c"], activeIndex = 0, withNav = true } = {}) {
  const page = document.createElement("div");
  page.className = "page";
  const buttons = features.map((feature, index) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = index === activeIndex ? "sub-nav-btn active" : "sub-nav-btn";
    btn.dataset.feature = feature;
    btn.textContent = feature;
    return btn;
  });
  const host = withNav ? document.createElement("nav") : page;
  if (withNav) {
    host.className = "sub-nav";
    page.appendChild(host);
  }
  buttons.forEach((btn) => host.appendChild(btn));
  const panels = features.map((feature) => {
    const panel = document.createElement("section");
    panel.className = "feature-panel";
    panel.dataset.feature = feature;
    page.appendChild(panel);
    return panel;
  });
  document.body.appendChild(page);
  built.push(page);
  return { page, buttons, panels };
}

const shown = (panels) => panels.filter((panel) => !panel.hidden).map((panel) => panel.dataset.feature);
const actived = (buttons) => buttons.filter((btn) => btn.classList.contains("active")).map((b) => b.dataset.feature);

describe("initialisation", () => {
  it("boots the real Tools page on the feature its markup pre-marks", async () => {
    const { initSubNav } = await subnav();
    const page = document.getElementById("tools-page");
    const onShow = vi.fn();
    const handle = initSubNav(page, { onShow });

    expect(page.dataset.activeFeature).toBe("custody");
    const panels = Array.from(page.querySelectorAll(".feature-panel"));
    expect(shown(panels)).toEqual(["custody"]);
    expect(actived(Array.from(page.querySelectorAll(".sub-nav-btn")))).toEqual(["custody"]);
    expect(onShow).toHaveBeenCalledExactlyOnceWith("custody", null);
    expect(Object.keys(handle)).toEqual(["showFeature"]);
  });

  it("the pre-marked button wins even when it is not the first", async () => {
    const { initSubNav } = await subnav();
    const { page, buttons, panels } = buildPage({ activeIndex: 2 });
    initSubNav(page);
    expect(page.dataset.activeFeature).toBe("c");
    expect(shown(panels)).toEqual(["c"]);
    expect(actived(buttons)).toEqual(["c"]);
  });

  it("with nothing pre-marked the first button wins", async () => {
    const { initSubNav } = await subnav();
    const { page, buttons, panels } = buildPage({ activeIndex: -1 });
    initSubNav(page);
    expect(page.dataset.activeFeature).toBe("a");
    expect(shown(panels)).toEqual(["a"]);
    expect(actived(buttons)).toEqual(["a"]);
  });

  it("fireInitialOnShow:false sets the DOM without calling onShow", async () => {
    const { initSubNav } = await subnav();
    const { page, panels } = buildPage();
    const onShow = vi.fn();
    initSubNav(page, { onShow, fireInitialOnShow: false });
    expect(page.dataset.activeFeature).toBe("a");
    expect(shown(panels)).toEqual(["a"]);
    expect(onShow).not.toHaveBeenCalled();
  });

  it("survives a page with no buttons at all, and no onShow", async () => {
    const { initSubNav } = await subnav();
    const page = document.createElement("div");
    page.className = "page";
    document.body.appendChild(page);
    built.push(page);
    expect(() => initSubNav(page)).not.toThrow();
    expect(page.dataset.activeFeature).toBeUndefined();
    // No callback given: the initial switch must not reach for one.
    const plain = buildPage();
    expect(() => initSubNav(plain.page)).not.toThrow();
    expect(plain.page.dataset.activeFeature).toBe("a");
  });
});

describe("switching", () => {
  it("a click swaps the panel, the active class and the dataset, and reports the previous feature", async () => {
    const { initSubNav } = await subnav();
    const { page, buttons, panels } = buildPage();
    const onShow = vi.fn();
    initSubNav(page, { onShow });
    onShow.mockClear();

    await userEvent.setup().click(buttons[1]);
    expect(page.dataset.activeFeature).toBe("b");
    expect(shown(panels)).toEqual(["b"]);
    expect(actived(buttons)).toEqual(["b"]);
    expect(onShow).toHaveBeenCalledExactlyOnceWith("b", "a");
  });

  it("re-selecting the active feature is a no-op", async () => {
    const { initSubNav } = await subnav();
    const { page, buttons } = buildPage();
    const onShow = vi.fn();
    const { showFeature } = initSubNav(page, { onShow });
    onShow.mockClear();

    await userEvent.setup().click(buttons[0]);
    showFeature("a");
    expect(onShow).not.toHaveBeenCalled();
    expect(page.dataset.activeFeature).toBe("a");
  });

  it("the returned showFeature drives the same path as a click", async () => {
    const { initSubNav } = await subnav();
    const { page, buttons, panels } = buildPage();
    const onShow = vi.fn();
    const { showFeature } = initSubNav(page, { onShow });
    onShow.mockClear();

    showFeature("c");
    expect(shown(panels)).toEqual(["c"]);
    expect(actived(buttons)).toEqual(["c"]);
    expect(onShow).toHaveBeenCalledExactlyOnceWith("c", "a");
  });

  it("a name no panel carries hides everything and de-activates every button", async () => {
    // Characterization: showFeature validates nothing, so a typo blanks the
    // page rather than throwing. No caller does this today.
    const { initSubNav } = await subnav();
    const { page, buttons, panels } = buildPage();
    const { showFeature } = initSubNav(page);
    showFeature("nope");
    expect(shown(panels)).toEqual([]);
    expect(actived(buttons)).toEqual([]);
    expect(page.dataset.activeFeature).toBe("nope");
  });
});

describe("what it ignores", () => {
  it("a click on the nav that is not a sub-nav button", async () => {
    const { initSubNav } = await subnav();
    const { page } = buildPage();
    const nav = page.querySelector(".sub-nav");
    const stray = document.createElement("span");
    nav.appendChild(stray);
    const onShow = vi.fn();
    initSubNav(page, { onShow });
    onShow.mockClear();

    await userEvent.setup().click(stray);
    expect(onShow).not.toHaveBeenCalled();
    expect(page.dataset.activeFeature).toBe("a");
  });

  it("buttons carrying no data-feature — the real Low Stock tab bar", async () => {
    // Low Stock's `.sub-nav` is styling only: its buttons carry `data-bucket`
    // and it swaps rows inside one list instead of `.feature-panel`s. Pointed
    // at it, initSubNav initialises to nothing and every click falls through.
    const { initSubNav } = await subnav();
    const page = document.getElementById("low-stock-page");
    const onShow = vi.fn();
    initSubNav(page, { onShow });
    expect(page.dataset.activeFeature).toBeUndefined();
    expect(onShow).not.toHaveBeenCalled();

    await userEvent.setup().click(page.querySelector('.sub-nav-btn[data-bucket="week"]'));
    expect(page.dataset.activeFeature).toBeUndefined();
    expect(onShow).not.toHaveBeenCalled();
  });

  it("a page with no .sub-nav still initialises; its buttons are simply dead", async () => {
    const { initSubNav } = await subnav();
    const { page, buttons, panels } = buildPage({ withNav: false });
    const onShow = vi.fn();
    initSubNav(page, { onShow });
    expect(page.dataset.activeFeature).toBe("a");
    expect(shown(panels)).toEqual(["a"]);
    expect(onShow).toHaveBeenCalledExactlyOnceWith("a", null);
    onShow.mockClear();

    await userEvent.setup().click(buttons[1]);
    expect(page.dataset.activeFeature).toBe("a");
    expect(onShow).not.toHaveBeenCalled();
  });
});
