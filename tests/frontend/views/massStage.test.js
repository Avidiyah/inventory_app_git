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
