// The **performance board**: one ranked table from `GET /hub/performance`.
//
// A pure view: the payload goes in directly, nothing is fetched.

import { beforeEach, describe, expect, it } from "vitest";
import { performanceWindow } from "../helpers/factories.js";
import { mountPerformanceBoard } from "../../../backend/static/views/hubPerformanceBoard.js";

let host;

beforeEach(() => {
  document.body.innerHTML = `<div id="host"></div>`;
  host = document.getElementById("host");
});

function mount(payload = performanceWindow()) {
  mountPerformanceBoard(host, payload);
  return host;
}

const rows = () => [...host.querySelectorAll("tbody tr")];
const text = (el) => el.textContent.replace(/\s+/g, " ").trim();

describe("the performance board", () => {
  it("ranks people with medals, then the score and the four components", () => {
    mount();
    const [ann] = rows();
    expect(ann.querySelector(".hub-leaderboard-rank").textContent).toContain("🥇");
    expect(ann.querySelector(".sr-only").textContent).toBe("1st");
    expect(text(ann)).toContain("Ann Lee");
    expect(ann.querySelector(".hub-performance-score").textContent).toBe("94");
    const cells = [...ann.querySelectorAll("td.hub-leaderboard-num:not(.hub-performance-score)")].map((td) => td.textContent);
    expect(cells).toEqual(["$1,000.00", "90%", "80%", "5 / 5", "40:00"]);
  });

  it("names every reason a day or an order was left out, beside the person", () => {
    mount();
    const bo = rows()[1];
    const notes = [...bo.querySelectorAll(".hub-leaderboard-pending")].map(text);
    expect(notes).toEqual(["2 days left out: forgotten clock-out ×1, charged off shift ×1"]);
    const cy = rows().at(-1);
    expect([...cy.querySelectorAll(".hub-leaderboard-pending")].map(text))
      .toEqual(["WO-4471 left out: job clock auto-closed"]);
  });

  it("lists people under the floor after a divider, with no rank", () => {
    mount();
    const divider = host.querySelector("tr.hub-performance-divider");
    expect(text(divider)).toBe("Below 16 h this week");
    const cy = rows().at(-1);
    expect(cy.classList.contains("hub-performance-unranked")).toBe(true);
    expect(cy.querySelector(".hub-leaderboard-rank").textContent).toBe("—");
    expect(rows().indexOf(divider)).toBe(2);
  });

  it("draws no divider when everyone is ranked", () => {
    const payload = performanceWindow();
    payload.rows = payload.rows.slice(0, 2);
    mount(payload);
    expect(host.querySelector(".hub-performance-divider")).toBeNull();
  });

  it("says nobody has trusted time yet rather than drawing an empty table", () => {
    mount(performanceWindow({ rows: [] }));
    expect(host.querySelector("table")).toBeNull();
    expect(text(host.querySelector(".hub-leaderboard-empty"))).toBe("Nobody has trusted time this week yet.");
    mount(performanceWindow({ rows: [], window: "month", floor_minutes: 3600 }));
    expect(text(host.querySelector(".hub-leaderboard-empty"))).toBe("Nobody has trusted time this month yet.");
  });

  it("names the window in the caption and the floor in the divider for a month", () => {
    mount(performanceWindow({ window: "month", start: "2026-10-01", end: "2026-10-29", floor_minutes: 3600 }));
    expect(host.querySelector("caption").textContent).toContain("2026-10-01 through 2026-10-29");
    expect(text(host.querySelector(".hub-performance-divider"))).toBe("Below 60 h this month");
  });

  it("carries no inline styles and no buttons", () => {
    mount();
    expect(host.querySelector("[style]")).toBeNull();
    expect(host.querySelector("button")).toBeNull();
  });
});
