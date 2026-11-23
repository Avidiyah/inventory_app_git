// Made-up records for the Mass Stage tutorials. Every id carries the reserved
// tutorial prefix ffffffff-ffff-4fff-8fff-, so a stray write cannot touch a
// real record. Maple Court bldg 12 is planning, bldg 14 is loading (one item
// short on the shelf), Cedar Row bldg 3 is completed.

export function sample(user) {
  const P = "ffffffff-ffff-4fff-8fff-";
  const id = (n) => P + "0000002300" + n;
  const at = "2026-11-20T12:00:00Z";
  const viewerName = user.full_name || "You";

  const stock = [
    [id("18"), "PH-LED60", "Philips 60W LED A19 Bulb", "2", "4.50"],
    [id("19"), "GE-OUTLET", "GE 15A Tamper-Resistant Outlet", "20", "1.75"],
    [id("20"), "SQD-BRKR", "Square D 20A Single-Pole Breaker", "50", "9.25"],
  ];
  const items = stock.map(([itemId, barcode, name, quantity, price]) => ({
    id: itemId, barcode, name, quantity, low_stock_threshold: 2, location: "Aisle 3",
    notes: {}, barcodes: [], price, product_link: null, created_at: at,
  }));
  const [bulb, outlet, breaker] = stock;

  const line = (lineId, [itemId, barcode, name, onHand], planned, loaded, returned) => ({
    id: lineId, item_id: itemId, item_name: name, item_barcode: barcode, item_quantity: onHand,
    planned_quantity: planned, loaded_quantity: loaded, returned_quantity: returned,
  });
  const slot = (slotId, woId, number, unit, status, order, assignee, lines) => ({
    id: slotId, work_order_id: woId, work_order_number: number, unit_number: unit, status,
    sort_order: order, assigned_to_id: assignee ? assignee[0] : null,
    assigned_to_name: assignee ? assignee[1] : null, items: lines,
  });
  const summary = (stageId, community, building, status, units, itemsCount) => ({
    id: stageId, community, building_name: building, status, unit_count: units,
    item_count: itemsCount, created_at: at,
  });
  const detail = (s, workOrders, merged) => ({
    id: s.id, community: s.community, building_name: s.building_name, status: s.status,
    created_at: at, work_orders: workOrders, merged_items: merged,
  });

  const wren = [id("21"), "Wren Alder"];
  const tobin = [id("22"), "Tobin Marsh"];

  const s1 = summary(id("01"), "Maple Court", "12", "planning", 1, 1);
  const s2 = summary(id("02"), "Maple Court", "14", "loading", 2, 2);
  const s3 = summary(id("03"), "Cedar Row", "3", "completed", 1, 1);

  const d1 = detail(s1, [
    slot(id("04"), id("08"), "880112", "101", "assigned", 0, wren, [line(id("12"), breaker, "2", "0", "0")]),
  ], []);
  const d2 = detail(s2, [
    slot(id("05"), id("09"), "880114", "201", "in_progress", 0, tobin, [
      line(id("13"), bulb, "4", "0", "0"), line(id("14"), outlet, "1", "1", "0")]),
    slot(id("06"), id("10"), "880115", "202", "assigned", 1, null, [
      line(id("15"), bulb, "2", "0", "0"), line(id("16"), outlet, "2", "0", "0")]),
  ], [
    { item_id: bulb[0], item_name: bulb[2], item_barcode: bulb[1], on_hand: "2", planned_total: "6",
      loaded_total: "0", returned_total: "0", overflow: "0", net_consumed: "0", remaining_to_load: "6" },
    { item_id: outlet[0], item_name: outlet[2], item_barcode: outlet[1], on_hand: "20", planned_total: "3",
      loaded_total: "1", returned_total: "0", overflow: "0", net_consumed: "1", remaining_to_load: "2" },
  ]);
  const d3 = detail(s3, [
    slot(id("07"), id("11"), "880103", "301", "assigned", 0, wren, [line(id("17"), breaker, "3", "3", "1")]),
  ], [
    { item_id: breaker[0], item_name: breaker[2], item_barcode: breaker[1], on_hand: "50", planned_total: "3",
      loaded_total: "3", returned_total: "1", overflow: "0", net_consumed: "2", remaining_to_load: "0" },
  ]);

  return {
    "GET /mass-stages/": [s1, s2, s3],
    [`GET /mass-stages/${s1.id}`]: d1,
    [`GET /mass-stages/${s2.id}`]: d2,
    [`GET /mass-stages/${s3.id}`]: d3,
    "GET /items/": items,
    "GET /users/": [
      { id: user.id, username: user.username, full_name: viewerName, first_name: user.first_name,
        last_name: user.last_name, role: user.role, created_at: user.created_at },
      { id: wren[0], username: "wren.alder", full_name: wren[1], first_name: "Wren", last_name: "Alder",
        role: "supervisor", created_at: at },
      { id: tobin[0], username: "tobin.marsh", full_name: tobin[1], first_name: "Tobin", last_name: "Marsh",
        role: "technician", created_at: at },
    ],
  };
}
