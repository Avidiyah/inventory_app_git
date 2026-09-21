// Starting a work-order clock behind a stale attendance punch (D5).
//
// The card resolves it in place: 409 -> read the blocking punch from
// GET /attendance/me -> promptTime -> self-close -> retry the Start.
//
// `promptTime` is the only piece this file stubs: it is a modal that
// tests/frontend/unit/dom.promptTime.test.js already covers on its own, and
// driving it through the DOM here would test that modal a second time.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import {
  card, message, mountWorkOrders, openCard, requests,
} from "../helpers/workOrders.js";
import { restoreBrowserStubs } from "../helpers/browserStubs.js";
import { workOrderCard, workOrderDetail } from "../helpers/factories.js";

vi.mock("../../../backend/static/dom.js", async () => {
  const actual = await vi.importActual("../../../backend/static/dom.js");
  return { ...actual, promptTime: vi.fn() };
});

afterEach(() => restoreBrowserStubs());

const STALE_DETAIL =
  "You are still punched in from Tue 10:12 PM. Close it on your Home tab before starting again.";
const OPEN_DETAIL = "You are already punched in since Wed 8:12 AM.";

const callsTo = (fragment) => requests().filter((r) => r.url.includes(fragment));

// `POST /tracking/start` refuses with `detail` until `failures` refusals have
// been handed out, then succeeds. MSW keeps the most recently registered
// handler first, so this wins over the fixture's own.
function refuseStart({ detail, failures = 1, then }) {
  let refused = 0;
  server.use(
    http.post("/work-orders/:id/tracking/start", () => {
      if (refused < failures) {
        refused += 1;
        return HttpResponse.json({ detail }, { status: 409 });
      }
      return HttpResponse.json(then);
    })
  );
}

function answerAttendanceMe(body, { status = 200 } = {}) {
  server.use(
    http.get("/attendance/me", () => HttpResponse.json(body, { status }))
  );
}

function selfCloseSucceeds() {
  server.use(
    http.post("/attendance/self-close", () => HttpResponse.json({ id: "punch-1" }))
  );
}

const openPunch = (stale) => ({
  server_now: "2026-09-21T15:00:00Z",
  day: "2026-09-21",
  clocked_minutes_today: 0,
  open_punch: {
    id: "punch-1",
    started_at: "2026-09-21T03:12:00Z",
    start_source: "manual",
    stale,
  },
});

// One assigned, not-yet-tracking card, opened and ready for the Start tap.
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

async function promptTimeMock() {
  const dom = await import("../../../backend/static/dom.js");
  return dom.promptTime;
}

const tapStart = () => card().querySelector('[data-action="start-tracking-wo"]').click();

describe("a stale punch blocking Start", () => {
  it("prompts, self-closes, and starts the clock", async () => {
    const detail = await openAssignedCard();
    refuseStart({ detail: STALE_DETAIL, then: { ...detail, status: "in_progress" } });
    answerAttendanceMe(openPunch(true));
    selfCloseSucceeds();
    (await promptTimeMock()).mockResolvedValue(new Date("2026-09-21T04:00:00Z"));

    tapStart();

    await vi.waitFor(() => expect(callsTo("/attendance/self-close")).toHaveLength(1));
    expect(callsTo("/attendance/self-close")[0].body)
      .toEqual({ ended_at: "2026-09-21T04:00:00.000Z" });
    await vi.waitFor(() => expect(callsTo("/tracking/start")).toHaveLength(2));
  });

  it("does nothing further when the prompt is dismissed", async () => {
    await openAssignedCard();
    refuseStart({ detail: STALE_DETAIL, failures: 99, then: null });
    answerAttendanceMe(openPunch(true));
    (await promptTimeMock()).mockResolvedValue(null);

    tapStart();

    await vi.waitFor(() => expect(message()?.textContent).toContain("still punched in"));
    expect(callsTo("/attendance/self-close")).toHaveLength(0);
    expect(callsTo("/tracking/start")).toHaveLength(1);
  });

  it("leaves a non-stale 409 as an inline message", async () => {
    await openAssignedCard();
    refuseStart({ detail: OPEN_DETAIL, failures: 99, then: null });
    answerAttendanceMe(openPunch(false));
    const promptTime = await promptTimeMock();
    promptTime.mockResolvedValue(new Date("2026-09-21T04:00:00Z"));

    tapStart();

    await vi.waitFor(() => expect(message()?.textContent).toContain("already punched in"));
    expect(promptTime).not.toHaveBeenCalled();
    expect(message().className).toContain("error");
  });

  it("falls back to the inline message when /attendance/me itself fails", async () => {
    // The recovery must never swallow the original error.
    await openAssignedCard();
    refuseStart({ detail: STALE_DETAIL, failures: 99, then: null });
    answerAttendanceMe({ detail: "boom" }, { status: 500 });
    (await promptTimeMock()).mockResolvedValue(new Date("2026-09-21T04:00:00Z"));

    tapStart();

    await vi.waitFor(() => expect(message()?.textContent).toContain("still punched in"));
    expect(message().className).toContain("error");
    expect(callsTo("/attendance/self-close")).toHaveLength(0);
  });
});
