import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { mountView } from "../helpers/shell.js";

let dom;
let user;
beforeEach(async () => {
  user = userEvent.setup({ document });
  dom = await mountView("dom.js");
});

const overlay = () => document.getElementById("scan-confirm-overlay");
const yes = () => document.getElementById("scan-confirm-yes");
const no = () => document.getElementById("scan-confirm-no");
const qtyInput = () => document.getElementById("scan-confirm-qty-input");

describe("the shell supplies every node dom.js captures", () => {
  // Renaming one of these in shell-tail.html turns confirmDialog into its
  // silent no-modal fallback in production. This is the drift guard.
  it.each([
    "scan-confirm-overlay", "scan-confirm-title", "scan-confirm-yes", "scan-confirm-no",
    "scan-confirm-qty", "scan-confirm-qty-input", "scan-confirm-qty-dec", "scan-confirm-qty-inc",
    "pw-reset-overlay", "pw-reset-new", "pw-reset-confirm", "pw-reset-save", "pw-reset-cancel",
    "user-name-overlay", "user-name-first", "user-name-last", "user-name-save", "user-name-cancel",
    "user-role-overlay", "user-role-select", "user-role-save", "user-role-cancel",
  ])("%s exists", (id) => {
    expect(document.getElementById(id), `${id} is missing from the shell`).not.toBeNull();
  });
});

describe("setMessage", () => {
  it("sets text and class", () => {
    const el = document.createElement("p");
    dom.setMessage(el, "Saved.", "success");
    expect(el.textContent).toBe("Saved.");
    expect(el.className).toBe("success");
  });

  it("clears both when given empty values", () => {
    const el = document.createElement("p");
    dom.setMessage(el, "x", "error");
    dom.setMessage(el, "", "");
    expect(el.textContent).toBe("");
    expect(el.className).toBe("");
  });

  it("writes text, never markup", () => {
    const el = document.createElement("p");
    dom.setMessage(el, "<b>x</b>", "");
    expect(el.querySelector("b")).toBeNull();
  });
});

describe("getNoteValueRaw", () => {
  it("reads the .note-value input", () => {
    const wrap = document.createElement("div");
    wrap.innerHTML = `<input class="note-value" value="42">`;
    expect(dom.getNoteValueRaw(wrap)).toBe("42");
  });

  it("returns an empty string when the row has no input", () => {
    expect(dom.getNoteValueRaw(document.createElement("div"))).toBe("");
  });
});

describe("confirmDialog", () => {
  it("shows the message as text and resolves true on Yes", async () => {
    const pending = dom.confirmDialog("Dispense <b>2</b> Bulb?");
    expect(overlay().hidden).toBe(false);
    expect(document.getElementById("scan-confirm-title").textContent).toBe("Dispense <b>2</b> Bulb?");
    expect(document.getElementById("scan-confirm-title").querySelector("b")).toBeNull();
    await user.click(yes());
    await expect(pending).resolves.toBe(true);
    expect(overlay().hidden).toBe(true);
  });

  it("resolves false on No", async () => {
    const pending = dom.confirmDialog("Sure?");
    await user.click(no());
    await expect(pending).resolves.toBe(false);
  });

  it("resolves false on Escape", async () => {
    const pending = dom.confirmDialog("Sure?");
    await user.keyboard("{Escape}");
    await expect(pending).resolves.toBe(false);
  });

  it("resolves false on a backdrop click but not on a click inside", async () => {
    const pending = dom.confirmDialog("Sure?");
    await user.click(document.getElementById("scan-confirm-title"));
    expect(overlay().hidden).toBe(false);
    overlay().dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await expect(pending).resolves.toBe(false);
  });

  it("focuses Yes, never the number input", async () => {
    const pending = dom.confirmDialog("Take how many?", { quantity: 3 });
    expect(document.activeElement).toBe(yes());
    await user.click(no());
    await pending;
  });

  it("renames the buttons and restores the originals afterwards", async () => {
    const originalYes = yes().textContent;
    const pending = dom.confirmDialog("Archive?", { confirmText: "Archive", cancelText: "Keep" });
    expect(yes().textContent).toBe("Archive");
    expect(no().textContent).toBe("Keep");
    await user.click(yes());
    await pending;
    expect(yes().textContent).toBe(originalYes);
  });

  it("hides the No button in dismissOnly mode and restores it", async () => {
    const pending = dom.confirmDialog("Heads up.", { dismissOnly: true });
    expect(no().hidden).toBe(true);
    expect(yes().textContent).toBe("Close");
    await user.click(yes());
    await pending;
    expect(no().hidden).toBe(false);
  });

  it("cleans up its listeners, so a second dialog is not double-resolved", async () => {
    const first = dom.confirmDialog("One?");
    await user.click(yes());
    await first;
    const second = dom.confirmDialog("Two?");
    await user.keyboard("{Escape}");
    await expect(second).resolves.toBe(false);
  });
});

