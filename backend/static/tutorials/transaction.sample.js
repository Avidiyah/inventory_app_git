// Made-up records for the transaction tutorials. Every id carries the reserved
// tutorial prefix ffffffff-ffff-4fff-8fff-. SAMPLE-11 is the one the tutorial
// taps; SAMPLE-13 is never tapped (a tap would ask to start it and write).

export function sample(user) {
  const P = "ffffffff-ffff-4fff-8fff-";
  const viewerName = user.full_name || "You";
  const card = (id, number, status, unit, assignee) => ({
    id: P + id, number, community: "Sample Village", building_number: "4", unit_number: unit,
    description: "Kitchen sink is leaking under the cabinet", priority: "Normal", status,
    entry_mode: "dispense", created_by_id: null,
    assigned_to_id: assignee ? user.id : null, assigned_to_name: assignee ? viewerName : null,
    assigned_to_ids: assignee ? [user.id] : [], assigned_to_names: assignee ? [viewerName] : [],
    item_count: 0, location: "Kitchen", output_to: null, vendor_assignee: null,
    service_type: "Plumbing", schedule_date: "2026-11-23", supervisor_id: null, supervisor_name: null,
    legacy: false,
  });
  const stock = [
    ["000000000021", "P-TRAP-15", "1-1/2 in. P-trap", "6.75", "Aisle 3"],
    ["000000000022", "SUPPLY-38", "3/8 in. braided supply line", "8.20", "Aisle 3"],
    ["000000000023", "TAPE-PTFE", "Thread seal tape", "1.10", "Aisle 4"],
  ];
  return {
    "GET /work-orders/": [
      card("000000000011", "SAMPLE-11", "in_progress", "11", true),
      card("000000000012", "SAMPLE-12", "in_progress", "12", true),
      card("000000000013", "SAMPLE-13", "assigned", "13", false),
    ],
    "GET /items/": stock.map(([id, barcode, name, price, location]) => ({
      id: P + id, barcode, name, quantity: "20", low_stock_threshold: 2, location,
      notes: {}, barcodes: [], price, product_link: null, created_at: "2026-11-01T12:00:00Z",
    })),
  };
}
