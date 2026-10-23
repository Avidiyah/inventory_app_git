// Characterization: the fourteen editor / labor / materials / picker
// branches of the click delegation, plus the add-material input delegation.
//
// The other twelve branches (status lifecycle, NetFacilities, the shared
// error paths) are in actions.test.js. Split only because this repo caps a
// file at 500 lines; together the two files cover all 26 `data-action`s, and
// actionCoverage.test.js proves it mechanically.

import { describe, expect, it, vi } from "vitest";
import {
  answerConfirm, card, cardBody, message, mountWorkOrders, openCard,
  requestFor, requests, respond, seedDetail,
} from "../../helpers/workOrders.js";
import {
  item as itemFactory, user, workOrderCard, workOrderDetail, workOrderItem, workOrderLabor,
} from "../../helpers/factories.js";

// A supervisor sees every control in this file; the role gating itself is
// frozen in roles.test.js.
// `catalogue` is the item reference list the pickers search; `items` (via
// overrides) is the work order's own logged materials. Two different lists,
// deliberately not both called "items".
async function open({ role = "supervisor", catalogue = [], users = [], ...overrides } = {}) {
  const detail = workOrderDetail(overrides);
  await mountWorkOrders({
    role,
    cards: [workOrderCard({ id: detail.id, number: detail.number, status: detail.status })],
    details: [detail],
    items: catalogue,
    users,
  });
  await openCard(0);
  return detail;
}

const click = (action, index = 0) =>
  card().querySelectorAll(`[data-action="${action}"]`)[index].click();

const detailGets = (id) =>
  requests().filter((r) => r.method === "GET" && r.url === `/work-orders/${id}`).length;

const refreshed = (id, count = 1) =>
  vi.waitFor(() => expect(detailGets(id)).toBe(count));

// `setMessage` overwrites className, so a message element cannot be found by
// its own class once it holds a message. Both of these are positional.
const notesMessage = () =>
  card().querySelector(".wo-notes-section .wo-section-content").lastElementChild;

