import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";

let tp;
let gets;
let puts;

const row = (key, completed = false) => ({
  key, seen_at: "2026-11-23T10:00:00Z", completed_at: completed ? "2026-11-23T10:05:00Z" : null,
});

function serve(rows, { putStatus = 204 } = {}) {
  server.use(
    http.get("/tutorials/progress/me", () => { gets += 1; return HttpResponse.json(rows); }),
    http.put("/tutorials/progress/:key", async ({ params, request }) => {
      puts.push([params.key, (await request.json()).event]);
      return new HttpResponse(null, { status: putStatus });
    }),
  );
}

const flush = () => new Promise((r) => setTimeout(r, 20));

beforeEach(async () => {
  gets = 0;
  puts = [];
  tp = await import("../../../backend/static/tutorialProgress.js");
});

afterEach(() => vi.restoreAllMocks());

describe("tutorialProgress", () => {
  it("loads me once and reads the cache", async () => {
    serve([row("a"), row("b", true)]);
    await tp.loadProgress();
    await tp.loadProgress();
    expect(gets).toBe(1);
    expect(tp.hasSeen("a")).toBe(true);
    expect(tp.isDone("a")).toBe(false);
    expect(tp.isDone("b")).toBe(true);
    expect(tp.hasSeen("zzz")).toBe(false);
  });

  it("mark flips the cache before the PUT resolves; completed implies seen", async () => {
    serve([]);
    tp.mark("k.a", "completed");
    expect(tp.isDone("k.a")).toBe(true);
    expect(tp.hasSeen("k.a")).toBe(true);
    expect(puts).toEqual([]);
    await flush();
    expect(puts).toEqual([["k.a", "completed"]]);
  });

  it("repeating a true state sends nothing", async () => {
    serve([]);
    tp.mark("k", "seen");
    tp.mark("k", "seen");
    tp.mark("k", "completed");
    tp.mark("k", "completed");
    tp.mark("k", "seen");
    await flush();
    expect(puts).toEqual([["k", "seen"], ["k", "completed"]]);
  });

  it("a failed PUT is logged and the cache stays", async () => {
    serve([], { putStatus: 500 });
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    tp.mark("k", "completed");
    await flush();
    expect(log).toHaveBeenCalled();
    expect(tp.isDone("k")).toBe(true);
  });

  it("a failed GET is logged and leaves the cache empty", async () => {
    server.use(http.get("/tutorials/progress/me", () => new HttpResponse(null, { status: 500 })));
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    await tp.loadProgress();
    expect(log).toHaveBeenCalled();
    expect(tp.hasSeen("a")).toBe(false);
  });

  it("clearProgress empties the cache and allows a refetch", async () => {
    serve([row("a")]);
    await tp.loadProgress();
    tp.clearProgress();
    expect(tp.hasSeen("a")).toBe(false);
    await tp.loadProgress();
    expect(gets).toBe(2);
    expect(tp.hasSeen("a")).toBe(true);
  });

  it("a load resolving after a clear does not repopulate", async () => {
    serve([row("a")]);
    const pending = tp.loadProgress();
    tp.clearProgress();
    await pending;
    expect(tp.hasSeen("a")).toBe(false);
  });

  it("onChange fires on load, mark and clear, and unsubscribes", async () => {
    serve([row("a")]);
    const fn = vi.fn();
    const off = tp.onChange(fn);
    await tp.loadProgress();
    expect(fn).toHaveBeenCalledTimes(1);
    tp.mark("b", "seen");
    expect(fn).toHaveBeenCalledTimes(2);
    tp.clearProgress();
    expect(fn).toHaveBeenCalledTimes(3);
    off();
    tp.mark("c", "seen");
    expect(fn).toHaveBeenCalledTimes(3);
    await flush();
  });
});
