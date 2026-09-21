// Characterization coverage for views/hubSupervisor.js: the crew board's
// roll-up tiles and the techfm_oa+ tile drop, the attention list, the
// technician card matrix (on clock, off clock, never worked, the flag
// vocabulary, the Unknown fallback) and D16's absent board.
//
// All of it through the real hub shell: userHub.js is the only caller, and it
// owns both `isAdminPlus` (by role) and whether the board renders at all (by
// `led.total`), so driving the renderer directly would test a contract no
// production path can reach (P6 deviation 5 stays unused here).

import { afterEach, describe, expect, it, vi } from "vitest";
import { el, openHub as baseOpenHub, restoreHub, stopClock } from "../helpers/hub.js";

// This suite asserts on the Dashboard tab's body, which only mounts while
// that tab is active -- the hub now opens on Home.
const openHub = (opts = {}) => baseOpenHub({ tab: "dashboard", ...opts });
import { hubAttentionItem, hubCrew, hubCrewTechnician, hubRunningSession } from "../helpers/factories.js";

afterEach(() => {
  stopClock();                          // the hide: clears the tick and the safety interval
  expect(vi.getTimerCount()).toBe(0);
  restoreHub();
});

const grid = () => el.crewMount().querySelector(".hub-tile-grid");
const board = () => el.crewMount().querySelector(".hub-crew");
const cards = () => el.crewMount().querySelectorAll(".hub-crew-card");
const card = () => cards()[0];
const tilesIn = (root) => Array.from(root.querySelectorAll(".hub-tile")).map((t) => ({
  label: t.querySelector(".hub-tile-label").textContent,
  value: t.querySelector(".hub-tile-value").textContent,
  sub: t.querySelector(".hub-tile-sub")?.textContent ?? null,
}));

// The crew payload with one technician; a card test names only the field
// under test. `led.total` is 1 in the factory, so the board renders for
// either role tier (D16 is driven explicitly at the bottom of the file).
const crewWith = (tech = {}, extra = {}) =>
  hubCrew({ technicians: [hubCrewTechnician(tech)], ...extra });
const openCrew = (tech = {}, extra = {}, role = "supervisor") =>
  openHub({ role, crew: crewWith(tech, extra) });

describe("roll-ups", () => {
  it("a supervisor gets three tiles: led, crew on the clock, crew time today", async () => {
    await openHub({ role: "supervisor", crew: hubCrew({
      led: { total: 4, in_progress: 2, ready_to_complete: 1 },
      crew_on_clock: 2, crew_total: 5, crew_minutes_today: 185,
    }) });
    expect(tilesIn(grid())).toEqual([
      { label: "Work orders I lead", value: "4", sub: "2 in progress" },
      { label: "Crew on the clock", value: "2 of 5", sub: null },
      { label: "Crew time today", value: "3 h 5 m", sub: "ticking" },
    ]);
  });

  it("nothing in progress and nobody on the clock drops both subs", async () => {
    await openHub({ role: "supervisor", crew: hubCrew({
      led: { total: 4, in_progress: 0, ready_to_complete: 0 },
      crew_on_clock: 0, crew_total: 5, crew_minutes_today: 0,
    }) });
    expect(tilesIn(grid())).toEqual([
      { label: "Work orders I lead", value: "4", sub: null },
      { label: "Crew on the clock", value: "0 of 5", sub: null },
      { label: "Crew time today", value: "0 m", sub: null },
    ]);
  });

  it("techfm_oa+ drops the Crew on the clock tile (the admin Time tiles supersede it)", async () => {
    await openHub({ role: "techfm_oa", crew: hubCrew({
      led: { total: 4, in_progress: 1, ready_to_complete: 0 },
      crew_on_clock: 3, crew_total: 5, crew_minutes_today: 60,
    }) });
    expect(tilesIn(grid())).toEqual([
      { label: "Work orders I lead", value: "4", sub: "1 in progress" },
      { label: "Crew time today", value: "1 h 0 m", sub: "ticking" },
    ]);
  });
});

