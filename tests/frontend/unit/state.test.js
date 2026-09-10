import { beforeEach, describe, expect, it, vi } from "vitest";

// Imported per test: state.js is a module singleton, and the point of half
// these tests is that setup.js's resetModules actually isolates it.
let state;
beforeEach(async () => {
  state = await import("../../../backend/static/state.js");
});

describe("cache accessors", () => {
  it.each([
    ["Items", [{ id: 1 }]],
    ["Users", [{ id: 2 }]],
    ["Tools", [{ id: 3 }]],
  ])("round-trips %s", (name, value) => {
    state[`set${name}`](value);
    expect(state[`get${name}`]()).toEqual(value);
  });

  it("starts every cache empty", () => {
    expect(state.getItems()).toEqual([]);
    expect(state.getUsers()).toEqual([]);
    expect(state.getTools()).toEqual([]);
  });

  it("returns the same array reference it was given", () => {
    // Views rely on this -- the items view mutates the cached array in place.
    const rows = [{ id: 1 }];
    state.setItems(rows);
    expect(state.getItems()).toBe(rows);
  });
});

describe("editing ids", () => {
  it("default to null and round-trip", () => {
    expect(state.getEditingItemId()).toBeNull();
    expect(state.getEditingNotesItemId()).toBeNull();
    state.setEditingItemId(4);
    state.setEditingNotesItemId(5);
    expect(state.getEditingItemId()).toBe(4);
    expect(state.getEditingNotesItemId()).toBe(5);
  });
});

describe("current user", () => {
  it("starts null and exposes the role through getRole", () => {
    expect(state.getCurrentUser()).toBeNull();
    expect(state.getRole()).toBeNull();
    state.setCurrentUser({ id: 1, role: "supervisor" });
    expect(state.getRole()).toBe("supervisor");
  });

  it("is not persisted to localStorage -- a reload must re-check /auth/me", () => {
    state.setCurrentUser({ id: 1, role: "owner" });
    expect(localStorage.length).toBe(0);
  });
});

describe("history state", () => {
  it("has the documented defaults", () => {
    expect(state.getHistoryState()).toEqual({
      tab: "all", itemId: null, itemLabel: null, userId: null, workOrder: null,
      dateFrom: null, dateTo: null, page: 1, totalPages: 1,
    });
    expect(state.HISTORY_PAGE_SIZE).toBe(10);
  });

  it("returns a copy, so a caller cannot mutate it by reference", () => {
    const snapshot = state.getHistoryState();
    snapshot.page = 99;
    expect(state.getHistoryState().page).toBe(1);
  });

  it("shallow-merges a patch and leaves the rest alone", () => {
    state.updateHistoryState({ page: 3, workOrder: "WO-1" });
    state.updateHistoryState({ page: 4 });
    expect(state.getHistoryState()).toMatchObject({ page: 4, workOrder: "WO-1", tab: "all" });
  });
});

describe("isolation", () => {
  it("does not leak into the next module generation", async () => {
    state.setItems([{ id: 1 }]);
    state.setCurrentUser({ id: 1, role: "owner" });
    state.updateHistoryState({ page: 7 });
    vi.resetModules();
    const fresh = await import("../../../backend/static/state.js");
    expect(fresh.getItems()).toEqual([]);
    expect(fresh.getCurrentUser()).toBeNull();
    expect(fresh.getHistoryState().page).toBe(1);
  });
});

describe("setTestUser", () => {
  it("primes the same module generation the test reads", async () => {
    const { setTestUser } = await import("../helpers/session.js");
    await setTestUser({ role: "admin" });
    const current = await import("../../../backend/static/state.js");
    expect(current.getRole()).toBe("admin");
  });
});
