// promptTime: one typed time field plus nudge buttons (no spinner wheels).
import { beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { mountView } from "../helpers/shell.js";

let dom;
let user;
beforeEach(async () => {
  user = userEvent.setup({ document });
  dom = await mountView("dom.js");
});

const el = (id) => document.getElementById(id);
const initial = () => new Date(2026, 8, 21, 16, 40);   // Mon 21 Sep 2026, 4:40 PM local

describe("promptTime", () => {
  it("opens on the initial time in one typed field", async () => {
    const pending = dom.promptTime({ title: "When did you leave?", initial: initial() });
    expect(el("prompt-time-overlay").hidden).toBe(false);
    expect(el("prompt-time-title").textContent).toBe("When did you leave?");
    expect(el("prompt-time-input").value).toBe("4:40 PM");
    expect(document.activeElement).toBe(el("prompt-time-input"));
    await user.click(el("prompt-time-cancel"));
    await expect(pending).resolves.toBeNull();
  });

  it("resolves the typed time on the initial's own calendar day", async () => {
    const pending = dom.promptTime({ initial: initial() });
    await user.clear(el("prompt-time-input"));
    await user.type(el("prompt-time-input"), "9:05 am");
    await user.click(el("prompt-time-save"));
    const chosen = await pending;
    expect(chosen.getFullYear()).toBe(2026);
    expect(chosen.getMonth()).toBe(8);
    expect(chosen.getDate()).toBe(21);
    expect(chosen.getHours()).toBe(9);
    expect(chosen.getMinutes()).toBe(5);
    expect(chosen.getSeconds()).toBe(0);
  });

  it("Enter in the field saves", async () => {
    const pending = dom.promptTime({ initial: initial() });
    await user.clear(el("prompt-time-input"));
    await user.type(el("prompt-time-input"), "1730{Enter}");
    const chosen = await pending;
    expect(chosen.getHours()).toBe(17);
    expect(chosen.getMinutes()).toBe(30);
  });

  it("refuses text that is not a time and keeps the dialog open", async () => {
    const pending = dom.promptTime({ initial: initial() });
    await user.clear(el("prompt-time-input"));
    await user.type(el("prompt-time-input"), "lunch");
    await user.click(el("prompt-time-save"));
    expect(el("prompt-time-overlay").hidden).toBe(false);
    expect(el("prompt-time-message").textContent).toMatch(/8:05 AM/);
    await user.click(el("prompt-time-cancel"));
    await expect(pending).resolves.toBeNull();
  });

  it.each([
    ["8:05", 485], ["805", 485], ["8:05a", 485], ["8:05 PM", 1205], ["17:30", 1050],
    ["12:00 am", 0], ["12:30pm", 750], ["0:15", 15], ["24:00", null], ["13:00 pm", null],
    ["8:60", null], ["", null],
  ])("parseTimeText(%j) -> %j", (text, minutes) => {
    expect(dom.parseTimeText(text)).toBe(minutes);
  });

  it.each([[-15, "4:25 PM"], [-5, "4:35 PM"], [5, "4:45 PM"], [15, "4:55 PM"]])(
    "the %i nudge rewrites the field",
    async (delta, text) => {
      const pending = dom.promptTime({ initial: initial() });
      await user.click(document.querySelector(`[data-nudge="${delta}"]`));
      expect(el("prompt-time-input").value).toBe(text);
      await user.click(el("prompt-time-cancel"));
      await pending;
    });

  it("a nudge across noon flips the meridiem", async () => {
    const pending = dom.promptTime({ initial: new Date(2026, 8, 21, 11, 55) });
    await user.click(document.querySelector('[data-nudge="15"]'));
    expect(el("prompt-time-input").value).toBe("12:10 PM");
    await user.click(el("prompt-time-cancel"));
    await pending;
  });

  it("a nudge never leaves the initial's calendar day", async () => {
    const pending = dom.promptTime({ initial: new Date(2026, 8, 21, 0, 5) });
    await user.click(document.querySelector('[data-nudge="-15"]'));
    expect(el("prompt-time-input").value).toBe("12:00 AM");
    await user.click(el("prompt-time-save"));
    const chosen = await pending;
    expect(chosen.getDate()).toBe(21);
  });

  it("Escape cancels", async () => {
    const pending = dom.promptTime({ initial: initial() });
    await user.keyboard("{Escape}");
    await expect(pending).resolves.toBeNull();
    expect(el("prompt-time-overlay").hidden).toBe(true);
  });

  it("emits no inline style attribute -- CSP drops them", () => {
    const pending = dom.promptTime({ initial: initial() });
    expect(el("prompt-time-overlay").querySelectorAll("[style]")).toHaveLength(0);
    el("prompt-time-cancel").click();
    return pending;
  });

  it("nests no button inside a button", () => {
    const pending = dom.promptTime({ initial: initial() });
    el("prompt-time-overlay").querySelectorAll("button").forEach((btn) => {
      expect(btn.querySelector("button")).toBeNull();
    });
    el("prompt-time-cancel").click();
    return pending;
  });
});
