// W7 T5: the Dashboard sections patch in place (rules 1, 2, 8).

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { importView } from "../helpers/shell.js";
import { server } from "../helpers/handlers.js";
import { connectHub, el, openHub, restoreHub, stopClock } from "../helpers/hub.js";
import { hubAdmin, hubCrew, hubCrewTechnician, hubPayload } from "../helpers/factories.js";

const glowing = (root) => [...root.querySelectorAll(".just-changed")].map((n) => n.id);

describe("module patches", () => {
  it("priorities: a changed tile glows, its neighbour does not", async () => {
    const { mountHubPriorities } = await importView("views/hubPriorities.js");
    const mount = document.createElement("div");
    const draw = (unassigned) => mountHubPriorities(mount, { role: "admin", admin: { assigned: 1, unassigned } });
    draw(0);
    const section = mount.querySelector(".hub-priorities");
    draw(2);
    expect(mount.querySelector(".hub-priorities")).toBe(section);
    expect(glowing(mount)).toEqual(["hub-priorities-tile-high-priority-unassigned"]);
  });

  it("crew: cards keep identity when the order changes; only the changed card glows", async () => {
    const { mountHubCrew } = await importView("views/hubSupervisor.js");
    const mount = document.createElement("div");
    const a = hubCrewTechnician();
    const b = hubCrewTechnician({ user: { id: "u-b", first_name: "B", last_name: "Two", role: "technician" } });
    mountHubCrew(mount, hubCrew({ technicians: [a, b] }));
    const cardB = mount.querySelector("#hub-crew-u-b");
    mountHubCrew(mount, hubCrew({ technicians: [{ ...b, minutes_today: 30 }, a] }));
    expect(mount.querySelector("#hub-crew-u-b")).toBe(cardB);
    expect(glowing(mount)).toEqual(["hub-crew-u-b"]);
  });

});

describe("through the hub", () => {
  afterEach(() => {
    stopClock();
    restoreHub();
  });

  it("admin: a changed pipeline count glows only that tile", async () => {
    await openHub({ role: "admin" });
    const { mountHubAdminSummary } = await importView("views/hubAdmin.js");
    const mount = document.createElement("div");
    mountHubAdminSummary(mount, hubAdmin());
    mountHubAdminSummary(mount, hubAdmin({ pipeline: { ...hubAdmin().pipeline, review: 3 } }));
    expect(glowing(mount)).toContain("hub-admin-pipeline-review");
    expect(glowing(mount)).not.toContain("hub-admin-pipeline-created");
  });

  it("dashboard: the sub-mounts survive a repaint; only the changed tile glows", async () => {
    await openHub({ role: "technician" });
    const { mountHubDashboard } = await importView("views/hubTechnician.js");
    const mount = document.createElement("div");
    mountHubDashboard(mount, hubPayload());
    const crew = mount.querySelector("#hub-crew-mount");
    crew.innerHTML = "<p>board</p>";
    mountHubDashboard(mount, hubPayload({ counts: { assigned: 4, in_progress: 0, ready_to_complete: 0 } }));
    expect(mount.querySelector("#hub-crew-mount")).toBe(crew);
    expect(crew.textContent).toBe("board");
    expect(glowing(mount)).toEqual(["hub-dash-tile-assigned-to-me"]);
  });

  it("a live status change patches the Dashboard without rebuilding it", async () => {
    const { payload } = await openHub({ role: "supervisor", tab: "dashboard" });
    const { emit } = await connectHub();
    const crew = el.crewMount();
    server.use(http.get("/hub", () => HttpResponse.json(hubPayload({ user: payload.user, counts: { assigned: 5, in_progress: 0, ready_to_complete: 0 } }))));
    emit("work_order.status.changed", { id: "w1" });
    await vi.waitFor(() => expect(document.getElementById("hub-dash-tile-assigned-to-me").textContent).toContain("5"));
    expect(el.crewMount()).toBe(crew);
  });
});
