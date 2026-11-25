// Made-up records for the work-order tutorials. Every id carries the reserved
// tutorial prefix ffffffff-ffff-4fff-8fff-, so a stray write cannot touch a
// real record. The viewer is put on the crew of SAMPLE-1.

export function sample(user) {
  const P = "ffffffff-ffff-4fff-8fff-";
  const viewerName = user.full_name || "You";
  const card = (id, number, status, extra) => ({
    id: P + id, number, community: "Sample Village", building_number: "4", unit_number: "12",
    description: "Kitchen sink is leaking under the cabinet", priority: "Normal", status,
    entry_mode: "dispense", created_by_id: null, assigned_to_id: null, assigned_to_name: null,
    assigned_to_ids: [], assigned_to_names: [], item_count: 0, location: "Kitchen",
    output_to: null, vendor_assignee: null, service_type: "Plumbing", schedule_date: "2026-11-23",
    supervisor_id: null, supervisor_name: null, legacy: false, ...extra,
  });
  const detail = (c, extra) => ({
    ...c, notes: null, items: [], labor: [], active_labor_session: null, prior_work: null,
    tracking_technician_ids: [], materials_total: "0.00", labor_minutes: 0, labor_billed_minutes: 0,
    labor_rate: "62.50", labor_total: "0.00", signature: null, smr_target: null, smr_paper_check: null,
    smr_stage: null, smr_ready: null, smr_readings: [], smr_lines: [], smr_legacy_labor_minutes: 0,
    smr_block: null, takeoff: [], ...extra,
  });
  const stock = [
    ["000000000101", "P-TRAP-15", "1-1/2 in. P-trap", "6.75"],
    ["000000000102", "SUPPLY-38", "3/8 in. braided supply line", "8.20"],
    ["000000000103", "TAPE-PTFE", "Thread seal tape", "1.10"],
  ];
  const items = stock.map(([id, barcode, name, price]) => ({
    id: P + id, barcode, name, quantity: "20", low_stock_threshold: 2, location: "Aisle 3",
    notes: {}, barcodes: [], price, product_link: null, created_at: "2026-11-01T12:00:00Z",
  }));
  const lines = stock.map(([id, barcode, name, price], i) => ({
    id: P + "00000000020" + (i + 1), item_id: P + id, item_name: name, item_barcode: barcode,
    item_quantity: "19", quantity: "1", mode: "dispense", unit_price: price, billable_quantity: null,
  }));
  const lead = { id: P + "000000220001", name: "Wren Alder" };
  const tobin = { id: P + "000000220003", name: "Tobin Marsh" };
  const one = card("000000000001", "SAMPLE-1", "in_progress",
    { assigned_to_ids: [user.id, tobin.id], assigned_to_names: [viewerName, tobin.name], item_count: 3,
      supervisor_id: lead.id, supervisor_name: lead.name });
  const two = card("000000000002", "SAMPLE-2", "created",
    { description: "Hallway light is out", service_type: "Electrical", location: "Hallway" });
  const three = card("000000000003", "SAMPLE-3", "ready_to_complete",
    { description: "Bathroom fan is noisy", service_type: "Electrical", location: "Bathroom",
      assigned_to_ids: [tobin.id], assigned_to_names: [tobin.name],
      supervisor_id: lead.id, supervisor_name: lead.name });
  return {
    "GET /work-orders/": [one, two, three],
    [`GET /work-orders/${one.id}`]: detail(one, {
      notes: "Shut-off valve under the sink is stiff.\nNew trap fitted; check for drips tomorrow.",
      items: lines, materials_total: "16.05", labor_minutes: 930, labor_billed_minutes: 930, labor_total: "968.75",
      labor: [{ id: P + "000000000301", technician_id: user.id, technician_name: viewerName, minutes: 150,
        session_window: null, auto_closed: false, hand_entered: false, week_open: true, recorded_by_self: false },
      { id: P + "000000220005", technician_id: tobin.id, technician_name: tobin.name, minutes: 720,
        session_window: "Nov 20, 6:00 AM - 6:00 PM", auto_closed: true, hand_entered: false, week_open: true,
        recorded_by_self: false },
      { id: P + "000000220006", technician_id: tobin.id, technician_name: tobin.name, minutes: 60,
        session_window: null, auto_closed: false, hand_entered: true, week_open: true, recorded_by_self: false }],
    }),
    [`GET /work-orders/${two.id}`]: detail(two),
    [`GET /work-orders/${three.id}`]: detail(three),
    [`GET /work-orders/${one.id}/requests`]: [],
    [`GET /work-orders/${two.id}/requests`]: [],
    [`GET /work-orders/${three.id}/requests`]: [],
    "GET /work-orders/filter-options": {
      service_types: ["Electrical", "Plumbing"], priorities: ["Normal", "Urgent"], supervisors: [], communities: ["Sample Village"],
    },
    "GET /items/": items,
    "GET /users/": [
      { id: user.id, username: user.username, full_name: viewerName, first_name: user.first_name,
        last_name: user.last_name, role: user.role, created_at: user.created_at },
      { id: P + "000000000401", username: "sample.tech", full_name: "Sam Sample", first_name: "Sam",
        last_name: "Sample", role: "technician", created_at: "2026-11-01T12:00:00Z" },
      { id: lead.id, username: "wren.alder", full_name: lead.name, first_name: "Wren",
        last_name: "Alder", role: "supervisor", created_at: "2026-11-01T12:00:00Z" },
      { id: P + "000000220002", username: "ila.brandt", full_name: "Ila Brandt", first_name: "Ila",
        last_name: "Brandt", role: "admin", created_at: "2026-11-01T12:00:00Z" },
      { id: tobin.id, username: "tobin.marsh", full_name: tobin.name, first_name: "Tobin",
        last_name: "Marsh", role: "technician", created_at: "2026-11-01T12:00:00Z" },
      { id: P + "000000220004", username: "odell.rusk", full_name: "Odell Rusk", first_name: "Odell",
        last_name: "Rusk", role: "technician", created_at: "2026-11-01T12:00:00Z" },
    ],
  };
}
