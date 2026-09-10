import { describe, expect, it } from "vitest";
import { PRICING_LINE_WIDTH } from "../../../backend/static/pricingText.js";
import { billedLaborHours, buildAdminReviewReceipt } from "../../../backend/static/adminReviewReceipt.js";

describe("billedLaborHours", () => {
  it.each([[60, "1"], [90, "1.5"], [1, "0.02"], [0, "0"], [null, "0"], ["120", "2"]])(
    "converts %o minutes", (minutes, expected) => expect(billedLaborHours(minutes)).toBe(expected));
});

describe("buildAdminReviewReceipt", () => {
  const detail = {
    items: [
      { item_name: "Bulb", quantity: 2, billable_quantity: null, unit_price: "10.00" },
      { item_name: "Fuse", quantity: 5, billable_quantity: 1, unit_price: "2.00" },
    ],
    labor_billed_minutes: 90,
    labor_total: 75,
    materials_total: 22,
  };

  it("bills the billable quantity when one is set, the recorded one otherwise", () => {
    const { text } = buildAdminReviewReceipt(detail);
    const [bulb, fuse] = text.split("\n");
    expect(bulb.startsWith("2 Bulb")).toBe(true);
    expect(fuse.startsWith("1 Fuse")).toBe(true);
  });

  it("applies the 15% markup to materials but not to labor", () => {
    const { text } = buildAdminReviewReceipt(detail);
    expect(text).toContain("$23.00"); // 2 x 10.00 x 1.15
    expect(text).toContain("$2.30");  // 1 x 2.00 x 1.15
    expect(text).toContain("$75.00"); // labor, unmarked
  });

  it("totals marked materials plus labor", () => {
    // 22 x 1.15 = 25.30, + 75 = 100.30
    expect(buildAdminReviewReceipt(detail).text).toContain("$100.30");
  });

  it("labels the labor line with the billed hours in brackets", () => {
    expect(buildAdminReviewReceipt(detail).text).toContain("[1.5] Labor Hours");
  });

  it("flags a missing price without dropping the line", () => {
    const result = buildAdminReviewReceipt({
      ...detail,
      items: [{ item_name: "Mystery", quantity: 1, billable_quantity: null, unit_price: null }],
    });
    expect(result.missingPrices).toEqual(["Mystery"]);
    expect(result.text).toContain("NO PRICE");
    expect(result.text).toContain("Total (incomplete)");
  });

  it("handles an empty work order", () => {
    const result = buildAdminReviewReceipt({ items: [], labor_billed_minutes: 0, labor_total: 0, materials_total: 0 });
    expect(result.missingPrices).toEqual([]);
    expect(result.text).toContain("Total");
  });

  it("keeps every emitted line inside the receipt width", () => {
    const wide = buildAdminReviewReceipt({
      ...detail,
      items: [{ item_name: "N".repeat(120), quantity: 1000, billable_quantity: null, unit_price: "9999.99" }],
    });
    for (const line of wide.text.split("\n")) {
      expect(line.length).toBeLessThanOrEqual(PRICING_LINE_WIDTH);
    }
  });
});
