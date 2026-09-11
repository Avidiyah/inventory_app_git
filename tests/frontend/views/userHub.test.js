// Characterization coverage for views/userHub.js: loadUserHub per role, tab
// switching and the lazy tabs, per-tab failure isolation, the crew safety
// interval and the visibility lifecycle, the clock hand-off, and the three
// realtime subscriptions driven through the fake socket.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { requestFor, requests, clearRequests } from "../helpers/requests.js";
import {
  connectHub, el, mountHub, openHub, queries, restoreHub, restoreHubVisibility, stopClock,
} from "../helpers/hub.js";
import { filterOptions, hubGraphs, hubPayload, hubTimesheets, workOrderCard } from "../helpers/factories.js";

afterEach(() => {
  stopClock();                          // the hide: clears the tick and the safety interval
  expect(vi.getTimerCount()).toBe(0);   // checked while fake timers are still on; anything left is a leak
  restoreHub();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

describe("mountHub", () => {
  it("mounts with the dashboard tab active and nothing fetched", async () => {
    const { mod } = await mountHub();
    expect(typeof mod.loadUserHub).toBe("function");
    expect(typeof mod.refreshUserHub).toBe("function");
    expect(el.tab("dashboard").classList.contains("active")).toBe(true);
    expect(requests()).toHaveLength(0);
  });
});
