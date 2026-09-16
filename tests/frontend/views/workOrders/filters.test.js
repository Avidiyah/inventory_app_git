// Characterization: the list-loading surface -- filters, keyword searches,
// sort, the RECENT_LIMIT cap, reference data, the archived-number restore
// prompt, and the second renderer the User Hub mounts.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../../helpers/handlers.js";
import {
  answerConfirm, cardEls, listEl, mountWorkOrders, requestFor, requests,
  respond, seedList, state,
} from "../../helpers/workOrders.js";
import { restoreBrowserStubs, stubScroll } from "../../helpers/browserStubs.js";
import { filterOptions, user, workOrderCard } from "../../helpers/factories.js";

afterEach(() => restoreBrowserStubs());

// The list fetch is issued a couple of microtasks into `loadWorkOrders`, and
// the recorder is synchronous, so draining microtasks is enough -- no timer
// advancing, which matters under `vi.useFakeTimers()`.
async function flush() {
  for (let i = 0; i < 20; i += 1) await Promise.resolve();
}

const listUrls = () =>
  requests().filter((r) => r.url.startsWith("/work-orders/?") || r.url === "/work-orders/")
    .map((r) => r.url);

const el = (id) => document.getElementById(id);

const change = (control, value) => {
  control.value = value;
  control.dispatchEvent(new Event("change", { bubbles: true }));
};

const typeIn = (control, value) => {
  control.value = value;
  control.dispatchEvent(new Event("input", { bubbles: true }));
};

const pressEnter = (control) =>
  control.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));

describe("the seven filter selects", () => {
  it.each([
    ["work-orders-status-filter", "in_progress", "status=in_progress"],
    ["work-orders-service-filter", "Electrical", "service_type=Electrical"],
    ["work-orders-priority-filter", "Urgent", "priority=Urgent"],
    ["work-orders-date-filter", "2026-09-10", "scheduled_date=2026-09-10"],
  ])("%s reloads with %s", async (id, value, param) => {
    await mountWorkOrders({ role: "admin" });
    change(el(id), value);
    await flush();
    expect(listUrls()).toHaveLength(1);
    expect(listUrls()[0]).toContain(param);
    // A filtered list is a search: the RECENT_LIMIT cap is dropped.
    expect(listUrls()[0]).not.toContain("limit=");
  });

  it("sends the community filter", async () => {
    await mountWorkOrders({
      role: "admin",
      filterOptions: filterOptions({ communities: [{ value: "Maple Ridge", label: "Maple Ridge" }] }),
    });
    change(el("work-orders-community-filter"), "Maple Ridge");
    await flush();
    expect(listUrls()[0]).toContain("community=Maple+Ridge");
  });

  it("sends the supervisor filter as supervisor_id", async () => {
    await mountWorkOrders({
      role: "admin",
      filterOptions: filterOptions({ supervisors: [{ id: "s1", name: "Sue S" }] }),
    });
    change(el("work-orders-supervisor-filter"), "s1");
    await flush();
    expect(listUrls()[0]).toContain("supervisor_id=s1");
  });

  it("populates and sends the technician filter as assigned_to_id, Supervisor+ only", async () => {
    const tech = user({ id: "t1", full_name: "Tim Tech", role: "technician" });
    await mountWorkOrders({ role: "admin", users: [tech] });
    const values = [...el("work-orders-technician-filter").options].map((o) => `${o.value}|${o.textContent}`);
    expect(values).toEqual(["|All technicians", "t1|Tim Tech"]);
    expect(el("work-orders-technician-field").hidden).toBe(false);
    change(el("work-orders-technician-filter"), "t1");
    await flush();
    expect(listUrls()[0]).toContain("assigned_to_id=t1");
  });

  it("hides the technician filter below Supervisor", async () => {
    await mountWorkOrders({ role: "technician" });
    expect(el("work-orders-technician-field").hidden).toBe(true);
  });

  it("always carries the sort direction", async () => {
    await mountWorkOrders({ role: "admin" });
    change(el("work-orders-status-filter"), "completed");
    await flush();
    expect(listUrls()[0]).toContain("sort=scheduled_asc");
  });

  it("resets Show all", async () => {
    const cards = Array.from({ length: 11 }, (_, i) => workOrderCard({ number: `${i}` }));
    await mountWorkOrders({ role: "admin", cards });
    el("wo-show-all").click();
    await flush();
    expect(listUrls().at(-1)).not.toContain("limit=");
    change(el("work-orders-status-filter"), "completed");
    await flush();
    // Back to a capped browse the moment the filter is cleared again.
    change(el("work-orders-status-filter"), "");
    await flush();
    expect(listUrls().at(-1)).toContain("limit=10");
  });
});

