// Tutorial counts on the Users page (0b T9): the row line and the profile block.
// A fixture catalogue is injected, so counts never depend on the live registry.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { clearRequests, mountUsers, requestFor, restoreUsers, rowFor } from "../helpers/users.js";
import { importView } from "../helpers/shell.js";
import { user as userFactory } from "../helpers/factories.js";

afterEach(() => restoreUsers());

const CATALOGUE = [
  { page: "work-orders", key: "a", title: "Alpha" },
  { page: "work-orders", key: "b", title: "Bravo" },
  { page: "transaction", key: "c", title: "Charlie" },
  { page: "work-orders", key: "d", title: "Delta", minRole: "supervisor" },
];
const tech = userFactory({ username: "tech1", role: "technician" });
const lead = userFactory({ username: "lead1", role: "supervisor" });

const tag = (username) => rowFor(username).querySelector(".users-tut-count")?.textContent ?? null;

async function open({ map = {}, handlers = [], role = "admin", users = [tech, lead] } = {}) {
  const { mod } = await mountUsers({
    role, users,
    handlers: [...handlers, http.get("/tutorials/progress/users", () => HttpResponse.json(map))],
  });
  (await importView("views/usersTutorials.js")).setTutorialEntries(CATALOGUE);
  await mod.loadUsers();
  return mod;
}

describe("the row line", () => {
  it("counts finished against relevant scripts, judged on each person's role, ignoring orphan keys", async () => {
    await open({ map: { [tech.id]: ["a", "c", "gone"], [lead.id]: ["a", "d"] } });
    expect(tag("tech1")).toBe("2 of 3 tutorials");
    expect(tag("lead1")).toBe("2 of 4 tutorials");
  });

  it("shows 0 of N when the person has no entry", async () => {
    await open({ map: {} });
    expect(tag("tech1")).toBe("0 of 3 tutorials");
  });

  it("a failed fetch hides only the count line", async () => {
    await open({ handlers: [http.get("/tutorials/progress/users", () => new HttpResponse(null, { status: 500 }))] });
    expect(tag("tech1")).toBeNull();
    expect(rowFor("tech1").querySelectorAll("td")).toHaveLength(4);
  });

  it("is fetched with the list and again on the minute tick", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    try {
      await open({ map: { [tech.id]: ["a"] } });
      expect(tag("tech1")).toBe("1 of 3 tutorials");
      server.use(http.get("/tutorials/progress/users", () => HttpResponse.json({ [tech.id]: ["a", "b"] })));
      clearRequests();
      document.getElementById("saved-users-page").classList.add("active");
      await vi.advanceTimersByTimeAsync(60000);
      await vi.waitFor(() => expect(tag("tech1")).toBe("2 of 3 tutorials"));
      expect(requestFor("/tutorials/progress/users", "GET")).not.toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("the profile block", () => {
  const openProfile = async (map) => {
    server.use(http.get("/hub/people/:id/week", () => HttpResponse.json({
      user: tech, archived: false, week_start: "2026-09-14", week_end: "2026-09-20",
      server_now: "2026-09-16T15:00:00Z", days: [], total_clocked_minutes: 0,
      total_charged_minutes: 0, total_adjustment_minutes: 0, total_completed: 0, reviewable: false,
    })));
    await open({ map });
    rowFor("tech1").querySelector(".user-profile-btn").click();
    await vi.waitFor(() => expect(document.querySelector(".user-profile-tut")).not.toBeNull());
    return document.querySelector(".user-profile-tut");
  };

  it("lists only unfinished relevant scripts, by page, as plain text", async () => {
    const block = await openProfile({ [tech.id]: ["a"] });
    expect(block.textContent).toContain("Tutorials");
    expect(block.textContent).toContain("Bravo");
    expect(block.textContent).toContain("Charlie");
    expect(block.textContent).not.toContain("Alpha");
    expect(block.textContent).not.toContain("Delta");
    expect(block.querySelector("button, a")).toBeNull();
  });

  it("says so when everything is finished", async () => {
    const block = await openProfile({ [tech.id]: ["a", "b", "c"] });
    expect(block.textContent).toContain("Everything finished.");
  });
});
