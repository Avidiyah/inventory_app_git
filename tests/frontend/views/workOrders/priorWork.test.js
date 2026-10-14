// The prior-work guardrail on the card: a banner when someone else has worked
// the order, the notes opened, and Begin Charging held until the notes are read.

import { afterEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../../helpers/handlers.js";
import {
  card, message, mountWorkOrders, openCard, requests,
} from "../../helpers/workOrders.js";
import { restoreBrowserStubs } from "../../helpers/browserStubs.js";
import { workOrderCard, workOrderDetail } from "../../helpers/factories.js";

afterEach(() => restoreBrowserStubs());

const PRIOR = { by: ["Ann Lee"], last_at: "2026-10-14T15:05:00Z" };
const startCalls = () => requests().filter((r) => r.url.includes("/tracking/start"));
const begin = () => card().querySelector('[data-action="start-tracking-wo"]');
const ack = () => card().querySelector('[data-action="ack-notes-wo"]');

async function open(overrides) {
  const detail = workOrderDetail({ status: "assigned", ...overrides });
  await mountWorkOrders({
    role: "technician",
    cards: [workOrderCard({ id: detail.id, number: detail.number, status: "assigned" })],
    details: [detail],
  });
  // Assigned to the caller, so the test holds with or without self-assignment.
  const stateMod = await import("../../../../backend/static/state.js");
  detail.assigned_to_ids = [stateMod.getCurrentUser().id];
  detail.assigned_to_names = ["Me"];
  await openCard(0);
  return detail;
}

describe("prior-work guardrail", () => {
  it("shows no banner and leaves Begin Charging alone without prior work", async () => {
    await open({ notes: "Ann Lee began work" });
    expect(card().querySelector(".wo-prior-work")).toBeNull();
    expect(begin().disabled).toBe(false);
    expect(ack()).toBeNull();
  });

  it("warns, opens the notes and holds Begin Charging until they are read", async () => {
    await open({ notes: "Ann Lee began work", prior_work: PRIOR });
    expect(card().querySelector(".wo-prior-work").textContent).toContain("Someone has been here");
    expect(card().querySelector(".wo-prior-work").textContent).toContain("Ann Lee");
    expect(card().querySelector(".wo-notes-section").open).toBe(true);
    expect(begin().disabled).toBe(true);

    ack().click();

    expect(begin().disabled).toBe(false);
    expect(ack().hidden).toBe(true);
  });

  it("sends notes_acknowledged only after the notes were read", async () => {
    await open({ notes: "Ann Lee began work", prior_work: PRIOR });
    ack().click();
    begin().click();
    await new Promise((r) => setTimeout(r, 50));
    expect(startCalls()).toHaveLength(1);
    expect(startCalls()[0].body).toEqual({ notes_acknowledged: true });
  });

  it("warns without gating when there are no notes to read", async () => {
    await open({ notes: null, prior_work: PRIOR });
    expect(card().querySelector(".wo-prior-work").textContent).toContain("no notes");
    expect(begin().disabled).toBe(false);
    expect(ack()).toBeNull();
  });

  it("repaints on a 409 so the banner appears when someone charged after load", async () => {
    const detail = await open({ notes: "Ann Lee began work" });
    server.use(
      http.post("/work-orders/:id/tracking/start", () =>
        HttpResponse.json(
          { detail: "Someone has been here. Check the notes before charging." },
          { status: 409 }
        )
      ),
      http.get("/work-orders/:id", () =>
        HttpResponse.json({ ...detail, prior_work: PRIOR })
      )
    );

    begin().click();

    await new Promise((r) => setTimeout(r, 100));
    expect(card().querySelector(".wo-prior-work")).not.toBeNull();
    expect(begin().disabled).toBe(true);
    expect(message()?.className ?? "").not.toContain("error");
  });
});
