// Characterization coverage for the Inventory half of views/tools.js: the Add
// Tool form and its scan widget on the create-item page, the tool table, and
// the three row actions — edit (the inline editor), correct (toolCorrection.js's
// wiring, P6 deviation 4) and delete (the real confirm overlay).
//
// The table lives in the `inventory` feature panel, which the page does not
// open on: every test here clicks the Inventory sub-nav button first, as a user
// does.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import {
  actionSelect, activeFeature, answerConfirm, answerDecode, answerToolLookup, el, headers,
  openTools, requestFor, requests, restoreTools, rows, upload,
} from "../helpers/tools.js";
import { importView } from "../helpers/shell.js";
import { tool, toolCustodyEntry } from "../helpers/factories.js";

afterEach(() => restoreTools());

const DRILL = () => tool({ name: "Drill", barcode: "T1", quantity: "3" });
const SAW = () => tool({ name: "Saw", barcode: "T2", quantity: "9" });

const cells = (rowIndex = 0) =>
  Array.from(rows()[rowIndex].querySelectorAll("td")).map((td) => td.textContent);

// Mounted, loaded, and switched to the Inventory feature.
async function openInventory({ role = "admin", tools = [], fake = false } = {}) {
  if (fake) vi.useFakeTimers();
  const user = userEvent.setup(fake ? { advanceTimers: vi.advanceTimersByTime } : {});
  const mounted = await openTools({ role, tools, users: [] });
  await user.click(el.subNavBtn("inventory"));
  expect(activeFeature()).toBe("inventory");
  return { ...mounted, user };
}

const answer = (method, path, status = null, detail = null) =>
  server.use(http[method](path, () => (status
    ? HttpResponse.json({ detail }, { status })
    : HttpResponse.json({ ok: true }))));

describe("the Add Tool form", () => {
  it.each([
    ["no barcode", "", "Drill"],
    ["no name", "T1", ""],
    ["neither", "", ""],
  ])("refuses %s", async (_label, barcode, name) => {
    await openTools({ role: "admin", users: [] });
    el.toolBarcode().value = barcode;
    el.toolName().value = name;
    el.createBtn().click();

    await vi.waitFor(() =>
      expect(el.createMessage().textContent).toBe("Enter a barcode and a tool name."));
    expect(el.createMessage().className).toBe("error");
    expect(requests()).toHaveLength(0);
  });

  it("posts the tool, then clears the fields and resets the quantity to one", async () => {
    await openTools({ role: "admin", users: [] });
    answer("post", "/tools/");
    el.toolBarcode().value = "T9";
    el.toolName().value = "Impact Driver";
    el.toolQuantity().value = "2.5";
    el.createBtn().click();

    await vi.waitFor(() => expect(el.createMessage().textContent).toBe("Tool saved."));
    expect(el.createMessage().className).toBe("success");
    expect(requestFor("/tools/", "POST").body)
      .toEqual({ barcode: "T9", name: "Impact Driver", quantity: 2.5 });
    expect(el.toolBarcode().value).toBe("");
    expect(el.toolName().value).toBe("");
    expect(el.toolQuantity().value).toBe("1");
  });

  it("a blank quantity posts one", async () => {
    await openTools({ role: "admin", users: [] });
    answer("post", "/tools/");
    el.toolBarcode().value = "T9";
    el.toolName().value = "Impact Driver";
    el.toolQuantity().value = "";
    el.createBtn().click();

    await vi.waitFor(() => expect(el.createMessage().className).toBe("success"));
    expect(requestFor("/tools/", "POST").body.quantity).toBe(1);
  });

  it("a failure keeps what was typed", async () => {
    await openTools({ role: "admin", users: [] });
    answer("post", "/tools/", 409, "That barcode is taken.");
    el.toolBarcode().value = "T9";
    el.toolName().value = "Impact Driver";
    el.createBtn().click();

    await vi.waitFor(() => expect(el.createMessage().className).toBe("error"));
    expect(el.createMessage().textContent).toBe("That barcode is taken.");
    expect(el.toolBarcode().value).toBe("T9");
    expect(el.toolName().value).toBe("Impact Driver");
  });
});

