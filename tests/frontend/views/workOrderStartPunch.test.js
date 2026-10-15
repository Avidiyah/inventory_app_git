// Starting a work-order clock while a punch is open. Yesterday's forgotten
// punch is swept server-side (M2), so the card never prompts: any 409 the
// start returns is shown inline, as every other refusal is.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import {
  card, message, mountWorkOrders, openCard, requests,
} from "../helpers/workOrders.js";
import { restoreBrowserStubs } from "../helpers/browserStubs.js";
import { workOrderCard, workOrderDetail } from "../helpers/factories.js";

afterEach(() => restoreBrowserStubs());

const OPEN_DETAIL = "You are already punched in since Wed 8:12 AM.";

const callsTo = (fragment) => requests().filter((r) => r.url.includes(fragment));

async function openAssignedCard() {
  const detail = workOrderDetail({ status: "assigned" });
  await mountWorkOrders({
    role: "technician",
    cards: [workOrderCard({ id: detail.id, number: detail.number, status: "assigned" })],
    details: [detail],
  });
  const stateMod = await import("../../../backend/static/state.js");
  detail.assigned_to_ids = [stateMod.getCurrentUser().id];
  detail.assigned_to_names = ["Me"];
  await openCard(0);
  return detail;
}

describe("a punch 409 on Start", () => {
  it("shows inline, with no prompt and no attendance lookup", async () => {
    await openAssignedCard();
    server.use(http.post("/work-orders/:id/tracking/start",
      () => HttpResponse.json({ detail: OPEN_DETAIL }, { status: 409 })));

    card().querySelector('[data-action="start-tracking-wo"]').click();

    await vi.waitFor(() => expect(message()?.textContent).toContain("already punched in"));
    expect(message().className).toContain("error");
    expect(callsTo("/attendance/me")).toHaveLength(0);
    expect(callsTo("/tracking/start")).toHaveLength(1);
    expect(document.getElementById("prompt-time-overlay")?.hidden ?? true).toBe(true);
  });
});
