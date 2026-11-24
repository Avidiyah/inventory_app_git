// static/messagesStore.js: one fetch in flight plus one rerun, refetch on
// `message.changed` and on reconnect, and nothing left in memory after stop.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { importView } from "../helpers/shell.js";
import { connectFakeRealtime } from "../helpers/realtime.js";
import { conversation } from "../helpers/messages.js";

let rt = null;
let store = null;

afterEach(() => {
  store?.stopMessages();
  rt?.disconnect();
  vi.useRealTimers();
  rt = null;
  store = null;
});

const settle = () => new Promise((r) => setTimeout(r, 0));

// The list endpoint, counting calls. `hold()` makes the next responses wait.
function serve(rows = [conversation({ id: "c1", name: "Ana" })], unread = 2) {
  const api = { calls: 0, gate: null, rows, unread };
  api.hold = () => {
    let release;
    api.gate = new Promise((r) => { release = r; });
    api.release = () => { api.gate = null; release(); };
  };
  server.use(http.get("/messages/conversations", async () => {
    api.calls += 1;
    if (api.gate) await api.gate;
    return HttpResponse.json({ conversations: api.rows, unread_people: api.unread });
  }));
  return api;
}

async function load(api) {
  rt = await connectFakeRealtime("hub");
  store = await importView("messagesStore.js");
  await store.startMessages();
  return api;
}

describe("messagesStore", () => {
  it("start fetches once and fills the state", async () => {
    const api = await load(serve());
    expect(api.calls).toBe(1);
    expect(store.getState().conversations.map((c) => c.id)).toEqual(["c1"]);
    expect(store.getState().unreadPeople).toBe(2);
  });

  it("an envelope refetches and listeners get the conversation id", async () => {
    const api = await load(serve());
    const listener = vi.fn();
    store.onChange(listener);
    rt.emit("message.changed", { id: "c1" });
    await vi.waitFor(() => expect(listener).toHaveBeenCalledWith({ conversationId: "c1" }));
    expect(api.calls).toBe(2);
  });

  it("a listener that throws does not stop the others", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    await load(serve());
    const good = vi.fn();
    store.onChange(() => { throw new Error("boom"); });
    store.onChange(good);
    await store.refresh();
    expect(good).toHaveBeenCalledWith({ conversationId: null });
  });

  it("five envelopes in a burst cause at most two fetches", async () => {
    const api = await load(serve());
    api.hold();
    for (let i = 0; i < 5; i += 1) rt.emit("message.changed", { id: "c1" });
    api.release();
    await settle();
    await settle();
    expect(api.calls).toBe(3); // the start fetch + one in flight + one rerun
  });

  it("a reconnect refetches", async () => {
    const api = await load(serve());
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    rt.reconnect();
    await vi.advanceTimersByTimeAsync(2000);
    rt.ws.last().emitOpen();
    await vi.waitFor(() => expect(api.calls).toBe(2));
  });

  it("after stop the state is empty, a late response is ignored, and an envelope fetches nothing", async () => {
    const api = await load(serve());
    api.hold();
    const pending = store.refresh();
    const listener = vi.fn();
    store.stopMessages();
    store.onChange(listener);
    expect(store.getState()).toEqual({ conversations: [], unreadPeople: 0 });
    api.release();
    await pending;
    expect(store.getState()).toEqual({ conversations: [], unreadPeople: 0 });
    expect(listener).not.toHaveBeenCalled();

    const before = api.calls;
    rt.emit("message.changed", { id: "c1" });
    await settle();
    expect(api.calls).toBe(before);
  });

  it("stop notifies listeners and clears what the first person had", async () => {
    await load(serve());
    const listener = vi.fn();
    store.onChange(listener);
    store.stopMessages();
    expect(listener).toHaveBeenCalledWith({ conversationId: null });
    expect(store.getState().conversations).toEqual([]);
  });
});