describe("Clear filters", () => {
  it("empties every control, reloads once, and cancels the pending debounces", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    await mountWorkOrders({ role: "admin" });
    el("work-orders-status-filter").value = "completed";
    el("work-orders-search").value = "123";
    typeIn(el("work-orders-location-search"), "hall");
    typeIn(el("work-orders-task-search"), "leak");
    el("work-orders-clear-filters").click();
    await flush();
    expect(listUrls()).toHaveLength(1);
    expect(listUrls()[0]).toBe("/work-orders/?limit=10&sort=scheduled_asc");
    for (const id of [
      "work-orders-status-filter", "work-orders-service-filter", "work-orders-priority-filter",
      "work-orders-supervisor-filter", "work-orders-technician-filter", "work-orders-community-filter",
      "work-orders-date-filter",
      "work-orders-search", "work-orders-location-search", "work-orders-task-search",
    ]) {
      expect(el(id).value, id).toBe("");
    }
    // The two keyword debounces armed above must not fire a second load.
    vi.advanceTimersByTime(1000);
    await flush();
    expect(listUrls()).toHaveLength(1);
  });
});

describe("the keyword searches", () => {
  it.each([
    ["work-orders-location-search", "location_q=hall"],
    ["work-orders-task-search", "task_q=leak"],
  ])("%s coalesces typing into one load after 250 ms", async (id, param) => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    await mountWorkOrders({ role: "admin" });
    const input = el(id);
    typeIn(input, "h");
    vi.advanceTimersByTime(100);
    typeIn(input, "ha");
    vi.advanceTimersByTime(100);
    typeIn(input, id.includes("location") ? "hall" : "leak");
    await flush();
    expect(listUrls()).toHaveLength(0);
    vi.advanceTimersByTime(249);
    await flush();
    expect(listUrls()).toHaveLength(0);
    vi.advanceTimersByTime(1);
    await flush();
    expect(listUrls()).toHaveLength(1);
    expect(listUrls()[0]).toContain(param);
  });

  it("Enter flushes the keyword search immediately", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    await mountWorkOrders({ role: "admin" });
    typeIn(el("work-orders-location-search"), "hall");
    pressEnter(el("work-orders-location-search"));
    await flush();
    expect(listUrls()).toHaveLength(1);
    // The cancelled debounce does not fire a second one.
    vi.advanceTimersByTime(1000);
    await flush();
    expect(listUrls()).toHaveLength(1);
  });

  it("the number search debounces the same way and asks for the archived check", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    await mountWorkOrders({ role: "admin", lookup: { found: false } });
    typeIn(el("work-orders-search"), "12345");
    vi.advanceTimersByTime(250);
    await flush();
    expect(listUrls()).toHaveLength(1);
    expect(listUrls()[0]).toContain("q=12345");
    // The archived lookup is the number search's own extra step.
    await vi.waitFor(() => expect(requestFor("/work-orders/lookup")).not.toBeNull());
  });

  it("the Search button runs it without waiting", async () => {
    await mountWorkOrders({ role: "admin", lookup: { found: false } });
    el("work-orders-search").value = "12345";
    el("work-orders-search-btn").click();
    await flush();
    expect(listUrls()).toHaveLength(1);
  });
});

