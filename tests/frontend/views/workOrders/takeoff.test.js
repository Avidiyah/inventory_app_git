// The card's Takeoff section: Team Lead+ plans material per order, and one tap
// turns a planned line into a real dispense (Takeoff spec, "Work-order card").

import { describe, expect, it, vi } from "vitest";
import {
  answerConfirm, card, cardBody, message, mountWorkOrders, openCard, requestFor, requests, respond,
} from "../../helpers/workOrders.js";
import {
  item as itemFactory, workOrderCard, workOrderDetail, workOrderItem,
} from "../../helpers/factories.js";
import { importView } from "../../helpers/shell.js";

const ITEM_ID = "10000000-0000-4000-8000-000000000001";
const LINE_ID = "60000000-0000-4000-8000-000000000001";
const line = (over = {}) => ({ id: LINE_ID, item_id: ITEM_ID, item_name: "Toilet", quantity: "4", ...over });

async function open({ role = "supervisor", crew = true, catalogue = [], ...overrides } = {}) {
  const detail = workOrderDetail(overrides);
  const { currentUser } = await mountWorkOrders({
    role,
    cards: [workOrderCard({ id: detail.id, number: detail.number, status: detail.status })],
    details: [detail],
    items: catalogue,
  });
  if (crew) {
    detail.assigned_to_ids = [currentUser.id];
    detail.assigned_to_names = ["Me"];
  }
  await openCard(0);
  return detail;
}

const click = (action, index = 0) =>
  card().querySelectorAll(`[data-action="${action}"]`)[index].click();
const $ = (sel) => cardBody().querySelector(sel);
const detailGets = (id) =>
  requests().filter((r) => r.method === "GET" && r.url === `/work-orders/${id}`).length;

describe("who sees what", () => {
  it("a Team Lead sees + Takeoff item, a technician does not", async () => {
    await open({ role: "supervisor" });
    expect($(".wo-takeoff-add .ms-item-search").placeholder).toContain("+ Takeoff item");
    expect(cardBody().querySelector('.wo-more-item[data-wo-tab="takeoff"]')).not.toBeNull();
  });

  it("a technician with no lines gets no section and no More entry", async () => {
    await open({ role: "technician" });
    expect($(".wo-takeoff-section")).toBeNull();
    expect($(".wo-takeoff-add")).toBeNull();
    expect(cardBody().querySelector('.wo-more-item[data-wo-tab="takeoff"]')).toBeNull();
  });

  it("a technician with lines sees them and Dispense, but nothing to plan with", async () => {
    await open({ role: "technician", takeoff: [line()] });
    expect($("#wo-tk-" + LINE_ID)).not.toBeNull();
    expect($('[data-action="open-dispense-takeoff"]')).not.toBeNull();
    expect($(".wo-takeoff-add")).toBeNull();
    expect($('[data-action="edit-takeoff"]')).toBeNull();
    expect($('[data-action="remove-takeoff"]')).toBeNull();
  });

  it("a technician off the crew sees lines without Dispense", async () => {
    await open({ role: "technician", crew: false, takeoff: [line()] });
    expect($("#wo-tk-" + LINE_ID)).not.toBeNull();
    expect($('[data-action="open-dispense-takeoff"]')).toBeNull();
  });

  it("More shows Takeoff · 3", async () => {
    await open({
      takeoff: [line(), line({ id: "6", item_id: "7", item_name: "Valve" }), line({ id: "8", item_id: "9", item_name: "Pipe" })],
    });
    expect($('.wo-more-item[data-wo-tab="takeoff"]').textContent).toBe("Takeoff · 3");
    const labels = [...cardBody().querySelectorAll(".wo-more-item")].map((b) => b.dataset.woTab);
    expect(labels).toEqual(["details", "takeoff"]);
  });

  it("completed order shows lines read-only", async () => {
    await open({ status: "completed", takeoff: [line()] });
    expect($("#wo-tk-" + LINE_ID).textContent).toContain("4 left of 4");
    expect($(".wo-takeoff-add")).toBeNull();
    expect($('[data-action="open-dispense-takeoff"]')).toBeNull();
    expect($('[data-action="edit-takeoff"]')).toBeNull();
    expect($('[data-action="remove-takeoff"]')).toBeNull();
  });
});

