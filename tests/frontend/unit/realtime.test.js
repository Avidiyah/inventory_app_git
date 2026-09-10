import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installFakeWebSocket } from "../helpers/fakeSocket.js";

let realtime;
let ws;

beforeEach(async () => {
  vi.useFakeTimers();
  ws = installFakeWebSocket();
  realtime = await import("../../../backend/static/realtime.js");
});

afterEach(() => {
  realtime.disconnectRealtime();
  ws.restore();
  vi.useRealTimers();
});

const envelope = (type, id = "1") => JSON.stringify({ type, id, req: null });

describe("subscribe", () => {
  it("rejects a non-string event type and a non-function handler", () => {
    expect(() => realtime.subscribe("", () => {})).toThrow(TypeError);
    expect(() => realtime.subscribe("work_order", null)).toThrow(TypeError);
  });

  it("returns an unsubscribe that stops delivery", () => {
    const handler = vi.fn();
    const off = realtime.subscribe("work_order", handler);
    realtime.connectRealtime();
    ws.last().emitOpen();
    ws.last().emitMessage(envelope("work_order"));
    expect(handler).toHaveBeenCalledTimes(1);
    off();
    ws.last().emitMessage(envelope("work_order"));
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("delivers to every subscriber of the type, and to no other type", () => {
    const a = vi.fn();
    const b = vi.fn();
    const other = vi.fn();
    realtime.subscribe("work_order", a);
    realtime.subscribe("work_order", b);
    realtime.subscribe("item", other);
    realtime.connectRealtime();
    ws.last().emitOpen();
    ws.last().emitMessage(envelope("work_order"));
    expect(a).toHaveBeenCalledOnce();
    expect(b).toHaveBeenCalledOnce();
    expect(other).not.toHaveBeenCalled();
  });

  it("passes the envelope, the reason, and the active page", () => {
    realtime.setActivePageGetter(() => "work-orders");
    const handler = vi.fn();
    realtime.subscribe("work_order", handler);
    realtime.connectRealtime();
    ws.last().emitOpen();
    ws.last().emitMessage(envelope("work_order", "42"));
    expect(handler).toHaveBeenCalledWith({
      reason: "event",
      envelope: { type: "work_order", id: "42", req: null },
      activePage: "work-orders",
    });
  });

  it("survives a throwing subscriber and still calls the next one", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const good = vi.fn();
    realtime.subscribe("work_order", () => { throw new Error("boom"); });
    realtime.subscribe("work_order", good);
    realtime.connectRealtime();
    ws.last().emitOpen();
    ws.last().emitMessage(envelope("work_order"));
    expect(good).toHaveBeenCalled();
    expect(error).toHaveBeenCalled();
  });

  it("survives a rejecting async subscriber", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    realtime.subscribe("work_order", async () => { throw new Error("boom"); });
    realtime.connectRealtime();
    ws.last().emitOpen();
    ws.last().emitMessage(envelope("work_order"));
    await vi.waitFor(() => expect(error).toHaveBeenCalled());
  });
});

describe("setActivePageGetter", () => {
  it("rejects a non-function", () => {
    expect(() => realtime.setActivePageGetter("work-orders")).toThrow(TypeError);
  });

  it("reports a null active page when the getter throws", () => {
    realtime.setActivePageGetter(() => { throw new Error("boom"); });
    const handler = vi.fn();
    realtime.subscribe("work_order", handler);
    realtime.connectRealtime();
    ws.last().emitOpen();
    ws.last().emitMessage(envelope("work_order"));
    expect(handler.mock.calls[0][0].activePage).toBeNull();
  });
});

describe("envelope validation", () => {
  const handler = vi.fn();

  beforeEach(() => {
    handler.mockClear();
    realtime.subscribe("work_order", handler);
    realtime.connectRealtime();
    ws.last().emitOpen();
  });

  it.each([
    ["not JSON at all", "{oops"],
    ["a non-string payload", { type: "work_order" }],
    ["an array", JSON.stringify([1, 2, 3])],
    ["null", JSON.stringify(null)],
    ["a missing key", JSON.stringify({ type: "work_order", id: "1" })],
    ["an extra key", JSON.stringify({ type: "work_order", id: "1", req: null, extra: 1 })],
    ["a non-string type", JSON.stringify({ type: 3, id: "1", req: null })],
    ["an empty type", JSON.stringify({ type: "", id: "1", req: null })],
    ["a numeric id", JSON.stringify({ type: "work_order", id: 1, req: null })],
    ["a numeric req", JSON.stringify({ type: "work_order", id: "1", req: 2 })],
  ])("drops %s", (_label, data) => {
    ws.last().emitMessage(data);
    expect(handler).not.toHaveBeenCalled();
  });

  it("accepts null id and null req", () => {
    ws.last().emitMessage(JSON.stringify({ type: "work_order", id: null, req: null }));
    expect(handler).toHaveBeenCalledOnce();
  });
});

