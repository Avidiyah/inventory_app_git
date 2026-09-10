import { describe, expect, it } from "vitest";
import {
  PRICING_LINE_WIDTH, formatPricingQuantity, pricingAmountLine, pricingLine, sanitisePricingText,
} from "../../../backend/static/pricingText.js";

describe("formatPricingQuantity", () => {
  it.each([["3.00", "3"], [3, "3"], ["2.50", "2.5"], [0, "0"]])(
    "shortens %o", (input, expected) => expect(formatPricingQuantity(input)).toBe(expected));
});

describe("sanitisePricingText", () => {
  it("collapses tabs and newlines into a single space", () => {
    expect(sanitisePricingText("a\t\tb\r\nc")).toBe("a b c");
  });
});

describe("pricingLine", () => {
  it("pads a short name so the price is flush right", () => {
    const line = pricingLine("3", "Bulb", "$4.50");
    expect(line).toHaveLength(PRICING_LINE_WIDTH);
    expect(line.startsWith("3 Bulb")).toBe(true);
    expect(line.endsWith("$4.50")).toBe(true);
  });

  it("truncates a long name with an ellipsis rather than overflowing", () => {
    const line = pricingLine("1", "X".repeat(80), "$1.00");
    expect(line).toHaveLength(PRICING_LINE_WIDTH);
    expect(line).toContain("...");
    expect(line.endsWith("$1.00")).toBe(true);
  });

  it("never exceeds the width, whatever it is given", () => {
    const cases = [
      ["1", "Bulb", "$1.00"],
      ["12.5", "A".repeat(200), "$1,234,567.89"],
      ["1", "", ""],
      ["1", "Bulb", "$".repeat(60)],
      ["1", "Tab\there", "NO PRICE"],
    ];
    for (const [qty, name, price] of cases) {
      expect(pricingLine(qty, name, price).length).toBeLessThanOrEqual(PRICING_LINE_WIDTH);
    }
  });

  it("drops the name entirely when the price alone fills the line", () => {
    expect(pricingLine("1", "Bulb", "$".repeat(60))).toHaveLength(PRICING_LINE_WIDTH);
  });
});

describe("pricingAmountLine", () => {
  it("right-aligns the amount after the label", () => {
    const line = pricingAmountLine("Total", "$12.00");
    expect(line).toHaveLength(PRICING_LINE_WIDTH);
    expect(line.startsWith("Total")).toBe(true);
    expect(line.endsWith("$12.00")).toBe(true);
  });

  it("truncates an over-long label", () => {
    const line = pricingAmountLine("L".repeat(80), "$1.00");
    expect(line).toHaveLength(PRICING_LINE_WIDTH);
    expect(line).toContain("...");
  });
});
