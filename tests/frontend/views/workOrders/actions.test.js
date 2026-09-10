// Characterization: the ten status-lifecycle branches of the click
// delegation, plus the two error paths every branch shares.
//
// Each branch is exercised at its minimum permitted role: the render-time
// role gating is already frozen in roles.test.js, so repeating 4 roles x 26
// actions here would be 100 tests of identical plumbing.
//
// The remaining fourteen branches (editor, labor, materials, technicians,
// combo) live in editorActions.test.js -- one file per half, because this
// repo caps a file at 500 lines.

import { describe, expect, it, vi } from "vitest";
import {
  answerConfirm, card, confirmOverlay, dismissMessageDialog, message,
  mountWorkOrders, openCard, requestFor, requests, respond, seedDetail, state,
} from "../../helpers/workOrders.js";
import { restoreBrowserStubs, stubLocationReload, stubWindowOpen } from "../../helpers/browserStubs.js";
import { workOrderCard, workOrderDetail } from "../../helpers/factories.js";

import { afterEach } from "vitest";
afterEach(() => restoreBrowserStubs());

// Mount one card, make the signed-in user assigned (or not), and open it.
async function open({ role, status, assigned = true, tracking = false, detail: overrides = {} }) {
  const detail = workOrderDetail({ status, ...overrides });
  await mountWorkOrders({
    role,
    cards: [workOrderCard({ id: detail.id, number: detail.number, status })],
    details: [detail],
  });
  const stateMod = await import("../../../../backend/static/state.js");
  const me = stateMod.getCurrentUser().id;
  if (assigned) {
    detail.assigned_to_ids = [me];
    detail.assigned_to_names = ["Me"];
  }
  if (tracking) {
    detail.active_labor_session = { id: "s1", technician_id: me, started_at: "2026-09-10T12:00:00Z" };
  }
  await openCard(0);
  return detail;
}

const click = (action) => card().querySelector(`[data-action="${action}"]`).click();

const detailGets = (id) =>
  requests().filter((r) => r.method === "GET" && r.url === `/work-orders/${id}`).length;

// The card body is rebuilt by the refresh, so "did it refresh" is a request
// count, not a DOM diff.
async function expectRefresh(id, count = 1) {
  await vi.waitFor(() => expect(detailGets(id)).toBe(count));
}

describe("start-tracking-wo", () => {
  it("posts to tracking/start and refreshes the card", async () => {
    const detail = await open({ role: "technician", status: "assigned" });
    respond("post", "/work-orders/:id/tracking/start", { ...detail, status: "in_progress" });
    click("start-tracking-wo");
    await vi.waitFor(() =>
      expect(requestFor("/tracking/start", "POST")).not.toBeNull());
    expect(requestFor("/tracking/start", "POST").url)
      .toBe(`/work-orders/${detail.id}/tracking/start`);
    await expectRefresh(detail.id);
  });
});

describe("stop-tracking-wo", () => {
  it("posts to tracking/stop and refreshes", async () => {
    const detail = await open({
      role: "technician", status: "in_progress", tracking: true,
    });
    respond("post", "/work-orders/:id/tracking/stop", { ...detail, status: "in_progress" });
    click("stop-tracking-wo");
    await expectRefresh(detail.id);
    expect(requestFor("/tracking/stop", "POST").body).toEqual({});
  });

  it("explains the automatic On-Hold in the REFRESHED message element", async () => {
    const detail = await open({
      role: "technician", status: "in_progress", tracking: true,
    });
    respond("post", "/work-orders/:id/tracking/stop", { ...detail, status: "on_hold" });
    seedDetail({ ...detail, status: "on_hold", active_labor_session: null });
    click("stop-tracking-wo");
    await vi.waitFor(() => expect(message().textContent)
      .toBe("Work stopped. Nobody is charging, so this is now On-Hold."));
    expect(message().className).toBe("success");
  });

  it("says nothing when the row stays In-Progress", async () => {
    const detail = await open({
      role: "technician", status: "in_progress", tracking: true,
    });
    respond("post", "/work-orders/:id/tracking/stop", { ...detail, status: "in_progress" });
    click("stop-tracking-wo");
    await expectRefresh(detail.id);
    expect(message().textContent).toBe("");
  });
});