describe("confirmDialog in quantity mode", () => {
  it("shows the stepper seeded with the requested amount", async () => {
    const pending = dom.confirmDialog("How many?", { quantity: 3 });
    expect(document.getElementById("scan-confirm-qty").hidden).toBe(false);
    expect(qtyInput().value).toBe("3");
    await user.click(yes());
    await expect(pending).resolves.toBe(3);
  });

  it("steps up and down by one and never below one", async () => {
    const pending = dom.confirmDialog("How many?", { quantity: 1 });
    await user.click(document.getElementById("scan-confirm-qty-dec"));
    expect(qtyInput().value).toBe("1");
    await user.click(document.getElementById("scan-confirm-qty-inc"));
    await user.click(document.getElementById("scan-confirm-qty-inc"));
    await user.click(yes());
    await expect(pending).resolves.toBe(3);
  });

  it("resolves a typed amount", async () => {
    const pending = dom.confirmDialog("How many?", { quantity: 2 });
    await user.clear(qtyInput());
    await user.type(qtyInput(), "7");
    await user.click(yes());
    await expect(pending).resolves.toBe(7);
  });

  it("falls back to the requested amount when the field is left unparseable", async () => {
    const pending = dom.confirmDialog("How many?", { quantity: 2 });
    await user.clear(qtyInput());
    await user.click(yes());
    await expect(pending).resolves.toBe(2);
  });

  it("resolves false -- never a bare true -- on No", async () => {
    const pending = dom.confirmDialog("How many?", { quantity: 2 });
    await user.click(no());
    await expect(pending).resolves.toBe(false);
  });

  it("hides the stepper again for the next generic dialog", async () => {
    const first = dom.confirmDialog("How many?", { quantity: 2 });
    await user.click(yes());
    await first;
    const second = dom.confirmDialog("Sure?");
    expect(document.getElementById("scan-confirm-qty").hidden).toBe(true);
    await user.click(yes());
    await second;
  });
});

describe("messageDialog", () => {
  it("resolves once the single button is pressed", async () => {
    const pending = dom.messageDialog("Import finished.");
    expect(no().hidden).toBe(true);
    await user.click(yes());
    await expect(pending).resolves.toBeUndefined();
  });
});

describe("confirmArchivedReuse", () => {
  it("returns the first attempt's value when it succeeds", async () => {
    const action = vi.fn().mockResolvedValue({ id: 1 });
    await expect(dom.confirmArchivedReuse(action)).resolves.toEqual({ id: 1 });
    expect(action).toHaveBeenCalledExactlyOnceWith(false);
    expect(overlay().hidden).toBe(true);
  });

  it("retries with the override flag when the user confirms a 409", async () => {
    const action = vi.fn()
      .mockRejectedValueOnce({ status: 409, detail: "archived" })
      .mockResolvedValueOnce({ id: 2 });
    const pending = dom.confirmArchivedReuse(action);
    await vi.waitFor(() => expect(overlay().hidden).toBe(false));
    await user.click(yes());
    await expect(pending).resolves.toEqual({ id: 2 });
    expect(action).toHaveBeenNthCalledWith(2, true);
  });

  it("throws {cancelled: true} when the user declines", async () => {
    const action = vi.fn().mockRejectedValue({ status: 409, detail: "archived" });
    // The rejection assertion is attached before the awaits below: the
    // dialog can settle while `user.click` is still resolving, and a
    // handler attached afterwards surfaces as an unhandled rejection.
    const pending = dom.confirmArchivedReuse(action);
    const rejected = expect(pending).rejects.toEqual({ cancelled: true });
    await vi.waitFor(() => expect(overlay().hidden).toBe(false));
    await user.click(no());
    await rejected;
    expect(action).toHaveBeenCalledTimes(1);
  });

  it("rethrows any other error unchanged, without prompting", async () => {
    const action = vi.fn().mockRejectedValue({ status: 400, detail: "Barcode in use" });
    await expect(dom.confirmArchivedReuse(action)).rejects.toEqual({ status: 400, detail: "Barcode in use" });
    expect(overlay().hidden).toBe(true);
  });

  it("uses the caller's message", async () => {
    const action = vi.fn().mockRejectedValue({ status: 409 });
    const pending = dom.confirmArchivedReuse(action, "Restore the archived tool?");
    const rejected = expect(pending).rejects.toEqual({ cancelled: true });
    await vi.waitFor(() =>
      expect(document.getElementById("scan-confirm-title").textContent).toBe("Restore the archived tool?"));
    await user.click(no());
    await rejected;
  });
});
