// Pure Admin Review receipt builder. Kept separate from the DOM-bound view so
// the billing text can be checked directly and every emitted line inherits the
// same 41-character contract as History.

import { formatMoney } from "./format.js";
import {
  formatPricingQuantity,
  pricingAmountLine,
  pricingLine,
} from "./pricingText.js";

const MARKUP_RATE = 1.15;

function effectiveBillable(item) {
  return item.billable_quantity === null || item.billable_quantity === undefined
    ? Number(item.quantity)
    : Number(item.billable_quantity);
}

export function billedLaborHours(minutes) {
  const hours = (Number(minutes) || 0) / 60;
  return String(Number(hours.toFixed(2)));
}

export function buildAdminReviewReceipt(detail) {
  const lines = [];
  const missingPrices = [];

  for (const item of detail.items || []) {
    const quantity = effectiveBillable(item);
    if (item.unit_price === null || item.unit_price === undefined) {
      missingPrices.push(item.item_name);
      lines.push(pricingLine(
        formatPricingQuantity(quantity),
        item.item_name,
        "NO PRICE"
      ));
      continue;
    }
    const markedCharge = quantity * Number(item.unit_price) * MARKUP_RATE;
    lines.push(pricingLine(
      formatPricingQuantity(quantity),
      item.item_name,
      formatMoney(markedCharge)
    ));
  }

  const laborTotal = Number(detail.labor_total) || 0;
  lines.push(pricingLine(
    `[${billedLaborHours(detail.labor_billed_minutes)}]`,
    "Labor Hours",
    formatMoney(laborTotal)
  ));

  const markedMaterials = (Number(detail.materials_total) || 0) * MARKUP_RATE;
  const total = markedMaterials + laborTotal;
  lines.push("", pricingAmountLine(
    missingPrices.length ? "Total (incomplete)" : "Total",
    formatMoney(total)
  ));

  return { text: lines.join("\n"), missingPrices };
}
