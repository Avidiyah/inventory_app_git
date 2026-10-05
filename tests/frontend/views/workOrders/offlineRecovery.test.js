// Characterization for the offline-save recovery path: workOrderDrafts.js +
// workOrderRetry.js. A failed save while offline drafts locally instead of
// just erroring inline, and a later `replayPendingDrafts()` (fired on a
// socket reconnect or app boot in production -- see auth.js) resends it.
//
// The session-expiry half (captureHeldEditorForResume + the reopen-and-refill
// on re-login) is characterized at the auth.js level in auth.test.js, where a
// real 401/re-login round trip is available; this file only needs the
// work-orders shell.

import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../../helpers/handlers.js";
import {
  card, clearRequests, message, mountWorkOrders, openCard, requestFor, respond,
} from "../../helpers/workOrders.js";
import { workOrderCard, workOrderDetail, workOrderItem } from "../../helpers/factories.js";

async function open({ role = "supervisor", ...overrides } = {}) {
  const detail = workOrderDetail(overrides);
  const { mod } = await mountWorkOrders({
    role,
    cards: [workOrderCard({ id: detail.id, number: detail.number, status: detail.status })],
    details: [detail],
  });
  await openCard(0);
  return { mod, detail };
}

const click = (action) => card().querySelector(`[data-action="${action}"]`).click();

describe("add-labor offline recovery", () => {
  it("drafts a failed save locally instead of just erroring inline", async () => {
    const { detail } = await open({ assigned_to_ids: ["t1"], assigned_to_names: ["Ada L"] });
    server.use(http.post("/work-orders/:id/labor", () => HttpResponse.error()));
    card().querySelector(".wo-new-labor-hours").value = "1";
    click("add-labor");
    await vi.waitFor(() =>
      expect(message().textContent).toBe("Could not reach the app. Check your signal and try again."));

    const draft = JSON.parse(localStorage.getItem(`wo-draft:${detail.id}:labor`));
    expect(draft).toMatchObject({
      number: detail.number,
      action: "add-labor",
      payload: { technicianId: "t1", minutes: 60 },
    });
  });

  it("replays and clears the draft once the server is reachable again", async () => {
    const { mod, detail } = await open({ assigned_to_ids: ["t1"], assigned_to_names: ["Ada L"] });
    server.use(http.post("/work-orders/:id/labor", () => HttpResponse.error()));
    card().querySelector(".wo-new-labor-hours").value = "1";
    click("add-labor");
    await vi.waitFor(() => expect(message().textContent).not.toBe(""));

    respond("post", "/work-orders/:id/labor", { ok: true });
    await mod.replayPendingDrafts();

    await vi.waitFor(() => expect(requestFor("/labor", "POST")).not.toBeNull());
    expect(requestFor("/labor", "POST").body).toEqual({ technician_id: "t1", minutes: 60 });
    expect(localStorage.getItem(`wo-draft:${detail.id}:labor`)).toBeNull();
    await vi.waitFor(() => expect(message().textContent).toBe("Reconnected — your entry saved."));
  });

  it("stops auto-retrying once the server actively rejects the replay", async () => {
    const { mod, detail } = await open({ assigned_to_ids: ["t1"], assigned_to_names: ["Ada L"] });
    server.use(http.post("/work-orders/:id/labor", () => HttpResponse.error()));
    card().querySelector(".wo-new-labor-hours").value = "1";
    click("add-labor");
    await vi.waitFor(() => expect(message().textContent).not.toBe(""));

    respond("post", "/work-orders/:id/labor", { detail: "Technician no longer assigned." }, { status: 400 });
    await mod.replayPendingDrafts();
    await vi.waitFor(() => expect(requestFor("/labor", "POST")).not.toBeNull());

    const key = `wo-draft:${detail.id}:labor`;
    expect(JSON.parse(localStorage.getItem(key)).lastError).toEqual({
      status: 400, detail: "Technician no longer assigned.",
    });

    // A second sweep (the next reconnect) must not hammer a save the server
    // already said no to.
    clearRequests();
    await mod.replayPendingDrafts();
    expect(requestFor("/labor", "POST")).toBeNull();
    expect(localStorage.getItem(key)).not.toBeNull();
  });
});