describe("the Add Tool scan widget", () => {
  it("a miss fills the barcode field and collapses the controls", async () => {
    const { user } = await openInventory({});
    answerDecode(["ZZ9"]);
    answerToolLookup("ZZ9", 404);
    await user.click(el.toolScanToggle());
    expect(el.toolScanControls().hidden).toBe(false);

    await upload(el.toolScanInput());
    await vi.waitFor(() => expect(el.toolBarcode().value).toBe("ZZ9"));
    expect(el.toolScanControls().hidden).toBe(true);
    expect(el.toolScanMessage().textContent).toBe("No tool matches that barcode.");
  });

  it("a hit warns with the owning tool's name and leaves the field alone", async () => {
    await openInventory({});
    answerDecode(["T1"]);
    answerToolLookup("T1", tool({ name: "Drill", barcode: "T1" }));
    await upload(el.toolScanInput());

    await vi.waitFor(() =>
      expect(el.toolScanMessage().textContent).toBe("Already in use by Drill."));
    expect(el.toolScanMessage().className).toBe("error");
    expect(el.toolBarcode().value).toBe("");
  });

  it("collapsing the controls stops the camera", async () => {
    const { mod, user } = await openInventory({});
    const stopLive = vi.spyOn(mod.toolScanWidget, "stopLive");
    await user.click(el.toolScanToggle());
    expect(stopLive).not.toHaveBeenCalled();
    await user.click(el.toolScanToggle());
    expect(el.toolScanControls().hidden).toBe(true);
    expect(stopLive).toHaveBeenCalledTimes(1);
  });
});

describe("the tool table", () => {
  it("renders the custody cell as 'name: quantity' joined by a line break", async () => {
    const shared = tool({
      name: "Drill", barcode: "T1", quantity: "3",
      custody: [
        toolCustodyEntry({ user_name: "Ann Holder", quantity: "1" }),
        toolCustodyEntry({ user_name: "Bob Other", quantity: "2" }),
      ],
    });
    await openInventory({ tools: [shared] });
    const custodyCell = rows()[0].querySelectorAll("td")[3];
    expect(custodyCell.innerHTML).toBe("Ann Holder: 1<br>Bob Other: 2");
  });

  it("renders an em dash when nobody holds the tool", async () => {
    await openInventory({ tools: [DRILL()] });
    expect(cells().slice(0, 4)).toEqual(["T1", "Drill", "3", "—"]);
  });

  it("offers the three row actions to a custody manager only", async () => {
    const drill = DRILL();
    await openInventory({ tools: [drill] });
    const select = actionSelect(0);
    expect(select.id).toBe(`tool-row-actions-${drill.id}`);
    expect(select.dataset.id).toBe(drill.id);
    expect(select.getAttribute("aria-label")).toBe("Actions for Drill");
    expect(Array.from(select.options).map((o) => o.value)).toEqual(["", "edit", "correct", "delete"]);
    expect(document.querySelector(`label[for="${select.id}"]`).className).toBe("sr-only");
  });

  it("renders no actions column below techfm_oa", async () => {
    await openInventory({ role: "supervisor", tools: [DRILL()] });
    expect(headers()).toEqual(["Barcode", "Name", "On Hand", "Checked Out"]);
    expect(actionSelect(0)).toBeNull();
    expect(cells()).toEqual(["T1", "Drill", "3", "—"]);
  });

  it("filters on name and barcode as the search is typed", async () => {
    const { user } = await openInventory({ tools: [DRILL(), SAW()] });
    expect(rows()).toHaveLength(2);

    await user.type(el.search(), "saw");
    expect(rows()).toHaveLength(1);
    expect(cells()[1]).toBe("Saw");

    await user.clear(el.search());
    await user.type(el.search(), "T1");
    expect(rows()).toHaveLength(1);
    expect(cells()[1]).toBe("Drill");
  });

  it.each([["admin", 5], ["supervisor", 4]])(
    "tells %s there are no tools yet, spanning %i columns", async (role, columns) => {
      await openInventory({ role, tools: [] });
      expect(rows()).toHaveLength(1);
      expect(rows()[0].querySelector("td").getAttribute("colspan")).toBe(String(columns));
      expect(rows()[0].textContent).toBe("No tools yet.");
    });

  it("tells a searcher that nothing matches", async () => {
    const { user } = await openInventory({ tools: [DRILL()] });
    await user.type(el.search(), "zzz");
    expect(rows()[0].textContent).toBe("No tools match that search.");
    expect(rows()[0].querySelector("td").getAttribute("colspan")).toBe("5");
  });
});

