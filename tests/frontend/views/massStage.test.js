// Characterization coverage for views/massStage.js: loadStages and the
// community -> building -> unit tree, lazy detail, create stage, and the
// thirteen delegated actions across the planning, loading and completed
// bodies. massStageActionCoverage.test.js audits that every action is
// named here.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server, pageHandlers } from "../helpers/handlers.js";
import { requestFor, requests, clearRequests } from "../helpers/requests.js";
import { answerConfirm, confirmOverlay, confirmTitle } from "../helpers/dialogs.js";
import {
  card, cardEls, el, groupEls, mountMassStage, openCard, openStages, respond, restoreMassStage, slotEls, stageMessage, state,
} from "../helpers/massStage.js";
import {
  item as itemFactory, massStageDetail, massStageSummary, mergedItem, stageItem, stageWorkOrder, user as userFactory,
} from "../helpers/factories.js";

afterEach(() => restoreMassStage());
const user = () => userEvent.setup();

describe("mountMassStage", () => {
  it("mounts with an empty list and nothing fetched", async () => {
    const { mod } = await mountMassStage();
    expect(typeof mod.loadStages).toBe("function");
    expect(el.list().children).toHaveLength(0);
    expect(requests()).toHaveLength(0);
  });
});

const uuidLike = () => `00000000-0000-4000-8000-${String(Math.floor(Math.random() * 1e12)).padStart(12, "0")}`;

describe("loadStages", () => {
  it("refreshReferenceData: items and users fetched, technicians filtered by canBeWorkOrderTechnician", async () => {
    const users = [userFactory({ role: "technician", full_name: "Tech One" }), userFactory({ role: "supervisor", full_name: "Sup" }),
      userFactory({ role: "admin", full_name: "Adm" }), userFactory({ role: "techfm_oa", full_name: "OA" })];
    const detail = massStageDetail();
    const { mod } = await mountMassStage({ stages: [massStageSummary({ id: detail.id })], details: [detail], users });
    await mod.loadStages({ refreshReferenceData: true });
    expect(requests().map((r) => r.url)).toEqual(["/items/", "/users/", "/mass-stages/"]);
    await openCard(detail.id);
    const options = Array.from(card(detail.id).querySelector(".ms-add-assignee").options).map((o) => o.textContent);
    expect(options).toEqual(["Unassigned", "Tech One", "Sup"]);
  });

  it("without refreshReferenceData the caches are reused; user-names-updated invalidates techs", async () => {
    const { mod } = await openStages({ stages: [] });
    await mod.loadStages();
    expect(requests().map((r) => r.url)).toEqual(["/mass-stages/"]);
    clearRequests();
    document.dispatchEvent(new Event("user-names-updated"));
    await mod.loadStages();
    expect(requests().map((r) => r.url)).toEqual(["/users/", "/mass-stages/"]);
  });

  it("a failed reference load is swallowed", async () => {
    await openStages({ handlers: [http.get("/items/", () => HttpResponse.json({ detail: "x" }, { status: 500 }))] });
    expect(el.listMessage().textContent).toBe("");
    expect(el.list().querySelector("p.hint")).not.toBeNull();
  });

  it("a failed list load renders the error", async () => {
    const { mod } = await mountMassStage({ handlers: [http.get("/mass-stages/", () => HttpResponse.json({ detail: "x" }, { status: 500 }))] });
    await mod.loadStages();
    expect(el.listMessage().className).toBe("error");
    expect(el.list().children).toHaveLength(0);
  });

  it("empty list: the hint", async () => {
    await openStages({ stages: [] });
    expect(el.list().querySelector("p.hint").textContent).toBe("No mass stages yet. Create one above.");
  });

  it("community groups sorted, buildings inside, status badge and meta", async () => {
    await openStages({ stages: [
      massStageSummary({ community: "Scholars", building_name: "19", status: "planning", unit_count: 0, item_count: 0 }),
      massStageSummary({ community: "Centennial", building_name: "3", status: "loading", unit_count: 1, item_count: 2 }),
      massStageSummary({ community: "Centennial", building_name: "4", status: "completed", unit_count: 2, item_count: 5 }),
      massStageSummary({ community: null, building_name: "x" }),
    ] });
    expect(groupEls().map((g) => g.dataset.community)).toEqual(["Centennial", "Scholars", "Unfiled"]);
    expect(groupEls()[0].querySelector(".community-meta").textContent).toBe("2 buildings");
    expect(groupEls()[1].querySelector(".community-meta").textContent).toBe("1 building");
    const cards = cardEls();
    expect(cards[0].querySelector(".stage-status").className).toBe("stage-status stage-status-loading");
    // Units pluralise, items never do ("1 unit · 2 items" is fine, "· 1 items" is not) -- see open-work.md.
    expect(cards[0].querySelector(".stage-meta").textContent).toBe("1 unit · 2 items");
    expect(cards[1].querySelector(".stage-meta").textContent).toBe("2 units · 5 items");
    expect(cards[2].querySelector(".stage-meta").textContent).toBe("no units");
    expect(cards[0].querySelector(".stage-body .skel-card")).not.toBeNull(); // lazy body
  });

  it("opening a card fetches its detail once and recomputes the meta from distinct items", async () => {
    const shared = uuidLike();
    const detail = massStageDetail({ work_orders: [
      stageWorkOrder({ items: [stageItem({ item_id: shared }), stageItem()] }),
      stageWorkOrder({ items: [stageItem({ item_id: shared })] }),
    ] });
    await openStages({ stages: [massStageSummary({ id: detail.id })], details: [detail] });
    const c = await openCard(detail.id);
    expect(requestFor(`/mass-stages/${detail.id}`, "GET")).not.toBeNull();
    expect(c.querySelector(".stage-meta").textContent).toBe("2 units · 2 items");
    c.open = false; c.open = true;
    await new Promise((r) => setTimeout(r, 10));
    expect(requests().filter((r) => r.url === `/mass-stages/${detail.id}`)).toHaveLength(1);
  });

  it("a failing detail renders the error inside the card", async () => {
    const s = massStageSummary();
    await openStages({ stages: [s] });                  // no detail seeded -> 404
    const c = card(s.id); c.closest("details.community-group").open = true; c.open = true;
    await vi.waitFor(() => expect(c.querySelector(".stage-body p.error")).not.toBeNull());
  });
});