describe("needs attention", () => {
  it("is omitted entirely when the list is empty", async () => {
    await openCrew();
    expect(el.crewMount().querySelector(".hub-attention")).toBeNull();
  });

  it("one row per item, with the count badge, the icon and an escaped subject", async () => {
    await openHub({ role: "supervisor", crew: hubCrew({ attention: [
      hubAttentionItem(),
      hubAttentionItem({ subject: "<b>WO 7002</b>", detail: "assigned, idle 2 days" }),
    ] }) });
    const section = el.crewMount().querySelector(".hub-attention");
    expect(section.querySelector(".hub-tile-label").textContent).toContain("Needs attention");
    expect(section.querySelector(".hub-tile-label .tip-btn").dataset.tip).toBe("hub.attention");
    expect(section.querySelector(".hub-tile-count").textContent).toBe("2");
    const rows = section.querySelectorAll(".hub-attention-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].querySelector(".hub-attention-icon").textContent).toBe("⚠");
    expect(rows[0].querySelector("span:last-child").textContent).toBe("WO 7001 — untouched 4 days");
    expect(rows[1].querySelector("span:last-child").textContent).toBe("<b>WO 7002</b> — assigned, idle 2 days");
    expect(rows[1].querySelector("b")).toBeNull();
  });
});

describe("technician cards", () => {
  it("on clock: the running classes, the work order and minutes off the payload's server_now", async () => {
    // 75 minutes before hubCrew()'s own server_now (2026-09-10T12:00:00Z).
    await openCrew({ running_session: hubRunningSession({ started_at: "2026-09-10T10:45:00Z" }) });
    expect(card().classList.contains("hub-crew-card-on")).toBe(true);
    expect(card().querySelector(".hub-crew-dot").classList.contains("hub-crew-dot-on")).toBe(true);
    expect(card().querySelector(".hub-crew-clock-label").textContent).toBe("ON CLOCK");
    expect(card().querySelector(".hub-crew-subject").textContent).toBe("WO 7001");
    expect(card().querySelector(".hub-crew-running").textContent).toBe("running 1 h 15 m");
  });

  // One mount per test throughout: the second `openHub` in a file gets the
  // cached userHub.js instance, whose captured elements still point at the
  // first shell, so the new document has no `#hub-crew-mount` to paint into.
  it("off clock: Last worked as a weekday stamp", async () => {
    const lastWorked = "2026-09-09T15:30:00Z";
    await openCrew({ last_worked: lastWorked });
    const stamp = new Date(lastWorked).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
    expect(card().classList.contains("hub-crew-card-on")).toBe(false);
    expect(card().querySelector(".hub-crew-dot").classList.contains("hub-crew-dot-on")).toBe(false);
    expect(card().querySelector(".hub-crew-clock-label").textContent).toBe("OFF CLOCK");
    expect(card().querySelector(".hub-crew-subject").textContent).toBe(`Last worked ${stamp}`);
    expect(card().querySelector(".hub-crew-running")).toBeNull();
  });

  it("off clock with no session ever: Last worked Never", async () => {
    await openCrew({ last_worked: null });
    expect(card().querySelector(".hub-crew-subject").textContent).toBe("Last worked Never");
  });

  it("Today and the counts line", async () => {
    await openCrew({ minutes_today: 120, assigned: 3, in_progress: 1, ready_to_complete: 2 });
    expect(card().querySelector(".hub-crew-today strong").textContent).toBe("2 h 0 m");
    expect(card().querySelector(".hub-crew-counts").textContent).toBe("Assigned 3 · In-prog 1 · Ready 2");
  });

  it.each([
    [["long_session"], ["⚠ long session"]],
    [["approaching_cap", "assigned_idle"], ["⚠ approaching cap", "⚠ idle"]],
    // Anything outside the map still renders, as readable snake case.
    [["weird_new_flag"], ["⚠ weird new flag"]],
  ])("flags %j render as %j", async (flags, expected) => {
    await openCrew({ flags });
    expect(Array.from(card().querySelectorAll(".hub-crew-flag")).map((s) => s.textContent)).toEqual(expected);
  });

  it("no flags: no flag row at all", async () => {
    await openCrew({ flags: [] });
    expect(card().querySelector(".hub-crew-flags")).toBeNull();
  });

  it("a nameless user reads Unknown", async () => {
    await openCrew({ user: { id: "u1", first_name: null, last_name: null, role: "technician" } });
    expect(card().querySelector(".hub-crew-name").textContent).toBe("Unknown");
  });

  it("a name carrying markup renders literally", async () => {
    await openCrew({ user: { id: "u1", first_name: "<b>Bob</b>", last_name: "Smith", role: "technician" } });
    expect(card().querySelector(".hub-crew-name").textContent).toBe("<b>Bob</b> Smith");
    expect(card().querySelector(".hub-crew-name b")).toBeNull();
  });

  it("an empty crew keeps the section and explains the routing", async () => {
    await openHub({ role: "supervisor", crew: hubCrew({ technicians: [] }) });
    expect(board().querySelector(".hub-tile-label").textContent).toContain("My crew");
    expect(board().querySelector(".hub-tile-label .tip-btn").dataset.tip).toBe("hub.crew");
    expect(board().querySelector(".hint").textContent).toContain("No one is currently routed to you.");
    expect(board().querySelector(".hub-crew-grid")).toBeNull();
    expect(cards()).toHaveLength(0);
  });
});

describe("D16: who gets a board at all", () => {
  const led = (total) => ({ led: { total, in_progress: 0, ready_to_complete: 0 } });

  it("a supervisor with nothing routed to them still gets the board", async () => {
    await openCrew({}, led(0));
    expect(board()).not.toBeNull();
    expect(tilesIn(grid())).toHaveLength(3);
  });

  it("a techfm_oa viewer leading nothing gets no board -- the mount is emptied", async () => {
    await openCrew({}, led(0), "techfm_oa");
    expect(el.crewMount().innerHTML).toBe("");
  });

  it("a techfm_oa viewer leading one work order gets the board, minus the on-clock tile", async () => {
    await openCrew({}, led(1), "techfm_oa");
    expect(cards()).toHaveLength(1);
    expect(tilesIn(grid()).map((t) => t.label)).toEqual(["Work orders I lead", "Crew time today"]);
  });
});
