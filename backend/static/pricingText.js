// Shared formatter for text pasted into the company's fixed-width receipt box.
// The destination hard-wraps at character 42, so every emitted line must fit
// within 41 characters. History and Admin Review both use these helpers so
// truncation, alignment, and sanitisation stay identical.

export const PRICING_LINE_WIDTH = 41;

// Shortest form of a Decimal-ish quantity for display ("3.00" -> "3").
export function formatPricingQuantity(quantity) {
  return String(Number(quantity));
}

// Tabs/newlines would break the one-row-per-line contract in the destination.
export function sanitisePricingText(value) {
  return String(value).replace(/[\t\r\n]+/g, " ");
}

// Build one <= 41-char line: "<qty> <name>...<price>" with the price flush
// right. When the name + price would overflow, the name is truncated with
// "...". The spacing is intentional: the pasted receipt aligns monetary
// values without depending on proportional-font layout.
export function pricingLine(quantity, nameValue, priceValue) {
  const qty = sanitisePricingText(quantity);
  const name = sanitisePricingText(nameValue);
  const price = sanitisePricingText(priceValue);
  const prefix = `${qty} `;
  const nameWidth = PRICING_LINE_WIDTH - prefix.length - price.length;
  if (nameWidth < 1) {
    return `${prefix}${price}`.slice(0, PRICING_LINE_WIDTH);
  }
  if (name.length <= nameWidth) {
    return prefix + name.padEnd(nameWidth) + price;
  }
  const cut = nameWidth - 3;
  const trimmed = cut > 0 ? name.slice(0, cut) + "..." : ".".repeat(nameWidth);
  return prefix + trimmed + price;
}

// Right-align an amount after a label, used for the final Total line.
export function pricingAmountLine(labelValue, priceValue) {
  const label = sanitisePricingText(labelValue);
  const price = sanitisePricingText(priceValue);
  const labelWidth = PRICING_LINE_WIDTH - price.length;
  if (labelWidth < 1) return price.slice(0, PRICING_LINE_WIDTH);
  if (label.length <= labelWidth) return label.padEnd(labelWidth) + price;
  const cut = labelWidth - 3;
  const trimmed = cut > 0 ? label.slice(0, cut) + "..." : ".".repeat(labelWidth);
  return trimmed + price;
}