describe("notify-supervisor-wo", () => {
  const setup = () => open({
    role: "technician", status: "in_progress", tracking: true,
  });

  it("posts to /complete and reports the handoff", async () => {
    const detail = await setup();
    respond("post", "/work-orders/:id/complete", { ...detail, status: "ready_to_complete" });
    seedDetail({ ...detail, status: "ready_to_complete", active_labor_session: null });
    click("notify-supervisor-wo");
    await vi.waitFor(() =>
      expect(message().textContent).toBe("Sent to your supervisor for review."));
    expect(requestFor("/complete", "POST").url).toBe(`/work-orders/${detail.id}/complete`);
  });

  it("stays quiet when the server lands some other status", async () => {
    const detail = await setup();
    respond("post", "/work-orders/:id/complete", { ...detail, status: "completed" });
    click("notify-supervisor-wo");
    await expectRefresh(detail.id);
    expect(message().textContent).toBe("");
  });

  it("pops the co-worker rule as a dialog and issues NO refresh", async () => {
    const detail = await setup();
    const rule = "All Users must Stop Charging before a Supervisor can be notified.";
    respond("post", "/work-orders/:id/complete", { detail: rule }, { status: 400 });
    click("notify-supervisor-wo");
    expect(await dismissMessageDialog()).toBe(rule);
    expect(detailGets(detail.id)).toBe(0);
    expect(message().textContent).toBe("");
  });

  it("falls through to the inline error for any other 400", async () => {
    const detail = await setup();
    respond("post", "/work-orders/:id/complete", { detail: "Something else" }, { status: 400 });
    click("notify-supervisor-wo");
    await vi.waitFor(() => expect(message().textContent).toBe("Something else"));
    expect(message().className).toBe("error");
    expect(confirmOverlay().hidden).toBe(true);
    expect(detailGets(detail.id)).toBe(0);
  });
});

describe("the plain PATCH branches", () => {
  it.each([
    ["send-back-wo", "ready_to_complete", "supervisor", { status: "in_progress" }],
    ["complete-wo", "in_progress", "supervisor", { status: "completed" }],
    ["reopen-wo", "completed", "supervisor", { status: "in_progress" }],
  ])("%s patches %o", async (action, status, role, patch) => {
    const detail = await open({ role, status });
    respond("patch", "/work-orders/:id", { ...detail, ...patch });
    click(action);
    await expectRefresh(detail.id);
    const sent = requestFor(`/work-orders/${detail.id}`, "PATCH");
    expect(sent.body).toEqual(patch);
  });
});

describe("hold-assigned-wo and resume-assigned-wo", () => {
  it("holds through the narrow endpoint", async () => {
    const detail = await open({ role: "technician", status: "in_progress" });
    respond("post", "/work-orders/:id/hold", { ...detail, status: "on_hold" });
    click("hold-assigned-wo");
    await expectRefresh(detail.id);
    expect(requestFor("/hold", "POST").url).toBe(`/work-orders/${detail.id}/hold`);
  });

  it("resumes through the narrow endpoint", async () => {
    const detail = await open({ role: "technician", status: "on_hold" });
    respond("post", "/work-orders/:id/resume", { ...detail, status: "in_progress" });
    click("resume-assigned-wo");
    await expectRefresh(detail.id);
    expect(requestFor("/resume", "POST").url).toBe(`/work-orders/${detail.id}/resume`);
  });
});

describe("review-wo", () => {
  // The routed supervisor, not assigned, is the minimum role that gets an
  // enabled control (see roles.test.js).
  async function openForReview() {
    const detail = workOrderDetail({ status: "completed" });
    await mountWorkOrders({
      role: "supervisor",
      cards: [workOrderCard({ id: detail.id, number: detail.number, status: "completed" })],
      details: [detail],
    });
    const stateMod = await import("../../../../backend/static/state.js");
    detail.supervisor_id = stateMod.getCurrentUser().id;
    await openCard(0);
    return detail;
  }

  it("asks first, and No sends nothing", async () => {
    const detail = await openForReview();
    click("review-wo");
    await answerConfirm(false);
    expect(requestFor(`/work-orders/${detail.id}`, "PATCH")).toBeNull();
    expect(detailGets(detail.id)).toBe(0);
  });

  it("patches to review on Yes", async () => {
    const detail = await openForReview();
    respond("patch", "/work-orders/:id", { ...detail, status: "review" });
    click("review-wo");
    await answerConfirm(true);
    await expectRefresh(detail.id);
    expect(requestFor(`/work-orders/${detail.id}`, "PATCH").body).toEqual({ status: "review" });
  });
});

describe("archive-wo", () => {
  it("asks first, and No archives nothing", async () => {
    const detail = await open({ role: "admin", status: "completed", assigned: false });
    click("archive-wo");
    await answerConfirm(false);
    expect(requestFor("/archive", "POST")).toBeNull();
  });

  it("archives, then reloads the whole list rather than the card", async () => {
    const detail = await open({ role: "admin", status: "completed", assigned: false });
    respond("post", "/work-orders/:id/archive", { ok: true });
    state.cards = [];
    click("archive-wo");
    await answerConfirm(true);
    await vi.waitFor(() =>
      expect(requestFor("/work-orders/", "GET")).not.toBeNull());
    expect(requestFor("/archive", "POST").url).toBe(`/work-orders/${detail.id}/archive`);
    // A full `loadWorkOrders()`, so the card page is gone and the list is back.
    await vi.waitFor(() =>
      expect(document.getElementById("work-orders-list").textContent)
        .toContain("No work orders match."));
    expect(detailGets(detail.id)).toBe(0);
  });
});

