import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { mountView } from "../helpers/shell.js";
import { TIPS } from "../../../backend/static/tips.js";

const KEY = Object.keys(TIPS)[0];

let tooltip;
let user;
let trigger;

beforeEach(async () => {
  user = userEvent.setup({ document });
  tooltip = await mountView("tooltip.js");
  // A trigger of our own, so the test does not depend on which page fragment
  // happens to hand-author one.
  const host = document.createElement("div");
  host.innerHTML = tooltip.tipHtml(KEY);
  document.body.appendChild(host);
  trigger = host.querySelector("[data-tip]");
  tooltip.installTooltips();
});

const bubble = () => document.getElementById("tip-bubble");

describe("installTooltips", () => {
  it("opens a pinned tip on click and marks the trigger expanded", async () => {
    await user.click(trigger);
    expect(bubble().hidden).toBe(false);
    expect(bubble().textContent).toBe(TIPS[KEY].text);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(trigger.getAttribute("aria-describedby")).toBe("tip-bubble");
  });

  it("closes on a second click of the same trigger", async () => {
    await user.click(trigger);
    await user.click(trigger);
    expect(bubble().hidden).toBe(true);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });

  it("closes on a click elsewhere", async () => {
    await user.click(trigger);
    await user.click(document.body);
    expect(bubble().hidden).toBe(true);
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    await user.click(trigger);
    await user.keyboard("{Escape}");
    expect(bubble().hidden).toBe(true);
    expect(document.activeElement).toBe(trigger);
  });

  it("keeps a pinned tip open when the pointer leaves", async () => {
    await user.click(trigger);
    trigger.dispatchEvent(new Event("pointerleave"));
    expect(bubble().hidden).toBe(false);
  });

  it("moves the single bubble between triggers rather than opening a second", async () => {
    const second = document.createElement("div");
    second.innerHTML = tooltip.tipHtml(Object.keys(TIPS)[1]);
    document.body.appendChild(second);
    await user.click(trigger);
    await user.click(second.querySelector("[data-tip]"));
    expect(document.querySelectorAll("#tip-bubble")).toHaveLength(1);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });

  it("drops an orphaned bubble when a refresh removes the trigger", async () => {
    await user.click(trigger);
    trigger.remove();
    await user.click(document.body);
    expect(bubble().hidden).toBe(true);
  });

  it("closes on scroll, because the bubble is fixed and would detach", async () => {
    await user.click(trigger);
    window.dispatchEvent(new Event("scroll"));
    expect(bubble().hidden).toBe(true);
  });

  it("is idempotent -- a second install does not double-bind", async () => {
    tooltip.installTooltips();
    await user.click(trigger);
    await user.click(trigger);
    expect(bubble().hidden).toBe(true);
  });

  it("labels hand-authored triggers that omit the accessible name", async () => {
    const bare = document.createElement("button");
    bare.className = "tip-btn";
    bare.dataset.tip = KEY;
    document.body.appendChild(bare);
    vi.resetModules();
    const fresh = await mountView("tooltip.js");
    document.body.appendChild(bare);
    fresh.installTooltips();
    expect(bare.getAttribute("aria-label")).toBe(`Help: ${TIPS[KEY].label}`);
  });

  it("hides a trigger naming a key that does not exist", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const bad = document.createElement("button");
    bad.dataset.tip = "nope.missing";
    document.body.appendChild(bad);
    await user.click(bad);
    expect(bad.hidden).toBe(true);
    expect(bubble().hidden).toBe(true);
    expect(warn).toHaveBeenCalled();
  });
});

describe("closeTip", () => {
  it("is safe to call with nothing open", () => {
    expect(() => tooltip.closeTip()).not.toThrow();
  });

  it("clears the bubble text so no stale copy is left in the DOM", async () => {
    await user.click(trigger);
    tooltip.closeTip();
    expect(bubble().textContent).toBe("");
  });
});