describe("create stage", () => {
  it("community select: seeds + used names sorted, New community reveals the input", async () => {
    await openStages({ stages: [massStageSummary({ community: "Aspen" })] });
    expect(Array.from(el.communitySelect().options).map((o) => o.value)).toEqual(["Aspen", "Centennial", "Cimarron", "Scholars", "__new__"]);
    expect(el.communityNew().hidden).toBe(true);
    await user().selectOptions(el.communitySelect(), "__new__");
    expect(el.communityNew().hidden).toBe(false);
  });

  it("validation: community first, then building; no request", async () => {
    await openStages();
    await user().selectOptions(el.communitySelect(), "__new__");
    await user().click(el.createBtn());
    expect(el.createMessage().textContent).toBe("Choose or enter a community.");
    await user().selectOptions(el.communitySelect(), "Scholars");
    await user().click(el.createBtn());
    expect(el.createMessage().textContent).toBe("Enter a building number.");
    expect(requestFor("/mass-stages/", "POST")).toBeNull();
  });

  it("posts, clears the form, reloads, and auto-opens the new community and card", async () => {
    const created = massStageDetail({ community: "Scholars", building_name: "19" });
    const { mod } = await openStages({ stages: [], details: [created] });
    respond("POST", "/mass-stages/", created, { status: 201 });
    server.use(http.get("/mass-stages/", () => HttpResponse.json([massStageSummary({ id: created.id, community: "Scholars", building_name: "19" })])));
    // The select defaults to the alphabetically-first seed (Centennial), so
    // the community is chosen explicitly.
    expect(el.communitySelect().value).toBe("Centennial");
    await user().selectOptions(el.communitySelect(), "Scholars");
    await user().type(el.buildingInput(), "19{Enter}");
    await vi.waitFor(() => expect(el.createMessage().textContent).toBe("Mass stage created."));
    expect(requestFor("/mass-stages/", "POST").body).toEqual({ community: "Scholars", building_name: "19" });
    expect(el.buildingInput().value).toBe("");
    expect(groupEls()[0].open).toBe(true);
    expect(card(created.id).open).toBe(true);
    await vi.waitFor(() => expect(card(created.id).dataset.loaded).toBe("1"));
    expect(mod).toBeTruthy();
  });

  it("a failing create shows friendlyError with the fallback", async () => {
    await openStages();
    respond("POST", "/mass-stages/", { detail: "" }, { status: 500 });
    await user().type(el.buildingInput(), "19");
    await user().click(el.createBtn());
    await vi.waitFor(() => expect(el.createMessage().className).toBe("error"));
  });
});

