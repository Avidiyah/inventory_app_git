// tutorial:end clears a sample scanning batch (reserved id prefix) and leaves
// a real batch alone.

import { afterEach, describe, expect, it } from "vitest";
import { workOrderCard } from "../helpers/factories.js";
import { BATCH_KEY, el, inBatch, restoreTransactions } from "../helpers/transactions.js";

afterEach(restoreTransactions);

describe("tutorial:end on the transaction page", () => {
  it("resets a sample batch", async () => {
    const wo = workOrderCard({ id: "ffffffff-ffff-4fff-8fff-000000000011", number: "SAMPLE-11", status: "in_progress" });
    await inBatch({ wo });
    document.dispatchEvent(new CustomEvent("tutorial:end"));
    expect(el.gate().hidden).toBe(false);
    expect(el.active().hidden).toBe(true);
    expect(sessionStorage.getItem(BATCH_KEY)).toBeNull();
  });

  it("leaves a real batch running", async () => {
    await inBatch();
    document.dispatchEvent(new CustomEvent("tutorial:end"));
    expect(el.active().hidden).toBe(false);
    expect(sessionStorage.getItem(BATCH_KEY)).not.toBeNull();
  });
});
