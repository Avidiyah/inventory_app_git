// The dropdown half of promptTime (spec 6). P3 layers the analog dial on
// the same export; these assertions must keep passing when it does.
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
  it("opens on the initial time, split across the three selects", async () => {
    const pending = dom.promptTime({ title: "When did you leave?", initial: initial() });
    expect(el("prompt-time-overlay").hidden).toBe(false);
    expect(el("prompt-time-title").textContent).toBe("When did you leave?");
    expect(el("prompt-time-hour").value).toBe("4");
    expect(el("prompt-time-minute").value).toBe("40");
    expect(el("prompt-time-meridiem").value).toBe("PM");
    await user.click(el("prompt-time-cancel"));
    await expect(pending).resolves.toBeNull();
  });

  it("resolves the chosen time on the initial's own calendar day", async () => {
    const pending = dom.promptTime({ initial: initial() });
    await user.selectOptions(el("prompt-time-hour"), "9");
    await user.selectOptions(el("prompt-time-minute"), "05");
    await user.selectOptions(el("prompt-time-meridiem"), "AM");
    await user.click(el("prompt-time-save"));
    const chosen = await pending;
    expect(chosen.getFullYear()).toBe(2026);
    expect(chosen.getMonth()).toBe(8);
    expect(chosen.getDate()).toBe(21);
    expect(chosen.getHours()).toBe(9);
    expect(chosen.getMinutes()).toBe(5);
    expect(chosen.getSeconds()).toBe(0);
  });

  it.each([[-15, "4", "25", "PM"], [-5, "4", "35", "PM"], [5, "4", "45", "PM"], [15, "4", "55", "PM"]])(
    "the %i nudge moves the selects",
    async (delta, hour, minute, meridiem) => {
      const pending = dom.promptTime({ initial: initial() });
      await user.click(document.querySelector(`[data-nudge="${delta}"]`));
      expect(el("prompt-time-hour").value).toBe(hour);
      expect(el("prompt-time-minute").value).toBe(minute);
      expect(el("prompt-time-meridiem").value).toBe(meridiem);
      await user.click(el("prompt-time-cancel"));
      await pending;
    });

  it("a nudge across noon flips the meridiem", async () => {
    const pending = dom.promptTime({ initial: new Date(2026, 8, 21, 11, 55) });
    await user.click(document.querySelector('[data-nudge="15"]'));
    expect(el("prompt-time-hour").value).toBe("12");
    expect(el("prompt-time-minute").value).toBe("10");
    expect(el("prompt-time-meridiem").value).toBe("PM");
    await user.click(el("prompt-time-cancel"));
    await pending;
  });

  it("a nudge never leaves the initial's calendar day", async () => {
    const pending = dom.promptTime({ initial: new Date(2026, 8, 21, 0, 5) });
    await user.click(document.querySelector('[data-nudge="-15"]'));
    expect(el("prompt-time-hour").value).toBe("12");
    expect(el("prompt-time-minute").value).toBe("00");
    expect(el("prompt-time-meridiem").value).toBe("AM");
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