describe("open-netfacilities-wo", () => {
  it("opens the vendor URL in a new tab", async () => {
    const openSpy = stubWindowOpen();
    await open({ role: "admin", status: "assigned", assigned: false });
    click("open-netfacilities-wo");
    expect(openSpy).toHaveBeenCalledWith(
      "https://system.netfacilities.com/tools/viewworkorders/12345",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("encodes a number that needs escaping", async () => {
    const openSpy = stubWindowOpen();
    const detail = workOrderDetail({ number: "WO 12/34&x", status: "assigned" });
    await mountWorkOrders({
      role: "admin",
      cards: [workOrderCard({ id: detail.id, number: detail.number, status: "assigned" })],
      details: [detail],
    });
    await openCard(0);
    click("open-netfacilities-wo");
    expect(openSpy.mock.calls[0][0])
      .toBe("https://system.netfacilities.com/tools/viewworkorders/WO%2012%2F34%26x");
  });
});

describe("the shared error paths", () => {
  it("pops the 409 already-assigned detail, then reloads the page", async () => {
    const reload = stubLocationReload();
    const detail = await open({ role: "technician", status: "assigned" });
    const taken = "This Work Order was already assigned to Ada L.";
    respond("post", "/work-orders/:id/tracking/start", { detail: taken }, { status: 409 });
    click("start-tracking-wo");
    expect(await dismissMessageDialog()).toBe(taken);
    await vi.waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    expect(message().textContent).toBe("");
  });

  it("leaves any other 409 on the inline error path", async () => {
    const reload = stubLocationReload();
    const detail = await open({ role: "technician", status: "assigned" });
    respond("post", "/work-orders/:id/tracking/start", { detail: "Conflict elsewhere" }, { status: 409 });
    click("start-tracking-wo");
    await vi.waitFor(() => expect(message().textContent).toBe("Conflict elsewhere"));
    expect(reload).not.toHaveBeenCalled();
  });

  it("renders any other failure through friendlyError into .wo-message", async () => {
    await open({ role: "technician", status: "assigned" });
    respond("post", "/work-orders/:id/tracking/start", { detail: "Server exploded" }, { status: 500 });
    click("start-tracking-wo");
    await vi.waitFor(() => expect(message().textContent).toBe("Server exploded"));
    expect(message().className).toBe("error");
  });

  it("uses the crew-friendly wording for a 403", async () => {
    await open({ role: "technician", status: "assigned" });
    respond("post", "/work-orders/:id/tracking/start", { detail: "nope" }, { status: 403 });
    click("start-tracking-wo");
    await vi.waitFor(() => expect(message().textContent)
      .toBe("Your account can't do that. Ask a supervisor if this seems wrong."));
  });

  it("swallows the SECOND error on a card, because setMessage stripped the class", async () => {
    // Observed, and it is a defect: `setMessage` assigns `className`, so the
    // first message turns `<p class="wo-message">` into `<p class="error">`.
    // The click handler then re-queries `.wo-message`, gets null, and both
    // its "clear the previous message" call and its catch-all error report
    // are skipped -- the user clicks a failing button again and sees the
    // stale text. Filed in docs/open-work.md; not fixed here.
    await open({ role: "technician", status: "assigned" });
    respond("post", "/work-orders/:id/tracking/start", { detail: "First failure" }, { status: 500 });
    click("start-tracking-wo");
    await vi.waitFor(() => expect(message().textContent).toBe("First failure"));
    expect(card().querySelector(".wo-message")).toBeNull();

    respond("post", "/work-orders/:id/tracking/start", { detail: "Second failure" }, { status: 500 });
    click("start-tracking-wo");
    await vi.waitFor(() =>
      expect(requests().filter((r) => r.url.endsWith("/tracking/start")).length).toBe(2));
    expect(message().textContent).toBe("First failure");
  });
});

describe("the mode select", () => {
  it("patches entry_mode and reports the new default", async () => {
    const detail = await open({ role: "supervisor", status: "assigned" });
    respond("patch", "/work-orders/:id", { ...detail, entry_mode: "retroactive" });
    const select = card().querySelector(".wo-mode-select");
    select.value = "retroactive";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await vi.waitFor(() =>
      expect(message().textContent).toBe("New entries will be retroactive."));
    expect(requestFor(`/work-orders/${detail.id}`, "PATCH").body)
      .toEqual({ entry_mode: "retroactive" });
    // No card refresh on this path.
    expect(detailGets(detail.id)).toBe(0);
  });

  it("reports a failure without touching the card", async () => {
    const detail = await open({ role: "supervisor", status: "assigned" });
    respond("patch", "/work-orders/:id", { detail: "No" }, { status: 400 });
    const select = card().querySelector(".wo-mode-select");
    select.value = "retroactive";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await vi.waitFor(() => expect(message().textContent).toBe("No"));
    expect(message().className).toBe("error");
  });
});
