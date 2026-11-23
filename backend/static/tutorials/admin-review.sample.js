// Made-up Review orders for the Admin Review tutorial. Every id carries the
// reserved tutorial prefix. ...61 is fully priced; ...62 has an unpriced item.

export function sample() {
  const P = "ffffffff-ffff-4fff-8fff-";
  const today = new Date().toISOString().slice(0, 10);
  const card = (id, number, extra) => ({
    id: P + id, number, community: "Sample Village", building_number: "4", unit_number: "12",
    description: "Kitchen sink is leaking under the cabinet", priority: "Normal", status: "review",
    entry_mode: "dispense", created_by_id: null, assigned_to_id: null, assigned_to_name: null,
    assigned_to_ids: [P + "000000000401"], assigned_to_names: ["Sam Sample"], item_count: 2,
    location: "Kitchen", output_to: null, vendor_assignee: null, service_type: "Plumbing",
    schedule_date: today, supervisor_id: null, supervisor_name: null, legacy: false, ...extra,
  });
  const detail = (c, extra) => ({
    ...c, notes: null, items: [], labor: [], active_labor_session: null, prior_work: null,
    tracking_technician_ids: [], materials_total: "0.00", labor_minutes: 0, labor_billed_minutes: 0,
    labor_rate: "62.50", labor_total: "0.00", signature: null, smr_target: null, smr_paper_check: null,
    smr_stage: null, smr_ready: null, smr_readings: [], smr_lines: [], smr_legacy_labor_minutes: 0,
    smr_block: null, ...extra,
  });
  const line = (id, itemId, barcode, name, qty, price) => ({
    id: P + id, item_id: P + itemId, item_name: name, item_barcode: barcode, item_quantity: "19",
    quantity: qty, mode: "dispense", unit_price: price, billable_quantity: null,
  });
  const labor = (id) => ({
    id: P + id, technician_id: P + "000000000401", technician_name: "Sam Sample", minutes: 150,
    session_window: null, auto_closed: false, hand_entered: false, week_open: false, recorded_by_self: false,
  });
  const priced = card("000000000061", "SAMPLE-61");
  const unpriced = card("000000000062", "SAMPLE-62",
    { description: "Hallway light is out", service_type: "Electrical", location: "Hallway", has_unpriced_items: true });
  return {
    "GET /work-orders/": [priced, unpriced],
    [`GET /work-orders/${priced.id}`]: detail(priced, {
      items: [
        line("000000000201", "000000000101", "P-TRAP-15", "1-1/2 in. P-trap", "1", "6.75"),
        line("000000000202", "000000000102", "SUPPLY-38", "3/8 in. braided supply line", "2", "8.20"),
      ],
      materials_total: "23.15", labor_minutes: 150, labor_billed_minutes: 150, labor_total: "156.25",
      labor: [labor("000000000301")],
    }),
    [`GET /work-orders/${unpriced.id}`]: detail(unpriced, {
      items: [line("000000000203", "000000000103", "BULB-A19", "LED bulb, A19", "1", null)],
      materials_total: "0.00", labor_minutes: 60, labor_billed_minutes: 60, labor_total: "62.50",
      labor: [labor("000000000302")],
    }),
  };
}
