// Characterization coverage for the two custody editors — views/toolCheckout.js
// and views/toolReturn.js — plus the checkout tool picker in views/tools.js
// that opens the first of them.
//
// Both editors are entered the way a user enters them: a chosen user's card,
// then either the tool search (checkout) or a holding's Check In (return). The
// `onSaved` callback is tools.js's real `refreshTools`, so the second
// `GET /tools/` and the card repaint are part of every save assertion.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import {
  checkinBtn, checkoutOptions, chooseUser, el, holdingRows,
  openTools, requestFor, requests, restoreTools,
} from "../helpers/tools.js";
import { importView } from "../helpers/shell.js";
import { tool, toolCustodyEntry, user as userFactory } from "../helpers/factories.js";

afterEach(() => restoreTools());

const DRILL = () => tool({ name: "Drill", barcode: "T1", quantity: "3" });

// A mounted page with a chosen user. `tools` may be a function of that user,
// for the holdings a Check In needs. `fake` installs fake timers before the
// mount, for the tests that advance the editors' 1 s auto-close.
async function withUser({ role = "admin", tools = [], fake = false } = {}) {
  if (fake) vi.useFakeTimers();
  const user = userEvent.setup(fake ? { advanceTimers: vi.advanceTimersByTime } : {});
  const holder = userFactory({ full_name: "Ann Holder" });
  const mounted = await openTools({
    role, users: [holder], tools: typeof tools === "function" ? tools(holder) : tools,
  });
  await chooseUser(holder, user);
  return { ...mounted, holder, user };
}

const heldBy = (holder, quantity = "2") => tool({
  name: "Drill", barcode: "T1", quantity: "3",
  custody: [toolCustodyEntry({ user_id: holder.id, user_name: holder.full_name, quantity })],
});

async function openCheckout(ctx, index = 0) {
  await ctx.user.click(el.checkoutSearch());
  await ctx.user.click(checkoutOptions()[index]);
  expect(el.checkoutSection().hidden).toBe(false);
}

const optionNames = () =>
  checkoutOptions().map((option) => option.querySelector(".manual-item-name").textContent);

// `formatError` falls back when the detail is null, so this is how the
// module's own copy — rather than the server's — reaches the message slot.
const answer = (method, path, status = null, detail = null) =>
  server.use(http[method](path, () => (status
    ? HttpResponse.json({ detail }, { status })
    : HttpResponse.json({ ok: true }))));

describe("the checkout tool picker", () => {
  it("lists tools with stock on hand, name-sorted and capped at eight", async () => {
    const stocked = Array.from({ length: 9 }, (_, i) =>
      tool({ name: `Tool ${String(9 - i).padStart(2, "0")}`, barcode: `B${i}`, quantity: "1" }));
    const empty = tool({ name: "Aardvark", barcode: "B9", quantity: "0" });
    const ctx = await withUser({ tools: [...stocked, empty] });

    await ctx.user.click(el.checkoutSearch());
    expect(el.checkoutResults().hidden).toBe(false);
    expect(checkoutOptions()).toHaveLength(8);
    expect(optionNames()[0]).toBe("Tool 01");            // sorted, and the 0-stock tool is gone
    expect(optionNames()).not.toContain("Aardvark");
  });

  it("renders each option's barcode and on-hand count", async () => {
    const ctx = await withUser({ tools: [DRILL()] });
    await ctx.user.click(el.checkoutSearch());
    expect(checkoutOptions()[0].querySelector(".manual-item-meta").textContent)
      .toBe("Barcode: T1On hand: 3");
  });

  it("says nothing is available, and says nothing matches once a search is typed", async () => {
    const ctx = await withUser({ tools: [tool({ name: "Drill", quantity: "0" })] });
    await ctx.user.click(el.checkoutSearch());
    expect(el.checkoutResults().textContent).toBe("No tools are currently available.");

    await ctx.user.type(el.checkoutSearch(), "zzz");
    expect(el.checkoutResults().textContent).toBe("No available tools match that search.");
  });

  it("Escape hides the results; Enter opens the first option", async () => {
    const ctx = await withUser({ tools: [DRILL()] });
    await ctx.user.click(el.checkoutSearch());
    await ctx.user.keyboard("{Escape}");
    expect(el.checkoutResults().hidden).toBe(true);

    await ctx.user.click(el.checkoutSearch());
    await ctx.user.keyboard("{Enter}");
    expect(el.checkoutSection().hidden).toBe(false);
    expect(el.checkoutSelected().textContent).toBe("Drill (T1) — 3 on hand");
  });

  it("typing again closes an open checkout editor", async () => {
    const ctx = await withUser({ tools: [DRILL()] });
    await openCheckout(ctx);
    await ctx.user.type(el.checkoutSearch(), "x");
    expect(el.checkoutSection().hidden).toBe(true);
    expect(el.checkoutResults().hidden).toBe(false);
  });
});

