// views/hubLive.js: coalesced feeds (W7 rule 6) and the event → feed routing
// (rules 4, 7). The routing through the real hub is in userHub.test.js.

import { afterEach, describe, expect, it, vi } from "vitest";
import { importView } from "../helpers/shell.js";
import { clearRequests } from "../helpers/requests.js";
import { queries, connectHub, openHub, restoreHub, stopClock } from "../helpers/hub.js";

const deferred = () => {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
};

describe("createFeed", () => {
  it("coalesces a burst into two fetches", async () => {
    const { createFeed } = await importView("views/hubLive.js");
    const first = deferred();
    const fetcher = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue("b");
    const onData = vi.fn();
    const feed = createFeed(fetcher, onData);
    const runs = Array.from({ length: 20 }, () => feed.run({ background: true }));
    first.resolve("a");
    await Promise.all(runs);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(onData.mock.calls.map((c) => c[0])).toEqual(["a", "b"]);
  });

  it("skips when the predicate is false", async () => {
    const { createFeed } = await importView("views/hubLive.js");
    const fetcher = vi.fn().mockResolvedValue(1);
    await createFeed(fetcher, () => {}, { when: () => false }).run();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("reset discards an in-flight result", async () => {
    const { createFeed } = await importView("views/hubLive.js");
    const pending = deferred();
    const onData = vi.fn();
    const feed = createFeed(() => pending.promise, onData);
    const run = feed.run();
    feed.reset();
    pending.resolve("stale");
    await run;
    expect(onData).not.toHaveBeenCalled();
  });

  it("a foreground run queued behind a background one reports its error", async () => {
    const { createFeed } = await importView("views/hubLive.js");
    const first = deferred();
    const fetcher = vi.fn().mockReturnValueOnce(first.promise).mockRejectedValue(new Error("x"));
    const onError = vi.fn();
    const feed = createFeed(fetcher, () => {}, { onError });
    const a = feed.run({ background: true });
    feed.run({ background: false });
    first.resolve(1);
    await a;
    expect(onError).toHaveBeenCalledWith(expect.any(Error), { background: false });
  });
});

describe("routing", () => {
  afterEach(() => {
    stopClock();
    restoreHub();
  });

  it("attendance.changed runs the attendance feed for a technician", async () => {
    await openHub({ role: "technician" });
    const { emit } = await connectHub();
    clearRequests();
    emit("attendance.changed");
    await vi.waitFor(() => expect(queries("/attendance/me")).toHaveLength(1));
  });

  it("the timer does nothing while the document is hidden", async () => {
    await openHub({ role: "admin" });
    stopClock();
    clearRequests();
    await vi.advanceTimersByTimeAsync(120000);
    expect(queries("/hub")).toHaveLength(0);
  });
});