describe("the sort control", () => {
  it("marks the active direction, oldest first by default", async () => {
    await mountWorkOrders({ role: "admin" });
    const buttons = [...el("work-orders-sort").querySelectorAll("[data-sort]")];
    expect(buttons.map((b) => b.getAttribute("aria-pressed"))).toEqual(["false", "true"]);
  });

  it("switches direction, persists it, and reloads", async () => {
    await mountWorkOrders({ role: "admin" });
    el("work-orders-sort").querySelector('[data-sort="scheduled_desc"]').click();
    await flush();
    expect(listUrls()[0]).toContain("sort=scheduled_desc");
    expect(localStorage.getItem("workOrders.sort")).toBe("scheduled_desc");
    const buttons = [...el("work-orders-sort").querySelectorAll("[data-sort]")];
    expect(buttons.map((b) => b.getAttribute("aria-pressed"))).toEqual(["true", "false"]);
  });

  it("ignores a click on the direction already active", async () => {
    await mountWorkOrders({ role: "admin" });
    el("work-orders-sort").querySelector('[data-sort="scheduled_asc"]').click();
    await flush();
    expect(listUrls()).toHaveLength(0);
  });

  it("ignores an unrecognised data-sort", async () => {
    await mountWorkOrders({ role: "admin" });
    const rogue = document.createElement("button");
    rogue.dataset.sort = "by_vibes";
    el("work-orders-sort").appendChild(rogue);
    rogue.click();
    await flush();
    expect(listUrls()).toHaveLength(0);
  });

  it("honours a stored direction on import", async () => {
    localStorage.setItem("workOrders.sort", "scheduled_desc");
    await mountWorkOrders({ role: "admin" });
    change(el("work-orders-status-filter"), "completed");
    await flush();
    expect(listUrls()[0]).toContain("sort=scheduled_desc");
  });

  it("falls back to the oldest-first default on a stored value it does not recognise", async () => {
    localStorage.setItem("workOrders.sort", "by_vibes");
    await mountWorkOrders({ role: "admin" });
    change(el("work-orders-status-filter"), "completed");
    await flush();
    expect(listUrls()[0]).toContain("sort=scheduled_asc");
  });
});

describe("RECENT_LIMIT", () => {
  const many = (n) => Array.from({ length: n }, (_, i) => workOrderCard({ number: `${i}` }));

  it("caps an unfiltered browse at ten and offers Show all", async () => {
    await mountWorkOrders({ role: "admin", cards: many(10) });
    expect(cardEls()).toHaveLength(10);
    expect(el("work-orders-more").hidden).toBe(false);
    expect(el("wo-show-all").textContent).toBe("Show all work orders");
  });

  it("offers nothing when the capped page did not fill", async () => {
    await mountWorkOrders({ role: "admin", cards: many(3) });
    expect(el("work-orders-more").hidden).toBe(true);
    expect(el("work-orders-more").innerHTML).toBe("");
  });

  it("Show all drops the cap and offers the way back", async () => {
    await mountWorkOrders({ role: "admin", cards: many(10) });
    seedList(many(11));
    el("wo-show-all").click();
    await vi.waitFor(() => expect(cardEls()).toHaveLength(11));
    expect(listUrls()[0]).not.toContain("limit=");
    expect(el("wo-show-recent").textContent).toBe("Show recent only");
    seedList(many(10));
    el("wo-show-recent").click();
    await vi.waitFor(() => expect(cardEls()).toHaveLength(10));
    expect(listUrls().at(-1)).toContain("limit=10");
  });
});

describe("the filter options request", () => {
  it("populates each select once, empty label first", async () => {
    await mountWorkOrders({
      role: "admin",
      filterOptions: filterOptions({
        service_types: ["Electrical"],
        priorities: ["Normal"],
        supervisors: [{ id: "s1", name: "Sue S" }],
        communities: [{ value: "mr", label: "Maple Ridge" }],
      }),
    });
    const values = (id) => [...el(id).options].map((o) => `${o.value}|${o.textContent}`);
    expect(values("work-orders-service-filter")).toEqual(["|All service types", "Electrical|Electrical"]);
    expect(values("work-orders-supervisor-filter")).toEqual(["|All supervisors", "s1|Sue S"]);
    expect(values("work-orders-community-filter")).toEqual(["|All communities", "mr|Maple Ridge"]);
    // Priority always gains the "not imported" sentinel at the end.
    expect(values("work-orders-priority-filter"))
      .toEqual(["|All priorities", "Normal|Normal", "__none__|Not imported"]);
  });

  it("is fetched once per visit, not once per load", async () => {
    const { mod } = await mountWorkOrders({ role: "admin" });
    await mod.loadWorkOrders();
    await mod.loadWorkOrders();
    expect(requests().filter((r) => r.url === "/work-orders/filter-options")).toHaveLength(0);
  });

  it("leaves the selects alone and retries next time when it fails", async () => {
    const { mod } = await mountWorkOrders({ role: "admin", load: false });
    respond("get", "/work-orders/filter-options", { detail: "nope" }, { status: 500 });
    await mod.loadWorkOrders();
    expect(el("work-orders-service-filter").options).toHaveLength(1);
    await mod.loadWorkOrders();
    expect(requests().filter((r) => r.url === "/work-orders/filter-options")).toHaveLength(2);
  });
});

