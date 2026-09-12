// Characterization coverage for the Tools page's contextual scanner and for
// `resetToolsView`.
//
// `toolsScanner` is one `mountScanner` widget serving two purposes: the default
// "lookup" context drops the scanned tool into Inventory, and the "checkout"
// context armed by the Scan Tool to Check Out button opens the checkout editor
// for the selected user. P5g owns mountScanner's own contract (decode, chooser,
// camera); what is pinned here is the two callbacks tools.js supplies, the
// sub-nav lifecycle hooks, and the reset.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import {
  activeFeature, answerDecode, answerToolLookup, checkoutOptions, chooseUser,
  el, openTools, restoreTools, rows, upload,
} from "../helpers/tools.js";
import { tool, user as userFactory } from "../helpers/factories.js";

afterEach(() => restoreTools());

const DRILL = () => tool({ name: "Drill", barcode: "T1", quantity: "3" });

const LOOKUP_HEADING = "Scan Tool Inventory";
const LOOKUP_HINT = "Scan a tool's barcode to find it in Inventory.";

async function mounted({ role = "admin", tools = [], withUser = true } = {}) {
  const user = userEvent.setup();
  const holder = userFactory({ full_name: "Ann Holder" });
  const ctx = await openTools({ role, tools, users: [holder] });
  if (withUser && role === "admin") await chooseUser(holder, user);
  return { ...ctx, holder, user };
}

// Answer the decode + lookup pair and drive the page's own file input.
async function scan(barcode, payload) {
  answerDecode([barcode]);
  answerToolLookup(barcode, payload);
  await upload(el.scanInput());
}