describe("edit-item offline recovery", () => {
  it("drafts with the row's own id, and replays against that same row", async () => {
    const { mod, detail } = await open({ items: [workOrderItem({ id: "wi1", quantity: "2" })] });
    server.use(http.patch("/work-orders/:id/items/:woItemId", () => HttpResponse.error()));
    card().querySelector(".wo-line-qty").value = "5";
    click("edit-item");
    await vi.waitFor(() => expect(message().textContent).not.toBe(""));

    const key = `wo-draft:${detail.id}:materials`;
    const draft = JSON.parse(localStorage.getItem(key));
    expect(draft).toMatchObject({ action: "edit-item", targetId: "wi1", payload: { quantity: 5 } });

    respond("patch", "/work-orders/:id/items/:woItemId", { ok: true });
    await mod.replayPendingDrafts();
    await vi.waitFor(() => expect(requestFor("/items/wi1", "PATCH")).not.toBeNull());
    expect(requestFor("/items/wi1", "PATCH").body).toEqual({ quantity: 5 });
    expect(localStorage.getItem(key)).toBeNull();
  });
});

describe("save-signature offline recovery", () => {
  const DRAFTS = "../../../../backend/static/workOrderDrafts.js";
  const IMAGE = "data:image/png;base64,iVBORw0KGgo=";
  const draftOf = (detail) => ({
    number: detail.number,
    action: "save-signature",
    payload: { image: IMAGE, witnessName: "Pat Doe", witnessPhone: "5555551234" },
  });

  it("replays a stored draft as the POST and clears it on success", async () => {
    const { mod, detail } = await open();
    const drafts = await import(DRAFTS);
    drafts.saveDraft(detail.id, "signature", draftOf(detail));
    respond("post", "/work-orders/:id/signature", { ...detail }, { status: 201 });

    await mod.replayPendingDrafts();

    await vi.waitFor(() => expect(requestFor("/signature", "POST")).not.toBeNull());
    expect(requestFor("/signature", "POST").body).toEqual({
      image: IMAGE, witness_name: "Pat Doe", witness_phone: "5555551234",
    });
    expect(localStorage.getItem(`wo-draft:${detail.id}:signature`)).toBeNull();
  });

  it("keeps the draft marked 409 and never retries once someone else signed first", async () => {
    const { mod, detail } = await open();
    const drafts = await import(DRAFTS);
    drafts.saveDraft(detail.id, "signature", draftOf(detail));
    respond("post", "/work-orders/:id/signature",
      { detail: "This work order is already signed." }, { status: 409 });

    await mod.replayPendingDrafts();
    await vi.waitFor(() => expect(requestFor("/signature", "POST")).not.toBeNull());

    const key = `wo-draft:${detail.id}:signature`;
    expect(JSON.parse(localStorage.getItem(key)).lastError).toEqual({
      status: 409, detail: "This work order is already signed.",
    });
    clearRequests();
    await mod.replayPendingDrafts();
    expect(requestFor("/signature", "POST")).toBeNull();
    expect(localStorage.getItem(key)).not.toBeNull();
  });

  it("resume after re-login reopens the section and leaves the draft for the replay", async () => {
    const detail = workOrderDetail();
    await mountWorkOrders({
      role: "supervisor",
      cards: [workOrderCard({ id: detail.id, number: detail.number, status: detail.status })],
      details: [detail],
    });
    const drafts = await import(DRAFTS);
    drafts.saveDraft(detail.id, "signature", draftOf(detail));
    drafts.setPendingResume({ workOrderId: detail.id, number: detail.number, section: "signature" });

    await openCard(0);

    // The capture is a pop-up flow: nothing on the card to refill, and no flow
    // reopened over a save the replay is about to make.
    const section = card().querySelector(".wo-signature-section");
    expect(section.open).toBe(true);
    expect(document.querySelector(".wo-sig-flow")).toBeNull();
    expect(drafts.readDraft(detail.id, "signature")).toMatchObject({ action: "save-signature" });
    expect(localStorage.getItem("wo-draft-resume")).toBeNull();
  });
});