async function planningCard({ slots = [stageWorkOrder()], items = [], role = "supervisor", users = [] } = {}) {
  const detail = massStageDetail({ status: "planning", work_orders: slots });
  const ctx = await openStages({ role, stages: [massStageSummary({ id: detail.id })], details: [detail], items, users });
  const c = await openCard(detail.id);
  clearRequests();
  return { ...ctx, detail, c, slot: slots[0] };
}
const S = (detail) => `/mass-stages/${detail.id}`;

describe("planning body", () => {
  it("renders slots, the add-work-order row with tech options, Save and Delete; tipHtml absent here", async () => {
    const { c, slot } = await planningCard({ slots: [stageWorkOrder({ unit_number: "12", work_order_number: "7001", assigned_to_name: "Pat", items: [stageItem()] })] });
    expect(slotEls(c)).toHaveLength(1);
    expect(c.querySelector(".room-title").textContent).toBe("Unit 12");
    // "1 items": the slot meta never pluralises -- see open-work.md.
    expect(c.querySelector(".room-meta").textContent).toBe("WO 7001 · 1 items · Pat");
    expect(c.querySelector('[data-action="add-work-order"]')).not.toBeNull();
    expect(c.querySelector('[data-action="save-stage"]')).not.toBeNull();
    expect(c.querySelector('[data-action="delete-stage"]').dataset.stageLoaded).toBeUndefined();
    expect(c.querySelector(".ms-item .ms-onhand").textContent).toBe("On hand: 10");
    expect(c.querySelector(".ms-item .ms-short")).toBeNull();
    expect(c.querySelector(".ms-subhead .tip-btn")).toBeNull();
    expect(c.querySelector(".ms-stage-message")).not.toBeNull();
    expect(slot).toBeTruthy();
  });

  it("a slot with no unit number renders a dash; a short item flags short-by", async () => {
    const { c } = await planningCard({ slots: [stageWorkOrder({ unit_number: null, items: [stageItem({ planned_quantity: "15", item_quantity: "10" })] })] });
    expect(c.querySelector(".room-title").textContent).toBe("Unit —");
    expect(c.querySelector(".ms-short").textContent).toBe("short by 5");
  });

  it("any stage action strips the message element's class, so the module's next lookup on that card is null", async () => {
    // setMessage(msg, "", "") runs before the branch and replaces className,
    // so `.ms-stage-message` matches nothing afterwards. The click handler
    // re-queries it on every action, so a SECOND action on the same card --
    // with no re-render in between (a validation failure, a declined
    // confirm, a failed request) -- throws a TypeError before doing anything.
    // Characterization -- see open-work.md N-P5-CHARACTERIZED. Every test
    // below therefore drives one action per card.
    const { c } = await planningCard();
    await user().click(c.querySelector('[data-action="add-work-order"]'));
    expect(stageMessage(c).textContent).toBe("Enter a work order number.");
    expect(c.querySelector(".ms-stage-message")).toBeNull();
  });

  it("pick-item: search filters the item cache, picking fills the row and focuses qty, no request", async () => {
    const bulb = itemFactory({ name: "Bulb A19", barcode: "111" });
    const { c } = await planningCard({ items: [bulb, itemFactory({ name: "Fuse", barcode: "222" })] });
    c.querySelector("details.room-card").open = true;
    await user().type(c.querySelector(".ms-item-search"), "bulb");
    const results = c.querySelector(".ms-item-results");
    expect(results.hidden).toBe(false);
    expect(results.querySelectorAll('[data-action="pick-item"]')).toHaveLength(1);
    await user().click(results.querySelector('[data-action="pick-item"]'));
    expect(c.querySelector(".ms-add-item").dataset.itemId).toBe(bulb.id);
    expect(c.querySelector(".ms-item-search").value).toBe("Bulb A19");
    expect(results.hidden).toBe(true);
    expect(document.activeElement).toBe(c.querySelector(".ms-item-qty"));
    expect(requests()).toHaveLength(0);
    await user().clear(c.querySelector(".ms-item-search"));
    await user().type(c.querySelector(".ms-item-search"), "zzz");
    expect(results.querySelector("p.hint").textContent).toBe("No matching items.");
    // Typing again drops the pick silently -- see open-work.md.
    expect(c.querySelector(".ms-add-item").dataset.itemId).toBeUndefined();
  });

  it("add-item without a pick: the pick-first message, no request", async () => {
    const { c } = await planningCard({ items: [itemFactory({ name: "Bulb" })] });
    c.querySelector("details.room-card").open = true;
    await user().click(c.querySelector('[data-action="add-item"]'));
    expect(stageMessage(c).textContent).toBe("Search and pick an item first.");
    expect(requests()).toHaveLength(0);
  });

  it("add-item with a pick but no quantity: the positive-quantity message", async () => {
    const { c } = await planningCard({ items: [itemFactory({ name: "Bulb" })] });
    c.querySelector("details.room-card").open = true;
    await user().type(c.querySelector(".ms-item-search"), "bulb");
    await user().click(c.querySelector('[data-action="pick-item"]'));
    await user().click(c.querySelector('[data-action="add-item"]'));
    expect(stageMessage(c).textContent).toBe("Enter a quantity greater than zero.");
    expect(requests()).toHaveLength(0);
  });

  it("add-item: posts item_id + planned_quantity and refreshes with the slot kept open", async () => {
    const bulb = itemFactory({ name: "Bulb" });
    const { c, detail, slot } = await planningCard({ items: [bulb] });
    c.querySelector("details.room-card").open = true;
    await user().type(c.querySelector(".ms-item-search"), "bulb");
    await user().click(c.querySelector('[data-action="pick-item"]'));
    await user().type(c.querySelector(".ms-item-qty"), "3");
    respond("POST", `${S(detail)}/work-orders/${slot.id}/items`, stageItem(), { status: 201 });
    state.details.set(detail.id, massStageDetail({ ...detail, work_orders: [stageWorkOrder({ ...slot, items: [stageItem({ item_name: "Bulb" })] })] }));
    await user().click(c.querySelector('[data-action="add-item"]'));
    await vi.waitFor(() => expect(c.querySelector(".ms-item")).not.toBeNull());
    expect(requestFor("/items", "POST").body).toEqual({ item_id: bulb.id, planned_quantity: 3 });
    expect(c.querySelector("details.room-card").open).toBe(true);   // refreshStage preserved it
    expect(c.querySelector(".ms-stage-message")).not.toBeNull();     // the re-render restored the class
  });

  it("edit-item rejects 0", async () => {
    const { c } = await planningCard({ slots: [stageWorkOrder({ items: [stageItem()] })] });
    c.querySelector("details.room-card").open = true;
    const qty = c.querySelector(".ms-item-planned");
    await user().clear(qty); await user().type(qty, "0");
    await user().click(c.querySelector('[data-action="edit-item"]'));
    expect(stageMessage(c).textContent).toBe("Enter a quantity greater than zero.");
    expect(requests()).toHaveLength(0);
  });

  it("edit-item PATCHes planned_quantity and refreshes", async () => {
    const it0 = stageItem();
    const { c, detail, slot } = await planningCard({ slots: [stageWorkOrder({ items: [it0] })] });
    c.querySelector("details.room-card").open = true;
    const qty = c.querySelector(".ms-item-planned");
    await user().clear(qty); await user().type(qty, "7");
    respond("PATCH", `${S(detail)}/work-orders/${slot.id}/items/${it0.id}`, it0);
    await user().click(c.querySelector('[data-action="edit-item"]'));
    await vi.waitFor(() => expect(requestFor(`/items/${it0.id}`, "PATCH")).not.toBeNull());
    expect(requestFor(`/items/${it0.id}`, "PATCH").body).toEqual({ planned_quantity: 7 });
    await vi.waitFor(() => expect(requests().filter((r) => r.url === S(detail)).length).toBe(1));
  });

  it("remove-item: DELETE without confirm, then refresh", async () => {
    const it0 = stageItem();
    const { c, detail, slot } = await planningCard({ slots: [stageWorkOrder({ items: [it0] })] });
    c.querySelector("details.room-card").open = true;
    respond("DELETE", `${S(detail)}/work-orders/${slot.id}/items/${it0.id}`, null, { status: 204 });
    await user().click(c.querySelector('[data-action="remove-item"]'));
    await vi.waitFor(() => expect(requestFor(`/items/${it0.id}`, "DELETE")).not.toBeNull());
    expect(confirmOverlay().hidden).toBe(true);
    await vi.waitFor(() => expect(requests().filter((r) => r.url === S(detail)).length).toBe(1));
  });

  it("add-work-order needs a number", async () => {
    const { c } = await planningCard();
    await user().click(c.querySelector('[data-action="add-work-order"]'));
    expect(stageMessage(c).textContent).toBe("Enter a work order number.");
    expect(requests()).toHaveLength(0);
  });

  it("add-work-order posts number, unit, assignee; a 404 surfaces in the stage message", async () => {
    const tech = userFactory({ role: "technician", full_name: "Tech" });
    const { c, detail } = await planningCard({ users: [tech] });
    await user().type(c.querySelector(".ms-unit-number"), "12");
    await user().type(c.querySelector(".ms-room-wo"), "7002");
    await user().selectOptions(c.querySelector(".ms-add-assignee"), String(tech.id));
    respond("POST", `${S(detail)}/work-orders`, { detail: "Work order not found" }, { status: 404 });
    await user().click(c.querySelector('[data-action="add-work-order"]'));
    await vi.waitFor(() => expect(stageMessage(c).className).toBe("error"));
    expect(requestFor("/work-orders", "POST").body).toEqual({ work_order_number: "7002", unit_number: "12", assigned_to_id: String(tech.id) });
    expect(requestFor(S(detail), "GET")).toBeNull();   // no refresh on failure
  });

  it("add-work-order success refreshes the stage", async () => {
    const { c, detail } = await planningCard();
    await user().type(c.querySelector(".ms-room-wo"), "7002");
    respond("POST", `${S(detail)}/work-orders`, stageWorkOrder(), { status: 201 });
    await user().click(c.querySelector('[data-action="add-work-order"]'));
    await vi.waitFor(() => expect(requests().filter((r) => r.url === S(detail)).length).toBe(1));
    expect(requestFor("/work-orders", "POST").body).toEqual({ work_order_number: "7002", unit_number: null, assigned_to_id: null });
  });

  it("remove-slot: confirm copy; No sends nothing", async () => {
    const { c } = await planningCard();
    c.querySelector("details.room-card").open = true;
    const clicking = user().click(c.querySelector('[data-action="remove-slot"]'));
    await vi.waitFor(() => expect(confirmTitle()).toBe("Remove this unit from the plan? (The work order itself is kept.)"));
    await answerConfirm(false); await clicking;
    expect(requests()).toHaveLength(0);
  });

  it("remove-slot: Yes DELETEs and refreshes", async () => {
    const { c, detail, slot } = await planningCard();
    c.querySelector("details.room-card").open = true;
    respond("DELETE", `${S(detail)}/work-orders/${slot.id}`, null, { status: 204 });
    const clicking = user().click(c.querySelector('[data-action="remove-slot"]'));
    await answerConfirm(true); await clicking;
    await vi.waitFor(() => expect(requestFor(`/work-orders/${slot.id}`, "DELETE")).not.toBeNull());
    await vi.waitFor(() => expect(requests().filter((r) => r.url === S(detail)).length).toBe(1));
  });

  it("open-wo hands off to Work Orders with the card focused", async () => {
    const { c, slot } = await planningCard();
    server.use(...pageHandlers());
    c.querySelector("details.room-card").open = true;
    await user().click(c.querySelector('[data-action="open-wo"]'));
    expect(document.getElementById("work-orders-page").classList.contains("active")).toBe(true);
    await vi.waitFor(() => expect(requestFor("/work-orders/", "GET")).not.toBeNull());
    expect(slot.work_order_id).toBeTruthy();
  });

  it("save-stage: confirm copy; Yes PATCHes status loading and reloads the list", async () => {
    const { c, detail } = await planningCard();
    respond("PATCH", S(detail), massStageDetail({ ...detail, status: "loading" }));
    const clicking = user().click(c.querySelector('[data-action="save-stage"]'));
    await vi.waitFor(() => expect(confirmTitle()).toBe("Save this mass stage? It moves to loading and the plan is locked."));
    await answerConfirm(true); await clicking;
    await vi.waitFor(() => expect(requestFor(S(detail), "PATCH").body).toEqual({ status: "loading" }));
    await vi.waitFor(() => expect(requestFor("/mass-stages/", "GET")).not.toBeNull());
  });

  it("a failing action surfaces friendlyError in the stage message", async () => {
    const { c, detail } = await planningCard();
    respond("PATCH", S(detail), { detail: "" }, { status: 500 });
    const clicking = user().click(c.querySelector('[data-action="save-stage"]'));
    await answerConfirm(true); await clicking;
    await vi.waitFor(() => expect(stageMessage(c).className).toBe("error"));
    expect(stageMessage(c).textContent).not.toBe("");
  });
});

