// W6: the shared helper both review pages use to refetch the selected order
// on a live event and decide what happened to it.

import { describe, expect, it, vi } from "vitest";
import { coalesce, refreshSelected } from "../../../backend/static/views/reviewLiveDetail.js";

const shown = { id: "w1", number: "5001", text: "old" };

function run(overrides = {}) {
  const calls = {
    fetchDetail: vi.fn(async () => ({ ...shown })),
    repaint: vi.fn(),
    markGone: vi.fn(),
  };
  const options = {
    getSelected: () => shown,
    isStale: () => false,
    inQueue: () => true,
    signature: (d) => d.text,
    ...calls,
    ...overrides,
  };
  return { result: refreshSelected(options), options };
}

describe("refreshSelected", () => {
  it("an unchanged order repaints nothing", async () => {
    const { result, options } = run();
    expect(await result).toBe("same");
    expect(options.fetchDetail).toHaveBeenCalledWith("w1");
    expect(options.repaint).not.toHaveBeenCalled();
    expect(options.markGone).not.toHaveBeenCalled();
  });

  it("a changed order repaints once with the fresh detail", async () => {
    const fresh = { ...shown, text: "new" };
    const { result, options } = run({ fetchDetail: vi.fn(async () => fresh) });
    expect(await result).toBe("changed");
    expect(options.repaint).toHaveBeenCalledTimes(1);
    expect(options.repaint).toHaveBeenCalledWith(fresh);
    expect(options.markGone).not.toHaveBeenCalled();
  });

  it("an order that left the queue is marked gone, not repainted", async () => {
    const fresh = { ...shown, text: "new" };
    const { result, options } = run({ fetchDetail: vi.fn(async () => fresh), inQueue: () => false });
    expect(await result).toBe("gone");
    expect(options.markGone).toHaveBeenCalledWith(fresh);
    expect(options.repaint).not.toHaveBeenCalled();
  });

  it("a 404 is gone", async () => {
    const { result, options } = run({ fetchDetail: vi.fn(async () => { throw { status: 404 }; }) });
    expect(await result).toBe("gone");
    expect(options.markGone).toHaveBeenCalledWith(null);
  });

  it("any other failure is skipped and touches nothing", async () => {
    const { result, options } = run({ fetchDetail: vi.fn(async () => { throw { status: 500 }; }) });
    expect(await result).toBe("skipped");
    expect(options.repaint).not.toHaveBeenCalled();
    expect(options.markGone).not.toHaveBeenCalled();
  });

  it.each([
    ["a changed order", async () => ({ ...shown, text: "new" })],
    ["a 404", async () => { throw { status: 404 }; }],
  ])("a newer selection wins over %s", async (_, fetchDetail) => {
    const { result, options } = run({ fetchDetail: vi.fn(fetchDetail), isStale: () => true });
    expect(await result).toBe("skipped");
    expect(options.repaint).not.toHaveBeenCalled();
    expect(options.markGone).not.toHaveBeenCalled();
  });

  it("no selection means no fetch", async () => {
    const { result, options } = run({ getSelected: () => null });
    expect(await result).toBe("skipped");
    expect(options.fetchDetail).not.toHaveBeenCalled();
  });
});

describe("coalesce", () => {
  it("runs once at a time, with one rerun queued behind it", async () => {
    let release;
    const gate = new Promise((r) => { release = r; });
    const work = vi.fn(() => gate);
    const go = coalesce(work);
    const first = go();
    go();
    go();
    expect(work).toHaveBeenCalledTimes(1);
    release();
    await first;
    expect(work).toHaveBeenCalledTimes(2);
    await go();
    expect(work).toHaveBeenCalledTimes(3);
  });
});