describe("the lookup context", () => {
  it("drops a found tool into Inventory, filtered and scrolled to", async () => {
    const drill = DRILL();
    const ctx = await mounted({ tools: [drill, tool({ name: "Saw", barcode: "T2" })] });
    await scan("T1", drill);

    await vi.waitFor(() => expect(activeFeature()).toBe("inventory"));
    expect(el.search().value).toBe("T1");
    expect(rows()).toHaveLength(1);
    expect(rows()[0].textContent).toContain("Drill");
    expect(ctx.scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center" });
  });

  it("a barcode no tool carries just says so", async () => {
    await mounted({ tools: [DRILL()] });
    await scan("ZZ9", 404);
    await vi.waitFor(() =>
      expect(el.scanMessage().textContent).toBe("No tool matches that barcode."));
    expect(activeFeature()).toBe("custody");
  });

  it("the Scan sub-nav button resets the widget and refreshes permission twice", async () => {
    // Its own listener fires before the sub-nav's delegated one, and the
    // sub-nav's onShow refreshes again -- two calls per click, by construction.
    const ctx = await mounted({ tools: [DRILL()] });
    const reset = vi.spyOn(ctx.mod.toolsScanner, "reset");
    const refresh = vi.spyOn(ctx.mod.toolsScanner, "refreshPermissionState");

    await ctx.user.click(el.subNavBtn("scan"));
    expect(activeFeature()).toBe("scan");
    expect(reset).toHaveBeenCalledTimes(1);
    expect(refresh).toHaveBeenCalledTimes(2);
    expect(el.scanHeading().textContent).toBe(LOOKUP_HEADING);
    expect(el.scanHint().textContent).toBe(LOOKUP_HINT);
  });
});

describe("arming the checkout context", () => {
  it("refuses without a selected user", async () => {
    const ctx = await mounted({ tools: [DRILL()], withUser: false });
    await ctx.user.click(el.checkoutScanBtn());
    expect(el.checkoutPickerMessage().textContent).toBe("Select an active user first.");
    expect(el.checkoutPickerMessage().className).toBe("error");
    expect(activeFeature()).toBe("custody");
  });

  it("refuses a supervisor, who is on their own card but cannot manage custody", async () => {
    const ctx = await mounted({ role: "supervisor", tools: [DRILL()] });
    expect(el.userCard().hidden).toBe(false);
    await ctx.user.click(el.checkoutScanBtn());
    expect(el.checkoutPickerMessage().textContent).toBe("Select an active user first.");
    expect(activeFeature()).toBe("custody");
  });

  it("names the user in the heading and hint, resets and opens the scan feature", async () => {
    const ctx = await mounted({ tools: [DRILL()] });
    const reset = vi.spyOn(ctx.mod.toolsScanner, "reset");
    const refresh = vi.spyOn(ctx.mod.toolsScanner, "refreshPermissionState");

    await ctx.user.click(el.checkoutScanBtn());
    expect(activeFeature()).toBe("scan");
    expect(el.scanHeading().textContent).toBe("Scan Tool for Checkout");
    expect(el.scanHint().textContent).toBe(
      "Scan a tool to check out to Ann Holder. You will confirm the quantity before saving.");
    expect(reset).toHaveBeenCalledTimes(1);
    // Twice again, for the mirror-image reason: the sub-nav's onShow refreshes
    // on entering `scan`, and the button refreshes once more after switching.
    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("closes both editors before switching", async () => {
    const ctx = await mounted({ tools: [DRILL()] });
    await ctx.user.click(el.checkoutSearch());
    await ctx.user.click(checkoutOptions()[0]);
    expect(el.checkoutSection().hidden).toBe(false);

    await ctx.user.click(el.checkoutScanBtn());
    expect(el.checkoutSection().hidden).toBe(true);
    expect(el.returnSection().hidden).toBe(true);
  });
});

describe("scanning for checkout", () => {
  it("opens the checkout editor on the custody feature and restores the lookup context", async () => {
    const drill = DRILL();
    const ctx = await mounted({ tools: [drill] });
    await ctx.user.click(el.checkoutScanBtn());

    await scan("T1", drill);
    await vi.waitFor(() => expect(el.checkoutSection().hidden).toBe(false));
    expect(activeFeature()).toBe("custody");
    expect(el.checkoutSelected().textContent).toBe("Drill (T1) — 3 on hand");
    expect(el.checkoutUserSummary().textContent).toBe("Checking out to Ann Holder");
    expect(el.returnSection().hidden).toBe(true);
    // The context is one-shot: the next scan is a lookup again.
    expect(el.scanHeading().textContent).toBe(LOOKUP_HEADING);
    expect(el.scanHint().textContent).toBe(LOOKUP_HINT);
  });

  it("refuses a tool with nothing on hand", async () => {
    const empty = tool({ name: "Drill", barcode: "T1", quantity: "0" });
    const ctx = await mounted({ tools: [empty] });
    await ctx.user.click(el.checkoutScanBtn());

    await scan("T1", empty);
    await vi.waitFor(() =>
      expect(el.scanMessage().textContent).toBe("Drill has no units on hand."));
    expect(el.scanMessage().className).toBe("error");
    expect(el.checkoutSection().hidden).toBe(true);
    expect(activeFeature()).toBe("scan");
  });

  it("refuses once a reload has dropped the user it was armed for", async () => {
    // N-P6-CHARACTERIZED: this guard's other half (`!canManageCustody()`) is
    // unreachable through the UI -- a non-manager is refused by the Scan Tool
    // to Check Out button before `scanPurpose` can ever become "checkout".
    const drill = DRILL();
    const ctx = await mounted({ tools: [drill] });
    await ctx.user.click(el.checkoutScanBtn());

    server.use(http.get("/users/", () =>
      HttpResponse.json([userFactory({ full_name: "Someone Else" })])));
    await ctx.mod.loadTools();

    await scan("T1", drill);
    await vi.waitFor(() => expect(el.scanMessage().textContent)
      .toBe("Select an active user before scanning for checkout."));
    expect(el.checkoutSection().hidden).toBe(true);
  });
});

describe("the sub-nav lifecycle hooks", () => {
  it("leaving Scan stops the camera and restores the lookup context", async () => {
    const ctx = await mounted({ tools: [DRILL()] });
    const stopLive = vi.spyOn(ctx.mod.toolsScanner, "stopLive");
    await ctx.user.click(el.checkoutScanBtn());
    expect(el.scanHeading().textContent).toBe("Scan Tool for Checkout");

    await ctx.user.click(el.subNavBtn("inventory"));
    expect(stopLive).toHaveBeenCalledTimes(1);
    expect(el.scanHeading().textContent).toBe(LOOKUP_HEADING);
    expect(el.scanHint().textContent).toBe(LOOKUP_HINT);
  });

  it("leaving Custody closes both editors and hides the checkout results", async () => {
    const ctx = await mounted({ tools: [DRILL()] });
    await ctx.user.click(el.checkoutSearch());
    await ctx.user.click(checkoutOptions()[0]);
    expect(el.checkoutSection().hidden).toBe(false);
    await ctx.user.click(el.checkoutSearch());
    expect(el.checkoutResults().hidden).toBe(false);

    await ctx.user.click(el.subNavBtn("inventory"));
    expect(el.checkoutSection().hidden).toBe(true);
    expect(el.returnSection().hidden).toBe(true);
    expect(el.checkoutResults().hidden).toBe(true);
  });

  it("leaving Inventory closes the editor and the correction panel", async () => {
    const drill = DRILL();
    const ctx = await mounted({ tools: [drill] });
    await ctx.user.click(el.subNavBtn("inventory"));
    const select = rows()[0].querySelector("select.row-actions-select");
    await ctx.user.selectOptions(select, "edit");
    expect(el.editorSection().hidden).toBe(false);

    await ctx.user.click(el.subNavBtn("custody"));
    expect(el.editorSection().hidden).toBe(true);
    expect(el.correctionSection().hidden).toBe(true);
  });
});

describe("resetToolsView", () => {
  it("empties every field, closes every panel and returns to Custody", async () => {
    const drill = DRILL();
    const ctx = await mounted({ tools: [drill] });
    const reset = vi.spyOn(ctx.mod.toolsScanner, "reset");
    const state = await import("../../../backend/static/state.js");

    // Populate: a chosen user, an open checkout, a filtered table, an open
    // editor, and the scan context armed.
    await ctx.user.click(el.checkoutSearch());
    await ctx.user.click(checkoutOptions()[0]);
    await ctx.user.click(el.subNavBtn("inventory"));
    await ctx.user.type(el.search(), "T1");
    await ctx.user.selectOptions(rows()[0].querySelector("select.row-actions-select"), "correct");
    expect(el.correctionSection().hidden).toBe(false);

    ctx.mod.resetToolsView();

    expect(el.userSearch().value).toBe("");
    expect(el.search().value).toBe("");
    expect(el.userResults().hidden).toBe(true);
    expect(el.userCard().hidden).toBe(true);
    expect(el.checkoutSection().hidden).toBe(true);
    expect(el.returnSection().hidden).toBe(true);
    expect(el.editorSection().hidden).toBe(true);
    expect(el.correctionSection().hidden).toBe(true);
    expect(el.checkoutSearch().value).toBe("");
    expect(el.custodyMessage().textContent).toBe("");
    expect(el.message().textContent).toBe("");
    expect(el.scanHeading().textContent).toBe(LOOKUP_HEADING);
    expect(activeFeature()).toBe("custody");
    expect(reset).toHaveBeenCalledTimes(1);
    expect(state.getTools()).toEqual([]);
    // renderTools is NOT called, so the last rows stay on screen until the
    // next load repaints them.
    expect(rows()).toHaveLength(1);
  });

  it("is a no-op-safe call on a page that was never loaded", async () => {
    const { mod } = await mounted({ tools: [] });
    expect(() => mod.resetToolsView()).not.toThrow();
    expect(activeFeature()).toBe("custody");
  });
});