describe("opening the checkout editor", () => {
  it("names the tool and the user, prefills one and caps at the on-hand count", async () => {
    const ctx = await withUser({ tools: [DRILL()] });
    await openCheckout(ctx);

    expect(el.checkoutSelected().textContent).toBe("Drill (T1) — 3 on hand");
    expect(el.checkoutUserSummary().textContent).toBe("Checking out to Ann Holder");
    expect(el.checkoutQuantity().value).toBe("1");
    expect(el.checkoutQuantity().max).toBe("3");
    expect(el.checkoutWorkOrder().value).toBe("");
    expect(el.checkoutMessage().textContent).toBe("");
    expect(el.checkoutSearch().value).toBe("Drill");
    expect(el.checkoutResults().hidden).toBe(true);
    expect(document.activeElement).toBe(el.checkoutQuantity());
  });

  it("closes the return editor first", async () => {
    const ctx = await withUser({ tools: (holder) => [heldBy(holder)] });
    await ctx.user.click(checkinBtn());
    expect(el.returnSection().hidden).toBe(false);

    await openCheckout(ctx);
    expect(el.returnSection().hidden).toBe(true);
  });
});

describe("the checkout ladder", () => {
  it("refuses a save with nothing open", async () => {
    await withUser({ tools: [DRILL()] });
    el.checkoutSaveBtn().click();
    await vi.waitFor(() => expect(el.checkoutMessage().textContent).toBe("Select a user and tool first."));
    expect(el.checkoutMessage().className).toBe("error");
    expect(requests()).toHaveLength(0);
  });

  it.each([
    ["a blank quantity", "", "Enter a quantity greater than zero."],
    ["zero", "0", "Enter a quantity greater than zero."],
    ["more than is on hand", "4", "Only 3 on hand."],
  ])("refuses %s", async (_label, value, expected) => {
    const ctx = await withUser({ tools: [DRILL()] });
    await openCheckout(ctx);
    el.checkoutQuantity().value = value;
    el.checkoutSaveBtn().click();

    await vi.waitFor(() => expect(el.checkoutMessage().className).toBe("error"));
    expect(el.checkoutMessage().textContent).toBe(expected);
    expect(requests()).toHaveLength(0);
    expect(el.checkoutSection().hidden).toBe(false);
  });
});