async function loadingCard({ status = "loading", merged = [mergedItem()], slots = [stageWorkOrder()] } = {}) {
  const detail = massStageDetail({ status, merged_items: merged, work_orders: slots });
  const ctx = await openStages({ stages: [massStageSummary({ id: detail.id, status })], details: [detail] });
  const c = await openCard(detail.id);
  clearRequests();
  return { ...ctx, detail, c };
}

describe("loading body", () => {
  it("renders the load list with stats, short/overflow flags, tipHtml on the heading, read-only slots", async () => {
    const { c } = await loadingCard({ merged: [
      mergedItem({ item_name: "Bulb", planned_total: "4", loaded_total: "1", remaining_to_load: "3", on_hand: "2", overflow: "0" }),
      mergedItem({ item_name: "Fuse", overflow: "2", remaining_to_load: "0" }),
    ], slots: [stageWorkOrder({ items: [stageItem()] })] });
    const rows = c.querySelectorAll(".ms-merged-item");
    expect(rows[0].querySelector(".ms-merged-stats").textContent).toBe("Planned 4 · Loaded 1 · Remaining 3 · On hand 2");
    expect(rows[0].querySelector(".ms-short").textContent).toBe("short by 1");
    expect(rows[0].querySelector(".ms-load-qty").value).toBe("3");
    expect(rows[1].querySelector(".ms-overflow").textContent).toBe("+2 over");
    expect(c.querySelector(".ms-subhead .tip-btn")).not.toBeNull();   // tipHtml("stage.load-list")
    expect(c.querySelector('[data-action="complete-stage"]')).not.toBeNull();
    expect(c.querySelector('[data-action="reuse-stage"]')).toBeNull();
    expect(c.querySelector('[data-action="delete-stage"]').dataset.stageLoaded).toBe("1");
    expect(c.querySelector('[data-action="add-item"]')).toBeNull();
    expect(c.querySelector(".ms-item-planned-ro").textContent).toBe("Planned: 2");
    expect(c.querySelector('[data-action="remove-slot"]')).toBeNull();
  });

  it("load-item rejects 0", async () => {
    const { c } = await loadingCard();
    const qty = c.querySelector(".ms-load-qty");
    await user().clear(qty); await user().type(qty, "0");
    await user().click(c.querySelector('[data-action="load-item"]'));
    expect(stageMessage(c).textContent).toBe("Enter a quantity greater than zero.");
    expect(confirmOverlay().hidden).toBe(true);
    expect(requests()).toHaveLength(0);
  });

  it("load-item: confirm names qty × item; Yes posts item_id + quantity and refreshes", async () => {
    const m = mergedItem({ item_name: "Bulb", remaining_to_load: "3" });
    const { c, detail } = await loadingCard({ merged: [m] });
    const qty = c.querySelector(".ms-load-qty");
    await user().clear(qty); await user().type(qty, "2");
    respond("POST", `${S(detail)}/load`, {});
    const clicking = user().click(c.querySelector('[data-action="load-item"]'));
    await vi.waitFor(() => expect(confirmTitle()).toBe("Load 2 × Bulb onto the truck?"));
    await answerConfirm(true); await clicking;
    await vi.waitFor(() => expect(requestFor("/load", "POST").body).toEqual({ item_id: m.item_id, quantity: 2 }));
    await vi.waitFor(() => expect(requestFor(S(detail), "GET")).not.toBeNull());
  });

  it("load-item: No sends nothing", async () => {
    const { c } = await loadingCard();
    const clicking = user().click(c.querySelector('[data-action="load-item"]'));
    await answerConfirm(false); await clicking;
    expect(requests()).toHaveLength(0);
  });

  it("return-item rejects blank", async () => {
    const { c } = await loadingCard();
    await user().click(c.querySelector('[data-action="return-item"]'));
    expect(stageMessage(c).textContent).toBe("Enter a quantity to return.");
    expect(requests()).toHaveLength(0);
  });

  it("return-item: no confirm; posts item_id + quantity and refreshes", async () => {
    const m = mergedItem();
    const { c, detail } = await loadingCard({ merged: [m] });
    await user().type(c.querySelector(".ms-return-qty"), "1");
    respond("POST", `${S(detail)}/return`, {});
    await user().click(c.querySelector('[data-action="return-item"]'));
    await vi.waitFor(() => expect(requestFor("/return", "POST").body).toEqual({ item_id: m.item_id, quantity: 1 }));
    expect(confirmOverlay().hidden).toBe(true);
    await vi.waitFor(() => expect(requestFor(S(detail), "GET")).not.toBeNull());
  });

  it("complete-stage: confirm copy; No does nothing", async () => {
    const { c } = await loadingCard();
    const no = user().click(c.querySelector('[data-action="complete-stage"]'));
    await vi.waitFor(() => expect(confirmTitle()).toBe("Mark this building complete? The stage becomes read-only."));
    await answerConfirm(false); await no;
    expect(requests()).toHaveLength(0);
  });

  it("complete-stage: Yes PATCHes completed and reloads", async () => {
    const { c, detail } = await loadingCard();
    respond("PATCH", S(detail), massStageDetail({ ...detail, status: "completed" }));
    const yes = user().click(c.querySelector('[data-action="complete-stage"]'));
    await answerConfirm(true); await yes;
    await vi.waitFor(() => expect(requestFor(S(detail), "PATCH").body).toEqual({ status: "completed" }));
    await vi.waitFor(() => expect(requestFor("/mass-stages/", "GET")).not.toBeNull());
  });

  it("delete-stage on a loaded stage uses the dispensed-stock copy; Yes DELETEs and reloads", async () => {
    const { c, detail } = await loadingCard();
    respond("DELETE", S(detail), null, { status: 204 });
    const clicking = user().click(c.querySelector('[data-action="delete-stage"]'));
    await vi.waitFor(() => expect(confirmTitle()).toBe(
      "Delete this mass stage? Items already loaded stay dispensed — this does not return them to stock. This cannot be undone."));
    await answerConfirm(true); await clicking;
    await vi.waitFor(() => expect(requestFor(S(detail), "DELETE")).not.toBeNull());
    await vi.waitFor(() => expect(requestFor("/mass-stages/", "GET")).not.toBeNull());
  });

  it("delete-stage on a planning stage uses the short copy; No sends nothing", async () => {
    const { c } = await planningCard();
    const clicking = user().click(c.querySelector('[data-action="delete-stage"]'));
    await vi.waitFor(() => expect(confirmTitle()).toBe("Delete this mass stage? This cannot be undone."));
    await answerConfirm(false); await clicking;
    expect(requests()).toHaveLength(0);
  });
});