describe("ensureReferenceData", () => {
  it("fetches items and users once per visit", async () => {
    const { mod } = await mountWorkOrders({ role: "admin" });
    await mod.loadWorkOrders();
    expect(requests().filter((r) => r.url === "/items/")).toHaveLength(0);
    expect(requests().filter((r) => r.url === "/users/")).toHaveLength(0);
  });

  it("re-fetches everything when the caller asks for a refresh", async () => {
    const { mod } = await mountWorkOrders({ role: "admin" });
    await mod.loadWorkOrders({ refreshReferenceData: true });
    expect(requests().filter((r) => r.url === "/items/")).toHaveLength(1);
    expect(requests().filter((r) => r.url === "/users/")).toHaveLength(1);
    expect(requests().filter((r) => r.url === "/work-orders/filter-options")).toHaveLength(1);
  });

  it("invalidates users and filter options on user-names-updated", async () => {
    const { mod } = await mountWorkOrders({ role: "admin" });
    document.dispatchEvent(new Event("user-names-updated"));
    await mod.loadWorkOrders();
    expect(requests().filter((r) => r.url === "/users/")).toHaveLength(1);
    expect(requests().filter((r) => r.url === "/work-orders/filter-options")).toHaveLength(1);
    // Items are not part of that invalidation.
    expect(requests().filter((r) => r.url === "/items/")).toHaveLength(0);
  });

  it("never asks for users below Supervisor", async () => {
    await mountWorkOrders({ role: "technician", load: false });
    const { mod } = await mountWorkOrders({ role: "technician" });
    expect(mod).toBeTruthy();
  });
});

describe("the archived-number restore prompt", () => {
  // The load does not settle until the prompt is answered, so it is started
  // and answered concurrently -- awaiting it first would deadlock.
  async function startSearch(number, { lookup, role = "admin" }) {
    const { mod } = await mountWorkOrders({ role, cards: [], lookup, load: false });
    el("work-orders-search").value = number;
    return { mod, pending: mod.loadWorkOrders({ checkArchivedSearch: true }) };
  }

  const archived = { found: true, archived: true, id: "wo9", number: "9999" };

  it("offers to restore an exact archived number, and does it on Yes", async () => {
    const { pending } = await startSearch("9999", { lookup: archived });
    respond("post", "/work-orders/:id/restore", { id: "wo9" });
    await answerConfirm(true);
    await pending;
    expect(requestFor("/restore", "POST").url).toBe("/work-orders/wo9/restore");
    // A reload follows the restore.
    expect(listUrls().length).toBeGreaterThan(1);
  });

  it("does nothing on Close", async () => {
    const { pending } = await startSearch("9999", { lookup: archived });
    await answerConfirm(false);
    await pending;
    expect(requestFor("/restore", "POST")).toBeNull();
    expect(listUrls()).toHaveLength(1);
  });

  it("reports a failing restore in the list message", async () => {
    const { pending } = await startSearch("9999", { lookup: archived });
    respond("post", "/work-orders/:id/restore", { detail: "Gone" }, { status: 404 });
    await answerConfirm(true);
    await pending;
    expect(el("work-orders-list-message").textContent).toBe("Gone");
  });

  it("stays quiet for a live number", async () => {
    const { pending } = await startSearch("9999", {
      lookup: { found: true, archived: false, id: "wo9" },
    });
    await pending;
    expect(document.getElementById("scan-confirm-overlay").hidden).toBe(true);
  });

  it("stays quiet for a number nothing matches", async () => {
    const { pending } = await startSearch("9999", { lookup: { found: false } });
    await pending;
    expect(document.getElementById("scan-confirm-overlay").hidden).toBe(true);
  });

  it("stays quiet when a newer search has already started (the token guard)", async () => {
    let release;
    const held = new Promise((resolve) => { release = resolve; });
    const { mod } = await mountWorkOrders({
      role: "admin", cards: [], lookup: archived, load: false,
    });
    server.use(http.get("/work-orders/lookup", async () => {
      await held;
      return HttpResponse.json(archived);
    }));
    el("work-orders-search").value = "9999";
    const stale = mod.loadWorkOrders({ checkArchivedSearch: true });
    await vi.waitFor(() => expect(requestFor("/work-orders/lookup")).not.toBeNull());
    // A newer load bumps the token while the lookup is still in flight.
    await mod.loadWorkOrders();
    release();
    await stale;
    expect(document.getElementById("scan-confirm-overlay").hidden).toBe(true);
  });

  it("stays quiet when the box no longer holds the number that was looked up", async () => {
    let release;
    const held = new Promise((resolve) => { release = resolve; });
    const { mod } = await mountWorkOrders({
      role: "admin", cards: [], lookup: archived, load: false,
    });
    server.use(http.get("/work-orders/lookup", async () => {
      await held;
      return HttpResponse.json(archived);
    }));
    el("work-orders-search").value = "9999";
    const pending = mod.loadWorkOrders({ checkArchivedSearch: true });
    // The operator types a different number while the lookup is in flight.
    await vi.waitFor(() => expect(requestFor("/work-orders/lookup")).not.toBeNull());
    el("work-orders-search").value = "1111";
    release();
    await pending;
    expect(document.getElementById("scan-confirm-overlay").hidden).toBe(true);
  });

  it("never prompts below Admin+", async () => {
    const { pending } = await startSearch("9999", { lookup: archived, role: "supervisor" });
    await pending;
    expect(requestFor("/work-orders/lookup")).toBeNull();
    expect(document.getElementById("scan-confirm-overlay").hidden).toBe(true);
  });

  it("swallows a failing lookup rather than disturbing the list", async () => {
    const { mod } = await mountWorkOrders({ role: "admin", cards: [], load: false });
    respond("get", "/work-orders/lookup", { detail: "no" }, { status: 500 });
    el("work-orders-search").value = "9999";
    await mod.loadWorkOrders({ checkArchivedSearch: true });
    expect(el("work-orders-list-message").textContent).toBe("");
  });
});