describe("saving a checkout", () => {
  it("posts the quantity, the user and a null work order, then refreshes and closes", async () => {
    const drill = DRILL();
    const ctx = await withUser({ tools: [drill], fake: true });
    answer("post", `/tools/${drill.id}/checkout`);
    await openCheckout(ctx);

    // The refresh answer differs from the load's, so the repaint is visible.
    const afterSave = tool({
      ...drill, quantity: "1",
      custody: [toolCustodyEntry({ user_id: ctx.holder.id, user_name: "Ann Holder", quantity: "2" })],
    });
    server.use(http.get("/tools/", () => HttpResponse.json([afterSave])));

    el.checkoutQuantity().value = "2";
    el.checkoutSaveBtn().click();

    await vi.waitFor(() =>
      expect(el.checkoutMessage().textContent).toBe("Checked out Drill to Ann Holder."));
    expect(el.checkoutMessage().className).toBe("success");
    expect(requestFor(`/tools/${drill.id}/checkout`, "POST").body)
      .toEqual({ quantity: 2, assigned_to_id: ctx.holder.id, work_order_number: null });

    await vi.waitFor(() => expect(holdingRows()).toHaveLength(1));
    expect(requestFor("/tools/", "GET")).not.toBeNull();
    expect(el.custodyCount().textContent).toBe("1 tool record currently checked out");

    expect(el.checkoutSection().hidden).toBe(false);
    await vi.advanceTimersByTimeAsync(1000);
    expect(el.checkoutSection().hidden).toBe(true);
    expect(el.checkoutQuantity().value).toBe("1");
    expect(el.checkoutQuantity().hasAttribute("max")).toBe(false);
  });

  it("trims a work order number into the body", async () => {
    const drill = DRILL();
    const ctx = await withUser({ tools: [drill] });
    answer("post", `/tools/${drill.id}/checkout`);
    await openCheckout(ctx);
    el.checkoutWorkOrder().value = "  4242  ";
    el.checkoutSaveBtn().click();

    await vi.waitFor(() => expect(el.checkoutMessage().className).toBe("success"));
    expect(requestFor(`/tools/${drill.id}/checkout`, "POST").body.work_order_number).toBe("4242");
  });

  it("keeps the editor open on a failure, with the server's copy", async () => {
    const drill = DRILL();
    const ctx = await withUser({ tools: [drill] });
    answer("post", `/tools/${drill.id}/checkout`, 409, "That tool is already out.");
    await openCheckout(ctx);
    el.checkoutSaveBtn().click();

    await vi.waitFor(() => expect(el.checkoutMessage().className).toBe("error"));
    expect(el.checkoutMessage().textContent).toBe("That tool is already out.");
    expect(el.checkoutSection().hidden).toBe(false);
    expect(el.checkoutQuantity().max).toBe("3");
  });

  it("Cancel clears the editor and drops the cap", async () => {
    const ctx = await withUser({ tools: [DRILL()] });
    await openCheckout(ctx);
    el.checkoutQuantity().value = "3";
    el.checkoutWorkOrder().value = "4242";
    await ctx.user.click(el.checkoutCancelBtn());

    expect(el.checkoutSection().hidden).toBe(true);
    expect(el.checkoutQuantity().value).toBe("1");
    expect(el.checkoutQuantity().hasAttribute("max")).toBe(false);
    expect(el.checkoutWorkOrder().value).toBe("");
    expect(el.checkoutMessage().textContent).toBe("");
  });
});

describe("the return ladder", () => {
  async function withHolding({ fake = false, quantity = "2" } = {}) {
    let drill = null;
    const ctx = await withUser({
      fake,
      tools: (holder) => { drill = heldBy(holder, quantity); return [drill]; },
    });
    await ctx.user.click(checkinBtn());
    expect(el.returnSection().hidden).toBe(false);
    return { ...ctx, drill };
  }

  it("refuses a save with nothing open", async () => {
    await withUser({ tools: [DRILL()] });
    el.returnSaveBtn().click();
    await vi.waitFor(() => expect(el.returnMessage().textContent).toBe("Select a checked-out tool first."));
    expect(el.returnMessage().className).toBe("error");
    expect(requests()).toHaveLength(0);
  });

  it.each([
    ["a blank quantity", "", "Enter a quantity greater than zero."],
    ["zero", "0", "Enter a quantity greater than zero."],
    ["more than is checked out", "3", "Only 2 checked out."],
  ])("refuses %s", async (_label, value, expected) => {
    await withHolding();
    el.returnQuantity().value = value;
    el.returnSaveBtn().click();

    await vi.waitFor(() => expect(el.returnMessage().className).toBe("error"));
    expect(el.returnMessage().textContent).toBe(expected);
    expect(requests()).toHaveLength(0);
    expect(el.returnSection().hidden).toBe(false);
  });

  it("posts the return, refreshes the card and closes a second later", async () => {
    const ctx = await withHolding({ fake: true });
    answer("post", `/tools/${ctx.drill.id}/return`);
    server.use(http.get("/tools/", () =>
      HttpResponse.json([tool({ ...ctx.drill, quantity: "5", custody: [] })])));

    el.returnWorkOrder().value = " 4242 ";
    el.returnSaveBtn().click();

    await vi.waitFor(() =>
      expect(el.returnMessage().textContent).toBe("Checked in Drill for Ann Holder."));
    expect(el.returnMessage().className).toBe("success");
    expect(requestFor(`/tools/${ctx.drill.id}/return`, "POST").body)
      .toEqual({ quantity: 2, assigned_to_id: ctx.holder.id, work_order_number: "4242" });

    await vi.waitFor(() => expect(holdingRows()).toHaveLength(0));
    expect(el.custodyCount().textContent).toBe("0 tool records currently checked out");

    await vi.advanceTimersByTimeAsync(1000);
    expect(el.returnSection().hidden).toBe(true);
    // Close resets to 1, NOT to the outstanding balance the open prefilled.
    expect(el.returnQuantity().value).toBe("1");
    expect(el.returnQuantity().hasAttribute("max")).toBe(false);
  });

  it("keeps the editor open on a failure", async () => {
    const ctx = await withHolding();
    answer("post", `/tools/${ctx.drill.id}/return`, 500, "Returns are locked.");
    el.returnSaveBtn().click();

    await vi.waitFor(() => expect(el.returnMessage().className).toBe("error"));
    expect(el.returnMessage().textContent).toBe("Returns are locked.");
    expect(el.returnSection().hidden).toBe(false);
  });

  it("Cancel clears the editor and drops the cap", async () => {
    const ctx = await withHolding();
    await ctx.user.click(el.returnCancelBtn());
    expect(el.returnSection().hidden).toBe(true);
    expect(el.returnQuantity().value).toBe("1");
    expect(el.returnQuantity().hasAttribute("max")).toBe(false);
    expect(el.returnWorkOrder().value).toBe("");
  });
});

