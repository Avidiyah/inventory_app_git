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
    const { detail } = await open({ role: "admin", assigned_to_ids: ["t1"], assigned_to_names: ["Ada L"] });
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
    const { mod, detail } = await open({ role: "admin", assigned_to_ids: ["t1"], assigned_to_names: ["Ada L"] });
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
    const { mod, detail } = await open({ role: "admin", assigned_to_ids: ["t1"], assigned_to_names: ["Ada L"] });
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

describe("save-details replay conflict (W3 rule 12)", () => {
  it("a replay refused as a conflict marks the draft and names the change, without buttons", async () => {
    const { mod, detail } = await open({ role: "admin", priority: "P1" });
    card().querySelector(".wo-edit-card").open = true;
    server.use(http.patch("/work-orders/:id", () => HttpResponse.error()));
    card().querySelector(".wo-edit-priority").value = "P3";
    click("save-details");
    await vi.waitFor(() => expect(message().textContent).not.toBe(""));

    respond("patch", "/work-orders/:id", { detail: { code: "field_conflict", message: "x", conflicts: [{
      field: "priority", label: "Priority", current: "P2", current_label: "P2", changed_by: "Maria Lopez", seconds_ago: 30,
    }] } }, { status: 409 });
    await mod.replayPendingDrafts();
    const key = `wo-draft:${detail.id}:details`;
    await vi.waitFor(() => expect(JSON.parse(localStorage.getItem(key)).lastError.status).toBe(409));
    const line = document.getElementById("wo-sec-msg");
    expect(line.textContent).toBe("Maria Lopez changed Priority to P2 30 seconds ago.");
    expect(line.querySelector("button")).toBeNull();
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
    // W3: the replay carries the quantity the row showed when it was drafted.
    expect(requestFor("/items/wi1", "PATCH").body).toEqual({ quantity: 5, expected_quantity: "2" });
    expect(localStorage.getItem(key)).toBeNull();
  });
});