describe("a line", () => {
  it('shows "1 left of 4" when 3 were already logged for that item', async () => {
    await open({
      takeoff: [line({ quantity: "1" })],
      items: [workOrderItem({ item_id: ITEM_ID, quantity: "3" }), workOrderItem({ item_id: "other", quantity: "9" })],
    });
    expect($(".wo-takeoff-left").textContent).toBe("1 left of 4");
  });

  it('shows "4 left of 4" when nothing was dispensed', async () => {
    await open({ takeoff: [line()] });
    expect($(".wo-takeoff-left").textContent).toBe("4 left of 4");
  });
});

describe("dispense-takeoff", () => {
  it("pre-fills the remaining quantity", async () => {
    await open({ takeoff: [line({ quantity: "1" })] });
    click("open-dispense-takeoff");
    const form = $(".wo-takeoff-dispense");
    expect(form.hidden).toBe(false);
    expect(form.querySelector(".wo-tk-dispense-qty").value).toBe("1");
  });

  it("posts takeoff_line_id and refreshes on the Takeoff section", async () => {
    const detail = await open({ takeoff: [line()] });
    respond("post", "/work-orders/:id/items", { id: "wi1", item_quantity: "5" });
    click("open-dispense-takeoff");
    $(".wo-tk-dispense-qty").value = "2";
    click("dispense-takeoff");
    await vi.waitFor(() => expect(requestFor("/items", "POST")).not.toBeNull());
    expect(requestFor("/items", "POST").body).toEqual({
      item_id: ITEM_ID, quantity: 2, material_request_id: null, takeoff_line_id: LINE_ID,
    });
    await vi.waitFor(() => expect(detailGets(detail.id)).toBe(1));
    await vi.waitFor(() => expect(message().textContent).toBe("Dispensed."));
    expect(message().className).toBe("success");
    expect($(".wo-takeoff-section").open).toBe(true);
    expect($(".wo-materials-section").open).toBe(false);
  });

  it("asks for a re-count when the dispense leaves stock negative", async () => {
    await open({ takeoff: [line()] });
    respond("post", "/work-orders/:id/items", { id: "wi1", item_quantity: "-1" });
    click("open-dispense-takeoff");
    click("dispense-takeoff");
    await vi.waitFor(() => expect(message().textContent).toBe("Item added. Please re-count stock."));
    expect(message().className).toBe("error");
  });

  it("a stale line shows the server's message and refreshes nothing", async () => {
    const detail = await open({ takeoff: [line()] });
    respond("post", "/work-orders/:id/items",
      { detail: "This takeoff line changed. Refresh and try again." }, { status: 409 });
    click("open-dispense-takeoff");
    click("dispense-takeoff");
    await vi.waitFor(() =>
      expect(message().textContent).toBe("This takeoff line changed. Refresh and try again."));
    expect(message().className).toBe("error");
    expect(detailGets(detail.id)).toBe(0);
  });

  it.each(["", "0", "-1"])("refuses the quantity %o", async (qty) => {
    await open({ takeoff: [line()] });
    click("open-dispense-takeoff");
    $(".wo-tk-dispense-qty").value = qty;
    click("dispense-takeoff");
    await vi.waitFor(() =>
      expect(message().textContent).toBe("Enter a quantity greater than zero."));
    expect(requestFor("/items", "POST")).toBeNull();
  });

  it("the Dispense button toggles the form closed again", async () => {
    await open({ takeoff: [line()] });
    click("open-dispense-takeoff");
    click("open-dispense-takeoff");
    expect($(".wo-takeoff-dispense").hidden).toBe(true);
    expect($(".wo-takeoff-dispense").hasAttribute("data-live-keep")).toBe(false);
  });
});

