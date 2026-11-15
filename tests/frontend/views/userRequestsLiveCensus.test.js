// W5 census: the live patch pairs cards by id and keeps only typed fields, so
// every card needs a unique id and every field outside a panel must draw with
// its server value as its default (a prefilled value set by `.value` would
// look typed and never update).

import { expect, it } from "vitest";
import { importView } from "../helpers/shell.js";
import { userRequest } from "../helpers/factories.js";

const TYPES = {
  material_request: ["open", "stocked", "resolved"],
  catalogue_request: ["open", "resolved"],
  inventory_recount: ["open", "resolved"],
  missing_item_price: ["open", "resolved"],
};
const DETAILS = {
  material_request: { quantity: "2", product_link: null, note: null },
  catalogue_request: { searched_text: "Flux capacitor", quantity: "1", note: null },
  inventory_recount: { recorded_quantity_before: "5", dispensed_quantity: "3", shortage_quantity: "2" },
  missing_item_price: { work_order_numbers: ["12345"] },
};

const all = () => Object.entries(TYPES).flatMap(([type, statuses]) => statuses.map((status) =>
  userRequest({
    request_type: type, status, details: DETAILS[type],
    item_price: "12.5", item_product_link: "https://example.com/p",
  })));

it("every card carries a unique ureq-card id", async () => {
  const { buildRequestCard } = await importView("views/userRequestCards.js");
  const requests = all();
  const ids = requests.map((r) => buildRequestCard(r).id);
  expect(ids).toEqual(requests.map((r) => `ureq-card-${r.id}`));
  expect(new Set(ids).size).toBe(ids.length);
});

it("every field outside a panel draws clean, with the server value as its default", async () => {
  const { buildRequestCard } = await importView("views/userRequestCards.js");
  const { isDirty } = await import("../../../backend/static/morph.js");
  for (const request of all()) {
    const card = buildRequestCard(request);
    const fields = [...card.querySelectorAll("input, select, textarea")]
      .filter((f) => !f.closest(".user-request-panel"));
    for (const field of fields) expect(isDirty(field), `${request.request_type} ${field.className}`).toBe(false);
  }
});

it("an open missing-price card prefills price and link by attribute", async () => {
  const { buildRequestCard } = await importView("views/userRequestCards.js");
  const card = buildRequestCard(all().find((r) => r.request_type === "missing_item_price" && r.status === "open"));
  expect(card.querySelector(".user-request-price-input").defaultValue).toBe("12.5");
  expect(card.querySelector(".user-request-link-input").defaultValue).toBe("https://example.com/p");
});