function type(input, value) {
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("cancel-edit", () => {
  it("re-fetches and discards the draft", async () => {
    const detail = await open({ role: "admin", location: "Hallway B" });
    card().querySelector(".wo-edit-card").open = true;
    card().querySelector(".wo-edit-location").value = "Somewhere else";
    click("cancel-edit");
    await refreshed(detail.id);
    await vi.waitFor(() =>
      expect(card().querySelector(".wo-edit-location").value).toBe("Hallway B"));
    // Rebuilt from scratch, so the editor is collapsed again.
    expect(card().querySelector(".wo-edit-card").open).toBe(false);
  });
});

describe("save-details", () => {
  it("sends every rendered field, trimmed, with the original supervisor id", async () => {
    const supervisorUser = user({ role: "supervisor", full_name: "Sue S" });
    const detail = workOrderDetail({ supervisor_id: supervisorUser.id });
    await mountWorkOrders({
      role: "admin",
      cards: [workOrderCard({ id: detail.id, number: detail.number })],
      details: [detail],
      users: [supervisorUser],
    });
    await openCard(0);
    respond("patch", "/work-orders/:id", detail);
    const body = cardBody();
    body.querySelector(".wo-edit-location").value = "  Hallway B  ";
    body.querySelector(".wo-edit-service-type").value = "Plumbing";
    body.querySelector(".wo-edit-priority").value = "Urgent";
    body.querySelector(".wo-edit-description").value = "";
    click("save-details");
    await vi.waitFor(() =>
      expect(requestFor(`/work-orders/${detail.id}`, "PATCH")).not.toBeNull());
    const sent = requestFor(`/work-orders/${detail.id}`, "PATCH").body;
    expect(sent).toEqual({
      // Observed: the row is `assigned` but carries no technicians, so the
      // editor offers `created` as its pre-work choice and `assigned` is not
      // among the options -- the select falls back to the first one, and a
      // save that touched nothing else silently rolls the status back.
      // Filed in docs/open-work.md.
      status: "created",
      location: "Hallway B",
      service_type: "Plumbing",
      schedule_date: "2026-09-10",
      output_to: null,
      vendor_assignee: null,
      description: null,
      priority: "Urgent",
      supervisor_id: String(supervisorUser.id),
      expected_supervisor_id: String(supervisorUser.id),
      assigned_to_ids: [],
    });
    await refreshed(detail.id);
  });

  it("omits the fields the editor never rendered", async () => {
    // A Supervisor's editor has no imported-metadata inputs, and no work
    // order has the legacy community/building/unit ones. `undefined` fields
    // are deleted rather than sent as null, which would wipe them.
    const detail = await open({ role: "supervisor" });
    respond("patch", "/work-orders/:id", detail);
    click("save-details");
    await vi.waitFor(() =>
      expect(requestFor(`/work-orders/${detail.id}`, "PATCH")).not.toBeNull());
    expect(Object.keys(requestFor(`/work-orders/${detail.id}`, "PATCH").body).sort())
      .toEqual(["assigned_to_ids", "expected_supervisor_id", "status", "supervisor_id"]);
  });

  it("collects assigned_to_ids from the technician selection rows", async () => {
    const detail = await open({
      assigned_to_ids: ["t1", "t2"], assigned_to_names: ["Ada L", "Grace H"],
    });
    respond("patch", "/work-orders/:id", detail);
    click("save-details");
    await vi.waitFor(() =>
      expect(requestFor(`/work-orders/${detail.id}`, "PATCH")).not.toBeNull());
    expect(requestFor(`/work-orders/${detail.id}`, "PATCH").body.assigned_to_ids)
      .toEqual(["t1", "t2"]);
  });

  it("sends a null supervisor when the combo is left Unassigned", async () => {
    const detail = await open({ supervisor_id: null });
    respond("patch", "/work-orders/:id", detail);
    click("save-details");
    await vi.waitFor(() =>
      expect(requestFor(`/work-orders/${detail.id}`, "PATCH")).not.toBeNull());
    const sent = requestFor(`/work-orders/${detail.id}`, "PATCH").body;
    expect(sent.supervisor_id).toBeNull();
    expect(sent.expected_supervisor_id).toBeNull();
  });
});

describe("save-notes", () => {
  it("refuses an empty note without issuing a request", async () => {
    const detail = await open({});
    card().querySelector(".wo-notes-input").value = "   ";
    click("save-notes");
    await vi.waitFor(() =>
      expect(notesMessage().textContent).toBe("Enter a note before saving."));
    expect(notesMessage().className).toBe("error");
    expect(requestFor(`/work-orders/${detail.id}`, "PATCH")).toBeNull();
  });

  it("patches the note, re-renders the log, and collapses the section", async () => {
    const detail = await open({ notes: "old line" });
    const section = card().querySelector(".wo-notes-section");
    section.open = true;
    respond("patch", "/work-orders/:id", { ...detail, notes: "old line\nnew line" });
    card().querySelector(".wo-notes-input").value = "  new line  ";
    click("save-notes");
    await vi.waitFor(() => expect(notesMessage().textContent).toBe("Note saved."));
    expect(requestFor(`/work-orders/${detail.id}`, "PATCH").body).toEqual({ notes: "new line" });
    expect(card().querySelector(".wo-notes-log").textContent).toBe("old line\nnew line");
    expect(card().querySelector(".wo-notes-input").value).toBe("");
    expect(section.open).toBe(false);
    // No card refresh: the log is repainted from the PATCH response.
    expect(detailGets(detail.id)).toBe(0);
  });
});

describe("add-skilled-labor", () => {
  it("posts a null technician with the skilled hours and reopens the section", async () => {
    const detail = await open({ role: "admin", smr: true, assigned_to_ids: ["t1"], assigned_to_names: ["Ada L"] });
    respond("post", "/work-orders/:id/labor", { ok: true });
    card().querySelector(".wo-new-skilled-hours").value = "0.5";
    click("add-skilled-labor");
    await vi.waitFor(() => expect(requestFor("/labor", "POST")).not.toBeNull());
    expect(requestFor("/labor", "POST").body).toEqual({ technician_id: null, minutes: 30 });
    await refreshed(detail.id);
    await vi.waitFor(() =>
      expect(card().querySelector(".wo-labor-section").open).toBe(true));
  });

  it("refuses blank skilled hours before anything is sent", async () => {
    await open({ role: "admin", smr: true, assigned_to_ids: ["t1"], assigned_to_names: ["Ada L"] });
    card().querySelector(".wo-new-skilled-hours").value = "";
    click("add-skilled-labor");
    await vi.waitFor(() =>
      expect(message().textContent).toBe("Enter Skilled Technician hours greater than zero."));
    expect(requestFor("/labor", "POST")).toBeNull();
  });
});

describe("add-labor", () => {
  it("needs a technician before anything is sent", async () => {
    // No assignment and no current user in the picker means the control
    // renders as a hint, so the Add button is absent entirely -- the
    // "Assign and select a technician first." guard is only reachable when
    // the select exists but holds no value.
    const detail = await open({ role: "admin", assigned_to_ids: [] });
    expect(card().querySelector(".wo-labor-technician")).not.toBeNull();
    card().querySelector(".wo-labor-technician").innerHTML = "";
    card().querySelector(".wo-new-labor-hours").value = "1";
    click("add-labor");
    await vi.waitFor(() =>
      expect(message().textContent).toBe("Assign and select a technician first."));
    expect(requestFor("/labor", "POST")).toBeNull();
  });

  it.each([["", "blank"], ["0", "zero"], ["-2", "negative"], ["abc", "non-numeric"]])(
    "refuses %s hours (%s)", async (value) => {
      const detail = await open({ role: "admin", assigned_to_ids: ["t1"], assigned_to_names: ["Ada L"] });
      card().querySelector(".wo-new-labor-hours").value = value;
      click("add-labor");
      await vi.waitFor(() =>
        expect(message().textContent).toBe("Enter actual labor hours greater than zero."));
      expect(requestFor("/labor", "POST")).toBeNull();
    });

  it("converts hours to minutes and reopens the labor section", async () => {
    const detail = await open({ role: "admin", assigned_to_ids: ["t1"], assigned_to_names: ["Ada L"] });
    respond("post", "/work-orders/:id/labor", { ok: true });
    card().querySelector(".wo-new-labor-hours").value = "1.25";
    click("add-labor");
    await vi.waitFor(() => expect(requestFor("/labor", "POST")).not.toBeNull());
    expect(requestFor("/labor", "POST").body).toEqual({ technician_id: "t1", minutes: 75 });
    await refreshed(detail.id);
    await vi.waitFor(() =>
      expect(card().querySelector(".wo-labor-section").open).toBe(true));
  });

  it("rounds a sub-minute entry up to one minute", async () => {
    await open({ role: "admin", assigned_to_ids: ["t1"], assigned_to_names: ["Ada L"] });
    respond("post", "/work-orders/:id/labor", { ok: true });
    card().querySelector(".wo-new-labor-hours").value = "0.001";
    click("add-labor");
    await vi.waitFor(() => expect(requestFor("/labor", "POST")).not.toBeNull());
    expect(requestFor("/labor", "POST").body.minutes).toBe(1);
  });

  // A Technician on the crew keys hours only for themselves (self-edit rules
  // in roles.test.js), so the picker holds just them; a session row stays read-only.
  it("a Technician on the crew adds only for themselves, and cannot touch a session row", async () => {
    const detail = workOrderDetail({ assigned_to_ids: [], labor: [workOrderLabor({ id: "l1" })] });
    const { currentUser } = await mountWorkOrders({
      role: "technician",
      cards: [workOrderCard({ id: detail.id, number: detail.number, status: detail.status })],
      details: [detail],
    });
    detail.assigned_to_ids = [currentUser.id];
    await openCard(0);
    expect(card().querySelector(".wo-labor-section")).not.toBeNull();
    expect([...card().querySelectorAll(".wo-labor-technician option")].map((o) => o.value))
      .toEqual([currentUser.id]);
    expect(card().querySelector('[data-action="edit-labor"]')).toBeNull();
    expect(card().querySelector('[data-action="remove-labor"]')).toBeNull();
    expect(card().querySelector(".wo-labor-section").textContent)
      .toContain("You can add or fix your own by hand this week.");
  });
});

describe("edit-labor and remove-labor", () => {
  const withEntry = () => open({ role: "admin",
    labor: [workOrderLabor({ id: "l1", minutes: 60, technician_name: "Ada L" })],
  });

  it("patches the row's own labor id", async () => {
    const detail = await withEntry();
    respond("patch", "/work-orders/:id/labor/:laborId", { ok: true });
    card().querySelector(".wo-labor-hours").value = "2";
    click("edit-labor");
    await vi.waitFor(() => expect(requestFor("/labor/l1", "PATCH")).not.toBeNull());
    expect(requestFor("/labor/l1", "PATCH").body).toEqual({ minutes: 120 });
    await refreshed(detail.id);
  });

  it("refuses zero hours on an update", async () => {
    await withEntry();
    card().querySelector(".wo-labor-hours").value = "0";
    click("edit-labor");
    await vi.waitFor(() =>
      expect(message().textContent).toBe("Enter actual labor hours greater than zero."));
    expect(requestFor("/labor/l1", "PATCH")).toBeNull();
  });

  it("asks before removing, and No removes nothing", async () => {
    await withEntry();
    click("remove-labor");
    await answerConfirm(false);
    expect(requestFor("/labor/l1", "DELETE")).toBeNull();
  });

  it("deletes on Yes and reopens the labor section", async () => {
    const detail = await withEntry();
    respond("delete", "/work-orders/:id/labor/:laborId", null, { status: 204 });
    click("remove-labor");
    await answerConfirm(true);
    await vi.waitFor(() => expect(requestFor("/labor/l1", "DELETE")).not.toBeNull());
    await refreshed(detail.id);
    await vi.waitFor(() =>
      expect(card().querySelector(".wo-labor-section").open).toBe(true));
  });
});

describe("the add-material search", () => {
  const bulb = itemFactory({ name: "Bulb", barcode: "B1" });

  it("ranks matches and caps the list at eight", async () => {
    const items = Array.from({ length: 12 }, (_, i) =>
      itemFactory({ name: `Bulb ${i}`, barcode: `B${i}` }));
    await open({ catalogue: items });
    type(card().querySelector(".ms-item-search"), "bulb");
    const results = card().querySelector(".ms-item-results");
    expect(results.hidden).toBe(false);
    expect(results.querySelectorAll('[data-action="pick-item"]')).toHaveLength(8);
  });

  it("hides the list again when the box is cleared", async () => {
    await open({ catalogue: [bulb] });
    const input = card().querySelector(".ms-item-search");
    type(input, "bulb");
    type(input, "");
    const results = card().querySelector(".ms-item-results");
    expect(results.hidden).toBe(true);
    expect(results.innerHTML).toBe("");
  });

  it("offers the catalogue request when nothing matches", async () => {
    const detail = await open({ catalogue: [bulb] });
    type(card().querySelector(".ms-item-search"), "flux capacitor");
    const prompt = card().querySelector(".catalogue-request");
    expect(prompt.dataset.source).toBe("work_orders");
    expect(prompt.dataset.workOrderId).toBe(String(detail.id));
    expect(prompt.dataset.searchedText).toBe("flux capacitor");
    expect(card().querySelector(".ms-item-results").textContent)
      .toContain("No matching items.");
  });

  it("pick-item stamps the id, fills the box and closes the list", async () => {
    await open({ catalogue: [bulb] });
    type(card().querySelector(".ms-item-search"), "bulb");
    click("pick-item");
    const container = card().querySelector(".wo-add-item");
    expect(container.dataset.itemId).toBe(String(bulb.id));
    expect(container.querySelector(".ms-item-search").value).toBe("Bulb");
    expect(container.querySelector(".ms-item-results").hidden).toBe(true);
    expect(document.activeElement).toBe(container.querySelector(".wo-item-qty"));
  });

  it("typing again clears the picked item", async () => {
    await open({ catalogue: [bulb] });
    const input = card().querySelector(".ms-item-search");
    type(input, "bulb");
    click("pick-item");
    type(input, "bul");
    expect(card().querySelector(".wo-add-item").dataset.itemId).toBeUndefined();
  });
});

describe("add-item", () => {
  const bulb = itemFactory({ name: "Bulb", barcode: "B1" });

  async function picked(qty) {
    const detail = await open({ catalogue: [bulb] });
    type(card().querySelector(".ms-item-search"), "bulb");
    click("pick-item");
    card().querySelector(".wo-item-qty").value = qty;
    return detail;
  }

  it("needs an item picked first", async () => {
    await open({ catalogue: [bulb] });
    card().querySelector(".wo-item-qty").value = "1";
    click("add-item");
    await vi.waitFor(() =>
      expect(message().textContent).toBe("Search and pick an item first."));
    expect(requestFor("/items", "POST")).toBeNull();
  });

  it.each(["", "0", "-1", "abc"])("refuses the quantity %o", async (qty) => {
    await picked(qty);
    click("add-item");
    await vi.waitFor(() =>
      expect(message().textContent).toBe("Enter a quantity greater than zero."));
    expect(requestFor("/items", "POST")).toBeNull();
  });

  it("posts the line, reopens Materials, and reports success", async () => {
    const detail = await picked("2");
    respond("post", "/work-orders/:id/items", { id: "wi1", item_quantity: "5" });
    seedDetail({ ...detail, items: [workOrderItem()] });
    click("add-item");
    await vi.waitFor(() => expect(requestFor("/items", "POST")).not.toBeNull());
    expect(requestFor("/items", "POST").body).toEqual({
      item_id: String(bulb.id), quantity: 2, material_request_id: null,
    });
    await vi.waitFor(() => expect(message().textContent).toBe("Item added."));
    expect(message().className).toBe("success");
    expect(card().querySelector(".wo-materials-section").open).toBe(true);
  });

  it("asks for a re-count when the response leaves stock negative", async () => {
    const detail = await picked("2");
    respond("post", "/work-orders/:id/items", { id: "wi1", item_quantity: "-3" });
    seedDetail({ ...detail, items: [workOrderItem({ item_quantity: "-3" })] });
    click("add-item");
    await vi.waitFor(() =>
      expect(message().textContent).toBe("Item added. Please re-count stock."));
    expect(message().className).toBe("error");
  });

  it("sends and then clears a stamped material request id", async () => {
    const detail = await picked("1");
    card().querySelector(".wo-add-item").dataset.materialRequestId = "mr1";
    respond("post", "/work-orders/:id/items", { id: "wi1", item_quantity: "5" });
    click("add-item");
    await vi.waitFor(() => expect(requestFor("/items", "POST")).not.toBeNull());
    expect(requestFor("/items", "POST").body.material_request_id).toBe("mr1");
    await vi.waitFor(() =>
      expect(card().querySelector(".wo-add-item").dataset.materialRequestId).toBeUndefined());
  });
});

describe("edit-item and remove-item", () => {
  const withLine = () => open({ items: [workOrderItem({ id: "wi1", quantity: "2" })] });

  it("patches the line by its own id", async () => {
    const detail = await withLine();
    respond("patch", "/work-orders/:id/items/:woItemId", { ok: true });
    card().querySelector(".wo-line-qty").value = "5";
    click("edit-item");
    await vi.waitFor(() => expect(requestFor("/items/wi1", "PATCH")).not.toBeNull());
    expect(requestFor("/items/wi1", "PATCH").body).toEqual({ quantity: 5 });
    await refreshed(detail.id);
    await vi.waitFor(() =>
      expect(card().querySelector(".wo-materials-section").open).toBe(true));
  });

  it("refuses a zero quantity", async () => {
    await withLine();
    card().querySelector(".wo-line-qty").value = "0";
    click("edit-item");
    await vi.waitFor(() =>
      expect(message().textContent).toBe("Enter a quantity greater than zero."));
    expect(requestFor("/items/wi1", "PATCH")).toBeNull();
  });

  it("asks before removing, and No removes nothing", async () => {
    await withLine();
    click("remove-item");
    await answerConfirm(false);
    expect(requestFor("/items/wi1", "DELETE")).toBeNull();
  });

  it("deletes on Yes", async () => {
    const detail = await withLine();
    respond("delete", "/work-orders/:id/items/:woItemId", null, { status: 204 });
    click("remove-item");
    await answerConfirm(true);
    await vi.waitFor(() => expect(requestFor("/items/wi1", "DELETE")).not.toBeNull());
    await refreshed(detail.id);
  });
});

describe("the technician picker", () => {
  const ada = user({ role: "technician", full_name: "Ada Lovelace" });
  const grace = user({ role: "technician", full_name: "Grace Hopper" });

  it("searches by normalized name and excludes anyone already selected", async () => {
    await open({
      users: [ada, grace], assigned_to_ids: [String(grace.id)], assigned_to_names: ["Grace Hopper"],
    });
    type(card().querySelector(".wo-tech-search"), "lovelace");
    const results = card().querySelector(".wo-tech-results");
    expect(results.hidden).toBe(false);
    const options = [...results.querySelectorAll('[data-action="pick-technician"]')];
    expect(options.map((b) => b.textContent)).toEqual(["Ada Lovelace"]);
    expect(card().querySelector(".wo-tech-search").getAttribute("aria-expanded")).toBe("true");
  });

  it("says so when nothing matches", async () => {
    await open({ users: [ada] });
    type(card().querySelector(".wo-tech-search"), "zzz");
    expect(card().querySelector(".wo-tech-results").textContent)
      .toContain("No matching technicians.");
  });

  it("says so when there are no technicians at all", async () => {
    await open({ users: [] });
    type(card().querySelector(".wo-tech-search"), "a");
    expect(card().querySelector(".wo-tech-results").textContent)
      .toContain("No active people are available to assign.");
  });

  it("pick-technician adds a selection row and clears the search", async () => {
    await open({ users: [ada] });
    type(card().querySelector(".wo-tech-search"), "ada");
    click("pick-technician");
    const rows = [...card().querySelectorAll(".wo-tech-selected-row")];
    expect(rows.map((r) => r.dataset.technicianId)).toEqual([String(ada.id)]);
    expect(card().querySelector(".wo-tech-empty")).toBeNull();
    expect(card().querySelector(".wo-tech-search").value).toBe("");
    expect(card().querySelector(".wo-tech-results").hidden).toBe(true);
  });

  it("remove-technician takes the row away and restores the empty hint", async () => {
    await open({ assigned_to_ids: ["t1"], assigned_to_names: ["Ada L"], users: [ada] });
    click("remove-technician");
    expect(card().querySelectorAll(".wo-tech-selected-row")).toHaveLength(0);
    expect(card().querySelector(".wo-tech-empty").textContent).toBe("No technicians assigned.");
  });

  // Safari never focuses a clicked button, so the input's focusout would close
  // the list mid-click; cancelling mousedown is what keeps it open.
  it("cancels mousedown on a result so Safari's focusout cannot close the list", async () => {
    await open({ users: [ada] });
    type(card().querySelector(".wo-tech-search"), "ada");
    const result = card().querySelector(".wo-tech-result");
    const down = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
    result.dispatchEvent(down);
    expect(down.defaultPrevented).toBe(true);
  });

  it("Escape closes the results without clearing the selection", async () => {
    await open({ users: [ada] });
    const input = card().querySelector(".wo-tech-search");
    type(input, "ada");
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(card().querySelector(".wo-tech-results").hidden).toBe(true);
    expect(input.getAttribute("aria-expanded")).toBe("false");
  });
});

describe("the combo", () => {
  // The shared menus module (static/menus.js) owns toggle/pick through
  // document-level listeners, so these click its own data-menu-action hooks.
  const toggle = (index = 0) =>
    card().querySelectorAll('[data-menu-action="toggle"]')[index].click();

  it("opening one combo closes every other", async () => {
    await open({ users: [user({ role: "supervisor" })] });
    const combos = [...card().querySelectorAll(".menu-combo")];
    expect(combos).toHaveLength(2); // supervisor + status
    toggle(0);
    expect(combos[0].querySelector(".menu-list").hidden).toBe(false);
    expect(combos[0].querySelector(".menu-trigger").getAttribute("aria-expanded")).toBe("true");
    toggle(1);
    expect(combos[0].querySelector(".menu-list").hidden).toBe(true);
    expect(combos[1].querySelector(".menu-list").hidden).toBe(false);
  });

  it("a second toggle closes its own list", async () => {
    await open({});
    toggle();
    toggle();
    expect(card().querySelector(".menu-list").hidden).toBe(true);
  });

  it("a pick writes through to the hidden native select", async () => {
    await open({ status: "in_progress", assigned_to_ids: ["t1"], assigned_to_names: ["Ada L"] });
    const combo = card().querySelector(".wo-status-combo");
    combo.querySelector('[data-menu-action="toggle"]').click();
    const onHold = [...combo.querySelectorAll('[data-menu-action="pick"]')]
      .find((b) => b.dataset.value === "on_hold");
    onHold.click();
    expect(card().querySelector(".wo-edit-status").value).toBe("on_hold");
    expect(combo.querySelector(".menu-trigger-label").textContent).toBe("On-Hold");
    expect(onHold.getAttribute("aria-selected")).toBe("true");
    expect(combo.querySelector(".menu-list").hidden).toBe(true);
    expect(document.activeElement).toBe(combo.querySelector(".menu-trigger"));
  });

  it("Escape closes an open combo", async () => {
    await open({});
    toggle();
    const combo = card().querySelector(".menu-combo");
    combo.querySelector(".menu-trigger")
      .dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(combo.querySelector(".menu-list").hidden).toBe(true);
  });

  it("a saved status combo choice is what save-details sends", async () => {
    const detail = await open({ status: "in_progress", assigned_to_ids: ["t1"], assigned_to_names: ["Ada L"] });
    respond("patch", "/work-orders/:id", detail);
    const combo = card().querySelector(".wo-status-combo");
    combo.querySelector('[data-menu-action="toggle"]').click();
    [...combo.querySelectorAll('[data-menu-action="pick"]')]
      .find((b) => b.dataset.value === "on_hold").click();
    click("save-details");
    await vi.waitFor(() =>
      expect(requestFor(`/work-orders/${detail.id}`, "PATCH")).not.toBeNull());
    expect(requestFor(`/work-orders/${detail.id}`, "PATCH").body.status).toBe("on_hold");
  });
});