describe("planning", () => {
  const toilet = itemFactory({ id: ITEM_ID, name: "Toilet", barcode: "T1" });

  it("add-takeoff posts the picked item and quantity, then shows the section", async () => {
    const detail = await open({ catalogue: [toilet] });
    respond("post", "/work-orders/:id/takeoff", line(), { status: 201 });
    const search = $(".wo-takeoff-add .ms-item-search");
    search.value = "toil";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    click("pick-item");
    expect($(".wo-takeoff-add").dataset.itemId).toBe(ITEM_ID);
    $(".wo-takeoff-add .wo-item-qty").value = "4";
    click("add-takeoff");
    await vi.waitFor(() => expect(requestFor("/takeoff", "POST")).not.toBeNull());
    expect(requestFor("/takeoff", "POST").body).toEqual({ item_id: ITEM_ID, quantity: 4 });
    await vi.waitFor(() => expect(detailGets(detail.id)).toBe(1));
    await vi.waitFor(() => expect(message().textContent).toBe("Added to takeoff."));
    expect($(".wo-takeoff-section").open).toBe(true);
  });

  it("a catalogue request raised from the takeoff chooser carries no work order id", async () => {
    await open({ catalogue: [toilet] });
    const search = $(".wo-takeoff-add .ms-item-search");
    search.value = "flux capacitor";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    const prompt = $(".wo-takeoff-add .catalogue-request");
    expect(prompt.dataset.searchedText).toBe("flux capacitor");
    expect(prompt.hasAttribute("data-work-order-id")).toBe(false);
    // Add Item beside it still links the order.
    const add = $(".wo-add-item .ms-item-search");
    add.value = "flux capacitor";
    add.dispatchEvent(new Event("input", { bubbles: true }));
    expect($(".wo-add-item .catalogue-request").dataset.workOrderId).toBeTruthy();
  });

  it("add-takeoff needs an item and a quantity first", async () => {
    await open({});
    click("add-takeoff");
    await vi.waitFor(() => expect(message().textContent).toBe("Search and pick an item first."));
    expect(requestFor("/takeoff", "POST")).toBeNull();
  });

  it("edit-takeoff patches the line by its id", async () => {
    await open({ takeoff: [line()] });
    respond("patch", "/work-orders/:id/takeoff/:lineId", line({ quantity: "6" }));
    $(".wo-tk-qty").value = "6";
    click("edit-takeoff");
    await vi.waitFor(() => expect(requestFor(`/takeoff/${LINE_ID}`, "PATCH")).not.toBeNull());
    expect(requestFor(`/takeoff/${LINE_ID}`, "PATCH").body).toEqual({ quantity: 6 });
  });

  it("remove-takeoff asks first, and No removes nothing", async () => {
    await open({ takeoff: [line()] });
    click("remove-takeoff");
    await answerConfirm(false);
    expect(requestFor("/takeoff/", "DELETE")).toBeNull();
  });

  it("remove-takeoff deletes the line once confirmed", async () => {
    await open({ takeoff: [line()] });
    respond("delete", "/work-orders/:id/takeoff/:lineId", null, { status: 204 });
    click("remove-takeoff");
    await answerConfirm(true);
    await vi.waitFor(() => expect(requestFor(`/takeoff/${LINE_ID}`, "DELETE")).not.toBeNull());
  });
});

describe("live updates", () => {
  it("a live patch keeps a half-typed dispense quantity and the open form", async () => {
    const detail = await open({ takeoff: [line()] });
    const live = await importView("views/workOrderLiveBody.js");
    click("open-dispense-takeoff");
    const qty = $(".wo-tk-dispense-qty");
    qty.value = "2";
    live.patchBodyLive({ ...detail, takeoff: [line({ quantity: "3" })] }, cardBody(), card());
    expect($(".wo-tk-dispense-qty").value).toBe("2");
    expect($(".wo-takeoff-dispense").hidden).toBe(false);
  });

  it("a live patch repaints the lines another session changed", async () => {
    const detail = await open({ takeoff: [line()] });
    const live = await importView("views/workOrderLiveBody.js");
    live.patchBodyLive({ ...detail, takeoff: [line({ quantity: "1" })] }, cardBody(), card());
    expect($(".wo-takeoff-left").textContent).toBe("1 left of 1");
  });
});
