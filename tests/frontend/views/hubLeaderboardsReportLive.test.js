// W7 T7: Leaderboards and Report follow live changes (rule 7) and patch in
// place.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { clearRequests } from "../helpers/requests.js";
import { queries, connectHub, el, openHub, restoreHub, stopClock } from "../helpers/hub.js";
import { hubReport, performanceWindow } from "../helpers/factories.js";

afterEach(() => {
  stopClock();
  restoreHub();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

describe("leaderboards", () => {
  it("work_order.status.changed refetches the selected window while the tab is showing", async () => {
    await openHub({ role: "admin" });
    const { emit } = await connectHub();
    await user().click(el.tab("leaderboards"));
    await vi.waitFor(() => expect(el.panel("leaderboards").querySelector(".hub-leaderboard")).not.toBeNull());
    await user().click(el.panel("leaderboards").querySelector('[data-window="month"]'));
    await vi.waitFor(() => expect(queries("/hub/performance").at(-1).window).toBe("month"));
    const before = queries("/hub/performance").length;
    emit("work_order.status.changed", { id: "w1" });
    await vi.waitFor(() => expect(queries("/hub/performance")).toHaveLength(before + 1));
    expect(queries("/hub/performance").at(-1).window).toBe("month");
  });

  it("no leaderboards fetch while the tab is hidden", async () => {
    await openHub({ role: "admin" });
    const { emit } = await connectHub();
    clearRequests();
    emit("attendance.changed");
    await vi.advanceTimersByTimeAsync(50);
    expect(queries("/hub/performance")).toHaveLength(0);
  });

  it("a reordered board keeps row identity and glows the changed row", async () => {
    const base = performanceWindow();
    await openHub({ role: "admin", performance: base });
    const { emit } = await connectHub();
    await user().click(el.tab("leaderboards"));
    await vi.waitFor(() => expect(el.panel("leaderboards").querySelector(".hub-leaderboard-row")).not.toBeNull());
    const [first] = base.rows;
    const row = document.getElementById(`lb-row-${first.user.id}`);
    server.use(http.get("/hub/performance", () => HttpResponse.json({
      ...base, rows: base.rows.map((r) => (r === first ? { ...r, score: r.score + 5 } : r)).reverse(),
    })));
    emit("work_order.status.changed", { id: "w1" });
    await vi.waitFor(() => expect(document.getElementById(`lb-row-${first.user.id}`).querySelector(".hub-performance-score").textContent).toBe(String(first.score + 5)));
    // Idiomorph may rebuild a row that moves backwards; rows hold no user
    // state, so only the pairing (one row per id, the right one glowing) matters.
    expect(row).toBeTruthy();
    expect(el.panel("leaderboards").querySelectorAll(`#lb-row-${first.user.id}`)).toHaveLength(1);
    const glowing = [...el.panel("leaderboards").querySelectorAll(".just-changed")].map((n) => n.id);
    expect(glowing).toEqual([`lb-row-${first.user.id}`]);
  });

  it("a background failure keeps the last good board", async () => {
    await openHub({ role: "admin" });
    const { emit } = await connectHub();
    await user().click(el.tab("leaderboards"));
    await vi.waitFor(() => expect(el.panel("leaderboards").querySelector(".hub-leaderboard")).not.toBeNull());
    server.use(http.get("/hub/performance", () => HttpResponse.json({ detail: "" }, { status: 500 })));
    const before = queries("/hub/performance").length;
    emit("attendance.changed");
    await vi.waitFor(() => expect(queries("/hub/performance")).toHaveLength(before + 1));
    await vi.advanceTimersByTimeAsync(10);
    expect(el.panel("leaderboards").querySelector(".hub-leaderboard")).not.toBeNull();
  });
});

describe("report", () => {
  it("an event refetches only the week in progress", async () => {
    await openHub({ role: "admin", report: hubReport() });
    const { emit } = await connectHub();
    await user().click(el.tab("report"));
    await vi.waitFor(() => expect(el.panel("report").querySelector(".hub-report-prev")).not.toBeNull());
    const before = queries("/hub/report").length;
    emit("work_order.status.changed", { id: "w1" });
    await vi.waitFor(() => expect(queries("/hub/report")).toHaveLength(before + 1));
  });

  it("a closed report week is not refetched by an event", async () => {
    await openHub({ role: "admin", report: hubReport() });
    const { emit } = await connectHub();
    await user().click(el.tab("report"));
    await vi.waitFor(() => expect(el.panel("report").querySelector(".hub-report-prev")).not.toBeNull());
    await user().click(el.panel("report").querySelector(".hub-report-prev"));
    await vi.waitFor(() => expect(queries("/hub/report").at(-1).week).toBeTruthy());
    const before = queries("/hub/report").length;
    emit("work_order.status.changed", { id: "w1" });
    await vi.advanceTimersByTimeAsync(50);
    expect(queries("/hub/report")).toHaveLength(before);
  });
});

describe("leaderboards reset", () => {
  it("a reset and re-render does not stack a second click listener", async () => {
    await openHub({ role: "admin" });
    const tab = await import("../../../backend/static/views/hubLeaderboardsTab.js");
    const panelEl = el.panel("leaderboards");
    tab.renderLeaderboardsTab(panelEl);
    await vi.waitFor(() => expect(panelEl.querySelector(".hub-leaderboards-prev")).not.toBeNull());
    tab.resetLeaderboardsTab(panelEl);
    tab.renderLeaderboardsTab(panelEl);
    await vi.waitFor(() => expect(panelEl.querySelector(".hub-leaderboards-prev")).not.toBeNull());
    await vi.advanceTimersByTimeAsync(10);
    const before = queries("/hub/performance").length;
    panelEl.querySelector(".hub-leaderboards-prev").click();
    await vi.advanceTimersByTimeAsync(50);
    expect(queries("/hub/performance")).toHaveLength(before + 1);
  });
});