describe("the edit action", () => {
  async function openEditor(ctx) {
    await ctx.user.selectOptions(actionSelect(0), "edit");
    expect(el.editorSection().hidden).toBe(false);
    // The select always snaps back to its disabled placeholder.
    expect(actionSelect(0).value).toBe("");
  }

  it("opens prefilled and named", async () => {
    const ctx = await openInventory({ tools: [DRILL()] });
    await openEditor(ctx);
    expect(el.editorSelected().textContent).toBe("Editing: Drill (T1)");
    expect(el.editorBarcode().value).toBe("T1");
    expect(el.editorName().value).toBe("Drill");
    expect(el.editorMessage().textContent).toBe("");
  });

  it.each([["a blank barcode", "", "Drill"], ["a blank name", "T1", ""]])(
    "refuses %s", async (_label, barcode, name) => {
      const ctx = await openInventory({ tools: [DRILL()] });
      await openEditor(ctx);
      el.editorBarcode().value = barcode;
      el.editorName().value = name;
      el.editorSaveBtn().click();

      await vi.waitFor(() =>
        expect(el.editorMessage().textContent).toBe("Barcode and name are required."));
      expect(el.editorMessage().className).toBe("error");
      expect(requests()).toHaveLength(0);
      expect(el.editorSection().hidden).toBe(false);
    });

  it("PATCHes the trimmed pair, refreshes the table and closes a second later", async () => {
    const drill = DRILL();
    const ctx = await openInventory({ tools: [drill], fake: true });
    answer("patch", `/tools/${drill.id}`);
    await openEditor(ctx);

    server.use(http.get("/tools/", () =>
      HttpResponse.json([tool({ ...drill, name: "Hammer Drill", barcode: "T7" })])));
    el.editorBarcode().value = "  T7  ";
    el.editorName().value = "  Hammer Drill  ";
    el.editorSaveBtn().click();

    await vi.waitFor(() => expect(el.editorMessage().textContent).toBe("Tool updated."));
    expect(el.editorMessage().className).toBe("success");
    expect(requestFor(`/tools/${drill.id}`, "PATCH").body).toEqual({ barcode: "T7", name: "Hammer Drill" });
    await vi.waitFor(() => expect(cells()[1]).toBe("Hammer Drill"));

    expect(el.editorSection().hidden).toBe(false);
    await vi.advanceTimersByTimeAsync(1000);
    expect(el.editorSection().hidden).toBe(true);
  });

  it("keeps the editor open on a failure", async () => {
    const drill = DRILL();
    const ctx = await openInventory({ tools: [drill] });
    answer("patch", `/tools/${drill.id}`, 409, "That barcode is taken.");
    await openEditor(ctx);
    el.editorSaveBtn().click();

    await vi.waitFor(() => expect(el.editorMessage().className).toBe("error"));
    expect(el.editorMessage().textContent).toBe("That barcode is taken.");
    expect(el.editorSection().hidden).toBe(false);
  });

  it("Cancel closes it", async () => {
    const ctx = await openInventory({ tools: [DRILL()] });
    await openEditor(ctx);
    await ctx.user.click(el.editorCancelBtn());
    expect(el.editorSection().hidden).toBe(true);
  });
});

describe("the correct action", () => {
  it("opens the shared panel under the tool-correction ids and posts the adjustment", async () => {
    const drill = DRILL();
    const ctx = await openInventory({ tools: [drill] });
    const correction = await importView("views/toolCorrection.js");
    answer("post", `/tools/${drill.id}/adjust`);

    await ctx.user.selectOptions(actionSelect(0), "correct");
    expect(el.correctionSection().hidden).toBe(false);
    expect(el.correctionSelected().textContent).toBe("Correcting: Drill (T1)");
    expect(el.correctionCurrent().textContent).toBe("Current count: 3");
    expect(el.correctionQuantity().value).toBe("3");
    expect(correction.getCorrectingToolId()).toBe(drill.id);

    server.use(http.get("/tools/", () => HttpResponse.json([tool({ ...drill, quantity: "7" })])));
    el.correctionQuantity().value = "7";
    el.correctionReason().value = "recount";
    el.correctionSaveBtn().click();

    await vi.waitFor(() => expect(el.correctionMessage().textContent).toBe("Count corrected."));
    expect(requestFor(`/tools/${drill.id}/adjust`, "POST").body)
      .toEqual({ new_quantity: 7, reason: "recount" });
    // setOnSaved is wired to refreshTools, so the table repaints.
    await vi.waitFor(() => expect(cells()[2]).toBe("7"));
  });

  it("Cancel closes it and drops the editing id", async () => {
    const ctx = await openInventory({ tools: [DRILL()] });
    const correction = await importView("views/toolCorrection.js");
    await ctx.user.selectOptions(actionSelect(0), "correct");
    await ctx.user.click(el.correctionCancelBtn());
    expect(el.correctionSection().hidden).toBe(true);
    expect(correction.getCorrectingToolId()).toBeNull();
  });
});