describe("completed body", () => {
  it("read-only stats, Stage again, no Mark Completed, no load controls", async () => {
    const { c } = await loadingCard({ status: "completed", merged: [mergedItem({ returned_total: "1", net_consumed: "3" })] });
    expect(c.querySelector(".ms-merged-stats-ro").textContent).toBe("Returned 1 · Consumed 3");
    expect(c.querySelector('[data-action="load-item"]')).toBeNull();
    expect(c.querySelector('[data-action="complete-stage"]')).toBeNull();
    expect(c.querySelector('[data-action="reuse-stage"]')).not.toBeNull();
  });

  it("reuse-stage: confirm; Yes POSTs /reuse, reloads, and auto-opens the fresh stage", async () => {
    const { c, detail } = await loadingCard({ status: "completed" });
    const fresh = massStageDetail({ community: detail.community, building_name: detail.building_name });
    respond("POST", `${S(detail)}/reuse`, fresh, { status: 201 });
    state.details.set(fresh.id, fresh);
    server.use(http.get("/mass-stages/", () => HttpResponse.json([
      massStageSummary({ id: detail.id, status: "completed" }), massStageSummary({ id: fresh.id, status: "planning" }),
    ])));
    const clicking = user().click(c.querySelector('[data-action="reuse-stage"]'));
    await vi.waitFor(() => expect(confirmTitle()).toBe("Start a new staging for this community + building? Item lists start empty."));
    await answerConfirm(true); await clicking;
    await vi.waitFor(() => expect(card(fresh.id)).not.toBeNull());
    expect(card(fresh.id).open).toBe(true);
    // The community group is NOT auto-opened on reuse (only autoOpenId is set,
    // not autoOpenCommunity) -- so the open card sits inside a closed group.
    // Characterization -- see open-work.md N-P5-CHARACTERIZED.
    expect(card(fresh.id).closest("details.community-group").open).toBe(false);
  });
});