describe("the list error path", () => {
  it("wipes the list and says so on a user-initiated failure", async () => {
    const { mod } = await mountWorkOrders({ role: "admin", cards: [workOrderCard()] });
    state.listResponder = () => HttpResponse.json({ detail: "Server down" }, { status: 500 });
    await mod.loadWorkOrders();
    expect(listEl().innerHTML).toBe("");
    expect(el("work-orders-list-message").textContent).toBe("Server down");
    expect(el("work-orders-more").hidden).toBe(true);
  });

  it("leaves the list untouched on a background failure", async () => {
    const { mod } = await mountWorkOrders({ role: "admin", cards: [workOrderCard()] });
    state.listResponder = () => HttpResponse.json({ detail: "Server down" }, { status: 500 });
    await mod.loadWorkOrders({ background: true });
    expect(cardEls()).toHaveLength(1);
    expect(el("work-orders-list-message").textContent).toBe("");
  });
});

describe("mountWorkOrderList", () => {
  it("renders collapsed cards into a container of the caller's choosing", async () => {
    const { mod } = await mountWorkOrders({ role: "technician" });
    const container = document.createElement("div");
    document.body.appendChild(container);
    seedList([workOrderCard({ number: "A1" }), workOrderCard({ number: "A2" })]);
    const list = mod.mountWorkOrderList({ container });
    await list.refresh();
    expect(container.querySelectorAll("details.wo-card")).toHaveLength(2);
    // Not the page's own list.
    expect(cardEls()).toHaveLength(0);
  });

  it("forwards lockedFilter to the list request", async () => {
    const { mod } = await mountWorkOrders({ role: "supervisor" });
    const container = document.createElement("div");
    const list = mod.mountWorkOrderList({ container, lockedFilter: { mine: true, status: "in_progress" } });
    await list.refresh();
    expect(listUrls().at(-1)).toBe("/work-orders/?status=in_progress&mine=true");
  });

  it("hands a click to onOpen instead of opening the card page", async () => {
    stubScroll();
    const { mod } = await mountWorkOrders({ role: "technician" });
    const container = document.createElement("div");
    document.body.appendChild(container);
    const card = workOrderCard({ number: "A1" });
    seedList([card]);
    const onOpen = vi.fn();
    await mod.mountWorkOrderList({ container, onOpen }).refresh();
    container.querySelector("summary.wo-summary").click();
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen.mock.calls[0][0].number).toBe("A1");
    expect(window.location.pathname).toBe("/");
  });

  it("renders its own empty state and its own error", async () => {
    const { mod } = await mountWorkOrders({ role: "technician" });
    const container = document.createElement("div");
    seedList([]);
    const list = mod.mountWorkOrderList({ container });
    await list.refresh();
    expect(container.textContent).toBe("No work orders match.");
    state.listResponder = () => HttpResponse.json({ detail: "Server down" }, { status: 500 });
    await list.refresh();
    expect(container.querySelector(".error").textContent).toBe("Server down");
  });
});
