import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { mountShell, mountView } from "../helpers/shell.js";
import { server } from "../helpers/handlers.js";
import { setTestUser } from "../helpers/session.js";
import { user } from "../helpers/factories.js";

describe("the shell markup the module binds to", () => {
  it("renders the status filter with its seven statuses plus 'All'", () => {
    mountShell();
    const select = document.getElementById("work-orders-status-filter");
    const values = [...select.options].map((o) => o.value);
    expect(values).toEqual([
      "", "created", "assigned", "in_progress",
      "on_hold", "ready_to_complete", "completed", "review",
    ]);
    expect(select.options[0].textContent).toBe("All statuses");
  });

  it("has a label bound to the filter", () => {
    mountShell();
    const label = document.querySelector('label[for="work-orders-status-filter"]');
    expect(label).not.toBeNull();
    expect(label.textContent).toContain("Status");
  });
});

describe("views/workOrders.js", () => {
  it("imports against the real shell and exposes its public surface", async () => {
    await setTestUser({ role: "admin" });
    const mod = await mountView("views/workOrders.js");
    // The eleven exports P4 must preserve start here. Spot-check the ones
    // other modules import today.
    for (const name of [
      "soloNumberFromPath", "focusWorkOrder", "workOrderCardClass",
      "loadWorkOrders", "loadIntegrationsPage", "mountWorkOrderList",
    ]) {
      expect(typeof mod[name], name).toBe("function");
    }
  });

  it("captured live nodes, not nulls", async () => {
    await setTestUser({ role: "admin" });
    const mod = await mountView("views/workOrders.js");
    server.use(http.get("/work-orders", () => HttpResponse.json([])));
    server.use(http.get("/work-orders/filter-options", () => HttpResponse.json({})));
    // If the module had captured nulls, this throws on a property access
    // rather than rendering an empty list.
    await mod.loadWorkOrders();
    expect(document.getElementById("work-orders-list")).not.toBeNull();
  });
});

describe("setTestUser", () => {
  it("primes state.js in the module generation the view sees", async () => {
    await setTestUser({ role: "supervisor" });
    const state = await import("../../../backend/static/state.js");
    expect(state.getRole()).toBe("supervisor");
  });

  it("defaults to a technician", () => {
    expect(user().role).toBe("technician");
  });
});