describe("the delete action", () => {
  const archive = (id, status = null, detail = null) =>
    server.use(http.delete(`/tools/${id}`, () => (status
      ? HttpResponse.json({ detail }, { status })
      : new HttpResponse(null, { status: 204 }))));

  async function archiveRow(ctx, yes, index = 0) {
    const choosing = ctx.user.selectOptions(actionSelect(index), "delete");
    await answerConfirm(yes);
    await choosing;
  }

  it("asks before archiving and writes nothing when told no", async () => {
    const drill = DRILL();
    const ctx = await openInventory({ tools: [drill] });
    archive(drill.id);
    const choosing = ctx.user.selectOptions(actionSelect(0), "delete");

    await vi.waitFor(() => expect(document.getElementById("scan-confirm-overlay").hidden).toBe(false));
    expect(document.getElementById("scan-confirm-title").textContent)
      .toBe('Archive "Drill"? Its history will be kept.');
    document.getElementById("scan-confirm-no").click();
    await choosing;

    expect(requests()).toHaveLength(0);
    expect(el.message().textContent).toBe("");
    expect(rows()).toHaveLength(1);
  });

  it("archives on yes, names the tool and refreshes the table", async () => {
    const drill = DRILL();
    const ctx = await openInventory({ tools: [drill, SAW()] });
    archive(drill.id);
    server.use(http.get("/tools/", () => HttpResponse.json([SAW()])));

    await archiveRow(ctx, true);
    await vi.waitFor(() => expect(el.message().textContent).toBe('Archived "Drill".'));
    expect(el.message().className).toBe("success");
    expect(requestFor(`/tools/${drill.id}`, "DELETE")).not.toBeNull();
    await vi.waitFor(() => expect(rows()).toHaveLength(1));
    expect(cells()[1]).toBe("Saw");
  });

  it("closes an editor open on the archived tool", async () => {
    const drill = DRILL();
    const ctx = await openInventory({ tools: [drill] });
    archive(drill.id);
    server.use(http.get("/tools/", () => HttpResponse.json([])));

    await ctx.user.selectOptions(actionSelect(0), "edit");
    expect(el.editorSection().hidden).toBe(false);
    await archiveRow(ctx, true);
    await vi.waitFor(() => expect(el.editorSection().hidden).toBe(true));
  });

  it("closes a correction open on the archived tool", async () => {
    const drill = DRILL();
    const ctx = await openInventory({ tools: [drill] });
    const correction = await importView("views/toolCorrection.js");
    archive(drill.id);
    server.use(http.get("/tools/", () => HttpResponse.json([])));

    await ctx.user.selectOptions(actionSelect(0), "correct");
    await archiveRow(ctx, true);
    await vi.waitFor(() => expect(el.correctionSection().hidden).toBe(true));
    expect(correction.getCorrectingToolId()).toBeNull();
  });

  it("leaves an editor open on a different tool alone", async () => {
    const drill = DRILL();
    const saw = SAW();
    const ctx = await openInventory({ tools: [drill, saw] });
    archive(saw.id);
    server.use(http.get("/tools/", () => HttpResponse.json([drill])));

    await ctx.user.selectOptions(actionSelect(0), "edit");    // Drill
    expect(el.editorSelected().textContent).toBe("Editing: Drill (T1)");
    await archiveRow(ctx, true, 1);                            // archive Saw
    await vi.waitFor(() => expect(rows()).toHaveLength(1));
    expect(el.editorSection().hidden).toBe(false);
  });

  it("reports a failure and leaves the row", async () => {
    const drill = DRILL();
    const ctx = await openInventory({ tools: [drill] });
    archive(drill.id, 409, null);

    await archiveRow(ctx, true);
    await vi.waitFor(() => expect(el.message().className).toBe("error"));
    expect(el.message().textContent).toBe("Could not archive the tool. Try again.");
    expect(rows()).toHaveLength(1);
  });

  it("ignores an action on a row whose tool has left the cache", async () => {
    const ctx = await openInventory({ tools: [DRILL()] });
    actionSelect(0).dataset.id = "no-such-tool";
    await ctx.user.selectOptions(actionSelect(0), "edit");
    expect(el.editorSection().hidden).toBe(true);
    expect(requests()).toHaveLength(0);
  });
});
