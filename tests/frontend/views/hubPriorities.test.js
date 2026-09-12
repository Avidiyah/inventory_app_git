// Characterization coverage for views/hubPriorities.js: the three role
// shapes through the hub shell, the blank when the source payload is
// missing, and the pure shape table by direct mount -- userHub.js decides
// which of personal / crew / admin reaches the renderer, so the branches it
// gates away are driven here against the real module (P6 deviation 5).

import { afterEach, describe, expect, it, vi } from "vitest";
import { userEvent } from "@testing-library/user-event";
import { el, mountHub, openHub, restoreHub, stopClock } from "../helpers/hub.js";
import { importView } from "../helpers/shell.js";
import { hubAdmin, hubCrew, hubPayload } from "../helpers/factories.js";

afterEach(() => {
  stopClock();
  expect(vi.getTimerCount()).toBe(0);
  restoreHub();
});

const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
const card = () => el.prioritiesMount().querySelector(".hub-priorities");
const tilesIn = (root) => Array.from(root.querySelectorAll(".hub-tile")).map((t) => ({
  label: t.querySelector(".hub-tile-label").textContent,
  value: t.querySelector(".hub-tile-value").textContent,
  sub: t.querySelector(".hub-tile-sub")?.textContent ?? null,
}));

describe("through the hub shell", () => {
  it("technician: one tile from the personal payload, under the Priorities label with its tip", async () => {
    await openHub({ role: "technician", hub: hubPayload({ priority: { assigned: 4, unassigned: null } }) });
    expect(card().querySelector(":scope > .hub-tile-label").textContent).toContain("Priorities");
    expect(card().querySelector(":scope > .hub-tile-label .tip-btn").dataset.tip).toBe("hub.priorities");
    expect(tilesIn(card())).toEqual([{ label: "High priority — assigned to you", value: "4", sub: null }]);
  });

  it("supervisor: two tiles from the crew payload; 'needs a technician' when unassigned > 0", async () => {
    await openHub({ role: "supervisor", crew: hubCrew({ priority: { assigned: 2, unassigned: 3 } }) });
    expect(tilesIn(card())).toEqual([
      { label: "High priority — your crew", value: "2", sub: null },
      { label: "High priority — unassigned", value: "3", sub: "needs a technician" },
    ]);
  });

  it("techfm_oa: two company-wide tiles from the admin payload, once the dashboard repaints", async () => {
    await openHub({ role: "techfm_oa", admin: hubAdmin({ priority: { assigned: 7, unassigned: 0 } }) });
    expect(card()).toBeNull();                 // blank after the first load -- N-P5-CHARACTERIZED
    await user().click(el.tab("dashboard"));
    expect(tilesIn(card())).toEqual([
      { label: "High priority — company-wide", value: "7", sub: null },
      { label: "High priority — unassigned", value: "0", sub: null },
    ]);
  });

  it("a supervisor whose crew payload failed gets an empty mount", async () => {
    await openHub({ role: "supervisor", crew: 500 });
    expect(el.prioritiesMount().innerHTML).toBe("");
  });
});

describe("mountHubPriorities directly", () => {
  async function mountDirect(role, sources) {
    await mountHub({ role: "technician" });    // the shell, for tooltip.js; nothing fetched
    const { mountHubPriorities } = await importView("views/hubPriorities.js");
    const container = document.createElement("div");
    document.body.appendChild(container);
    mountHubPriorities(container, { role, ...sources });
    return container;
  }

  it.each([
    ["technician", { personal: { assigned: 1, unassigned: null } },
      [{ label: "High priority — assigned to you", value: "1", sub: null }]],
    ["technician", { personal: null, crew: { assigned: 9, unassigned: 9 } }, []],
    ["supervisor", { crew: { assigned: 0, unassigned: 0 } }, [
      { label: "High priority — your crew", value: "0", sub: null },
      { label: "High priority — unassigned", value: "0", sub: null },
    ]],
    ["supervisor", { crew: null, personal: { assigned: 9 } }, []],       // personal is not a fallback
    ["techfm_oa", { admin: { assigned: 2, unassigned: 1 } }, [
      { label: "High priority — company-wide", value: "2", sub: null },
      { label: "High priority — unassigned", value: "1", sub: "needs a technician" },
    ]],
    ["admin", { admin: null, crew: { assigned: 5, unassigned: 5 } }, []],  // crew is not a fallback
    ["owner", { admin: { assigned: 0, unassigned: 4 } }, [
      { label: "High priority — company-wide", value: "0", sub: null },
      { label: "High priority — unassigned", value: "4", sub: "needs a technician" },
    ]],
  ])("%s with %j", async (role, sources, expected) => {
    const container = await mountDirect(role, sources);
    if (!expected.length) {
      expect(container.innerHTML).toBe("");
      return;
    }
    expect(tilesIn(container)).toEqual(expected);
  });

  it("a null container is a no-op", async () => {
    await mountHub({ role: "technician" });
    const { mountHubPriorities } = await importView("views/hubPriorities.js");
    expect(() => mountHubPriorities(null, { role: "technician", personal: { assigned: 1 } })).not.toThrow();
  });
});
