// Made-up items for the Find Item tutorials. Every id carries the reserved tutorial
// prefix ffffffff-ffff-4fff-8fff-, so a stray write cannot touch a real record.
// ...11 to ...13 feed the office scripts (notes, extra barcode, unpriced);
// ...21 to ...24 are the plain lookup rows.

export function sample(user) {
  const P = "ffffffff-ffff-4fff-8fff-";
  // The real route nulls price and product_link below TechFM OA (_item_response).
  const seesCost = ["techfm_oa", "admin", "owner"].includes(user.role);
  const ago = (days) => new Date(Date.now() - days * 86400000).toISOString();
  const row = (id, barcode, name, quantity, location, extra = {}) => ({
    id: P + id, barcode, name, quantity, low_stock_threshold: 2, location, notes: {}, barcodes: [],
    created_at: ago(30), ...extra,
    price: seesCost ? (extra.price ?? null) : null,
    product_link: seesCost ? (extra.product_link ?? null) : null,
  });
  const link = "https://example.com/products/sample";
  return {
    "GET /items/": [
      row("000000000021", "SAMP-0021", "Acme 1-1/2 in. P-Trap Kit", "24", "Aisle 3, Bin 2", { price: "6.75", product_link: link }),
      row("000000000022", "SAMP-0022", "Brightline 3/8 in. Braided Supply Line", "40", "Aisle 3, Bin 5", { price: "8.20", product_link: link }),
      row("000000000023", "SAMP-0023", "Northfield Thread Seal Tape", "60", "Aisle 4, Shelf 1", { price: "1.10", product_link: link }),
      row("000000000024", "SAMP-0024", "Halo LED Bulb 60W Equivalent", "18", "Aisle 6, Shelf 2", { price: "2.50", product_link: link }),
      row("000000000011", "SAMP-0011", "Acme 3 in. Deck Screws", "12", "Aisle 1, Bin 4",
        { notes: { Size: "3 in", Pack: 100 }, price: "9.40", product_link: link, created_at: ago(20) }),
      row("000000000012", "SAMP-0012", "Brightline Door Hinge Set", "8", "Aisle 2, Bin 1",
        { barcodes: ["SAMP-0012-PKG"], price: "4.85", product_link: link, created_at: ago(15) }),
      row("000000000013", "SAMP-0013", "Northfield Caulk Gun", "5", "Aisle 5, Shelf 3", { created_at: ago(10) }),
    ],
  };
}
