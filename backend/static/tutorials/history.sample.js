// Made-up records for the History tutorials. Every id carries the reserved
// tutorial prefix ffffffff-ffff-4fff-8fff-, so a stray write cannot touch a
// real record. Prices are shown to TechFM OA and above only, as the API does.

export function sample(user) {
  const P = "ffffffff-ffff-4fff-8fff-";
  const priced = ["owner", "admin", "techfm_oa"].includes(user.role);
  const viewerName = user.full_name || "You";
  const stock = [
    ["000000002401", "P-TRAP-15", "1-1/2 in. P-trap", "6.75"],
    ["000000002402", "SUPPLY-38", "3/8 in. braided supply line", "8.20"],
    ["000000002403", "TAPE-PTFE", "Thread seal tape", "1.10"],
  ];
  const items = stock.map(([id, barcode, name, price]) => ({
    id: P + id, barcode, name, quantity: "20", low_stock_threshold: 2, location: "Aisle 3",
    notes: {}, barcodes: [], price: priced ? price : null, product_link: null,
    created_at: "2026-11-01T12:00:00Z",
  }));
  const people = [
    { id: user.id, name: viewerName },
    { id: P + "000000002411", name: "Wren Alder" },
    { id: P + "000000002412", name: "Tobin Marsh" },
  ];
  // [type, item index, quantity, work order, reason, person index, price shown]
  const rows = [
    ["dispense", 0, "1", "SAMPLE-1", null, 0, false],
    ["stock", 1, "10", null, null, 1, true],
    ["dispense", 2, "2", "SAMPLE-2", null, 2, true],
    ["adjust", 0, "-1", null, "Recount: one was damaged", 1, true],
    ["stock", 0, "6", null, null, 2, true],
    ["dispense", 1, "1", "SAMPLE-1", null, 0, true],
    ["adjust", 2, "3", null, "Found a box on the shelf", 2, true],
    ["stock", 2, "12", null, null, 1, true],
    ["dispense", 0, "2", "SAMPLE-3", null, 0, true],
    ["stock", 1, "5", null, null, 2, true],
  ];
  const txns = rows.map(([type, i, qty, wo, reason, p, price], n) => ({
    id: P + "0000000024" + String(21 + n),
    item_id: items[i].id, item_barcode: items[i].barcode, item_name: items[i].name,
    user_id: people[p].id, user_name: people[p].name,
    transaction_type: type, quantity: qty, work_order_number: wo, work_order_id: null, reason,
    item_price: priced && price ? stock[i][3] : null, billable_quantity: null,
    created_at: `2026-11-${String(23 - n).padStart(2, "0")}T14:00:00Z`,
  }));
  return {
    "GET /transactions/": { items: txns, total: 25, page: 1, page_size: 10 },
    "GET /items/": items,
    "GET /users/": [
      { id: user.id, username: user.username, full_name: viewerName, first_name: user.first_name,
        last_name: user.last_name, role: user.role, created_at: user.created_at, archived_at: null },
      { id: people[1].id, username: "wren.alder", full_name: "Wren Alder", first_name: "Wren",
        last_name: "Alder", role: "technician", created_at: "2026-11-01T12:00:00Z", archived_at: null },
      { id: people[2].id, username: "tobin.marsh", full_name: "Tobin Marsh", first_name: "Tobin",
        last_name: "Marsh", role: "technician", created_at: "2026-10-01T12:00:00Z",
        archived_at: "2026-11-10T12:00:00Z" },
    ],
  };
}