describe("connect and disconnect", () => {
  it("opens one socket at the ws(s) /ws URL", () => {
    realtime.connectRealtime();
    expect(ws.sockets).toHaveLength(1);
    expect(ws.last().url).toMatch(/^wss?:\/\/[^/]+\/ws$/);
  });

  it("is a no-op when already connected", () => {
    realtime.connectRealtime();
    realtime.connectRealtime();
    expect(ws.sockets).toHaveLength(1);
  });

  it("closes cleanly on disconnect and stops reconnecting", () => {
    realtime.connectRealtime();
    const socket = ws.last();
    socket.emitOpen();
    realtime.disconnectRealtime();
    expect(socket.closed).toEqual({ code: 1000, reason: "signed out" });
    socket.emitClose();
    vi.advanceTimersByTime(120000);
    expect(ws.sockets).toHaveLength(1);
  });
});

describe("reconnect", () => {
  it("schedules a retry after an unexpected close", () => {
    realtime.connectRealtime();
    ws.last().emitOpen();
    ws.last().emitClose();
    expect(ws.sockets).toHaveLength(1);
    // Unpinned jitter puts the first retry in [500, 1000), so 1000 always fires it.
    vi.advanceTimersByTime(1000);
    expect(ws.sockets).toHaveLength(2);
  });

  it("backs off exponentially, capped at 30s, with a non-zero floor", () => {
    // Equal jitter: delay is in [ceiling/2, ceiling), where ceiling is
    // min(30000, 1000 * 2 ** min(attempt, 10)) and the first attempt is 0.
    // Pinning Math.random to 0 gives ceiling/2 -- these exact values were
    // measured against the real module, not derived on paper.
    vi.spyOn(Math, "random").mockReturnValue(0);
    realtime.connectRealtime();
    const expected = [500, 1000, 2000, 4000, 8000, 15000, 15000];
    for (const delay of expected) {
      ws.last().emitClose();
      const before = ws.sockets.length;
      vi.advanceTimersByTime(delay - 1);
      expect(ws.sockets).toHaveLength(before);
      vi.advanceTimersByTime(1);
      expect(ws.sockets).toHaveLength(before + 1);
    }
  });

  it("resets the ladder after a successful open", () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    realtime.connectRealtime();
    ws.last().emitClose();
    vi.advanceTimersByTime(500);
    ws.last().emitOpen();
    ws.last().emitClose();
    // Back to the bottom of the ladder: 500 again, not 1000.
    vi.advanceTimersByTime(500);
    expect(ws.sockets).toHaveLength(3);
  });

  it("notifies every subscriber once on recovery, whatever their event type", () => {
    const a = vi.fn();
    const b = vi.fn();
    realtime.subscribe("work_order", a);
    realtime.subscribe("item", b);
    realtime.connectRealtime();
    ws.last().emitOpen();
    a.mockClear();
    b.mockClear();
    ws.last().emitClose();
    vi.advanceTimersByTime(30000);
    ws.last().emitOpen();
    expect(a).toHaveBeenCalledWith({ reason: "reconnect", envelope: null, activePage: null });
    expect(b).toHaveBeenCalledOnce();
  });

  it("does not fire a recovery refresh on the first ever open", () => {
    const handler = vi.fn();
    realtime.subscribe("work_order", handler);
    realtime.connectRealtime();
    ws.last().emitOpen();
    expect(handler).not.toHaveBeenCalled();
  });

  it("closes the socket on error, letting close drive the single retry path", () => {
    realtime.connectRealtime();
    const socket = ws.last();
    socket.emitOpen();
    socket.emitError();
    expect(socket.readyState).toBe(3);
  });

  it("retries when the constructor itself throws", async () => {
    realtime.disconnectRealtime();
    ws.restore();
    ws = installFakeWebSocket({ throwOnConstruct: true });
    realtime.connectRealtime();
    ws.restore();
    const live = installFakeWebSocket();
    vi.advanceTimersByTime(30000);
    expect(live.sockets.length).toBeGreaterThan(0);
    live.restore();
  });

  it("ignores messages from a socket belonging to a stale generation", () => {
    const handler = vi.fn();
    realtime.subscribe("work_order", handler);
    realtime.connectRealtime();
    const stale = ws.last();
    stale.emitOpen();
    realtime.disconnectRealtime();
    realtime.connectRealtime();
    stale.emitMessage(envelope("work_order"));
    expect(handler).not.toHaveBeenCalled();
  });
});