describe("the module surface", () => {
  // Every export driven by name, not through the host. `setOnSaved` replaces
  // the `refreshTools` tools.js registered at import, so a save that reaches
  // the spy and fires no second list request proves the setter is the seam.
  const listGets = () => requests().filter((r) => r.url === "/tools/" && r.method === "GET");

  it("openToolCheckout / closeToolCheckout / setOnSaved", async () => {
    const drill = DRILL();
    await openTools({ role: "admin", tools: [drill], users: [] });
    const checkout = await importView("views/toolCheckout.js");
    const holder = userFactory({ full_name: "Ann Holder" });
    const saved = vi.fn();
    checkout.setOnSaved(saved);
    answer("post", `/tools/${drill.id}/checkout`);

    checkout.openToolCheckout(drill, holder);
    expect(el.checkoutSection().hidden).toBe(false);
    expect(el.checkoutSelected().textContent).toBe("Drill (T1) — 3 on hand");

    el.checkoutSaveBtn().click();
    await vi.waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
    expect(listGets()).toHaveLength(0);

    checkout.closeToolCheckout();
    expect(el.checkoutSection().hidden).toBe(true);
    expect(el.checkoutQuantity().hasAttribute("max")).toBe(false);
  });

  it("openToolReturn / closeToolReturn / setOnSaved", async () => {
    const holder = userFactory({ full_name: "Ann Holder" });
    const drill = heldBy(holder, "2");
    await openTools({ role: "admin", tools: [drill], users: [holder] });
    const ret = await importView("views/toolReturn.js");
    const saved = vi.fn();
    ret.setOnSaved(saved);
    answer("post", `/tools/${drill.id}/return`);

    ret.openToolReturn(drill, holder, drill.custody[0]);
    expect(el.returnSection().hidden).toBe(false);
    expect(el.returnUserSummary().textContent).toBe("Ann Holder has 2 checked out");

    el.returnSaveBtn().click();
    await vi.waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
    expect(listGets()).toHaveLength(0);

    ret.closeToolReturn();
    expect(el.returnSection().hidden).toBe(true);
    expect(el.returnQuantity().hasAttribute("max")).toBe(false);
  });
});

describe("a refresh that fails after a successful save", () => {
  it("overwrites the success copy in both message slots", async () => {
    const drill = DRILL();
    const ctx = await withUser({ tools: [drill] });
    answer("post", `/tools/${drill.id}/checkout`);
    await openCheckout(ctx);
    // A null detail is what makes `friendlyError` fall through to the
    // module's own copy rather than the server's.
    server.use(http.get("/tools/", () => HttpResponse.json({ detail: null }, { status: 500 })));

    el.checkoutSaveBtn().click();
    const expected = "The change was saved, but tool data could not be refreshed.";
    await vi.waitFor(() => expect(el.message().textContent).toBe(expected));
    expect(el.message().className).toBe("error");
    expect(el.custodyMessage().textContent).toBe(expected);
    expect(el.custodyMessage().className).toBe("error");
    // The editor's own slot still reads success -- only the two page-level
    // slots carry the refresh failure.
    expect(el.checkoutMessage().textContent).toBe("Checked out Drill to Ann Holder.");
  });
});
