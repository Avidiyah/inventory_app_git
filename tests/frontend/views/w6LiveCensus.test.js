// W6 census: the live patch pairs cards and tiles by id, so every one of them
// on the three pages needs a unique id of the agreed form, and every Low Stock
// field must sit inside a card that has one and draw with its server value as
// its default (a value set by `.value` would look typed and never update).

import { afterEach, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { mountView } from "../helpers/shell.js";
import { setTestUser } from "../helpers/session.js";
import { lowStockItem, workOrderCard } from "../helpers/factories.js";
import { cards as lowStockCards, mountLowStock, restoreLowStock } from "../helpers/lowStock.js";
import { isDirty } from "../../../backend/static/morph.js";

afterEach(() => restoreLowStock());

const unique = (ids) => new Set(ids).size === ids.length;

it("every Low Stock card carries a unique low-stock-card id", async () => {
  const rows = ["a", "b", "c"].map((id) => lowStockItem({ id, barcodes: ["ALT"], price: "1.50" }));
  await mountLowStock({ rows });
  const ids = lowStockCards().map((card) => card.id);
  expect(ids).toEqual(rows.map((row) => `low-stock-card-${row.id}`));
  expect(unique(ids)).toBe(true);
});

it("every Low Stock field sits in a card with an id and draws clean", async () => {
  await mountLowStock({ rows: [lowStockItem({ id: "a", barcodes: ["ALT"], price: "1.50", product_link: "https://example.com/p" })] });
  const fields = [...document.getElementById("low-stock-list").querySelectorAll("input, select, textarea")];
  expect(fields.length).toBeGreaterThan(0);
  for (const field of fields) {
    expect(field.closest(".low-stock-card")?.id, field.className).toMatch(/^low-stock-card-/);
    expect(isDirty(field), field.className).toBe(false);
  }
});

it("every Admin Review tile carries a unique review-card id", async () => {
  const seeded = ["a", "b", "c"].map((id) => workOrderCard({ id, status: "review" }));
  server.use(http.get("/work-orders/", () => HttpResponse.json(seeded)));
  await setTestUser({ role: "admin" });
  const mod = await mountView("views/adminReview.js");
  await mod.loadAdminReview();
  const ids = [...document.querySelectorAll("#admin-review-list .admin-review-card")].map((t) => t.id);
  expect(ids).toEqual(seeded.map((card) => `review-card-${card.id}`));
  expect(unique(ids)).toBe(true);
});

it("every SMR Admin Review tile carries a unique smr-review-card id", async () => {
  const tiles = ["a", "b", "c"].map((id) => ({
    id, number: id, stage: "ready", archived_at: null, lines: { block_version: 1 },
  }));
  server.use(http.get("/work-orders/smr", () => HttpResponse.json({ tiles })));
  await setTestUser({ role: "admin" });
  const mod = await mountView("views/smrAdminReview.js");
  await mod.loadSmrAdminReview();
  const ids = [...document.querySelectorAll("#smr-admin-review-list .admin-review-card")].map((t) => t.id);
  expect(ids).toEqual(tiles.map((tile) => `smr-review-card-${tile.id}`));
  expect(unique(ids)).toBe(true);
});
