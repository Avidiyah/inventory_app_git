// Factories, not fixture files: every field gets a sane default and the test
// overrides only what it is asserting on. Adding a field to the API shape is
// then one edit here, not one per test.

let seq = 0;

export function user(overrides = {}) {
  seq += 1;
  return {
    id: seq,
    username: `user${seq}`,
    full_name: `Test User ${seq}`,
    first_name: "Test",
    last_name: `User ${seq}`,
    role: "technician",
    ...overrides,
  };
}

// Complete, valid payloads with a sane default for every field the response
// model declares. Tests override only the field under test, so a test stays
// readable when the API shape grows a column.
//
// Shapes are read off backend/app/schemas/*.py -- ItemResponse,
// WorkOrderDetail (WorkOrderCard + detail fields) and TransactionResponse --
// and guarded by the drift test in unit/api.endpoints.test.js. A drifting
// factory produces green tests over a broken app.
//
// Ids are UUID strings, not integers: every id column on these three models is
// a UUID, and a numeric id would let a test pass a shape the app never sees.
let uuidSeq = 0;
const uuid = () => {
  uuidSeq += 1;
  return `00000000-0000-4000-8000-${String(uuidSeq).padStart(12, "0")}`;
};

// Decimals arrive as JSON strings (Pydantic serialises Decimal that way), so
// the money and quantity fields are strings here too.
export function item(overrides = {}) {
  return {
    id: uuid(),
    barcode: "B1",
    name: "Bulb",
    quantity: "10",
    low_stock_threshold: 0,
    location: "A1",
    notes: {},
    barcodes: [],
    price: "2.50",
    product_link: null,
    created_at: "2026-09-10T12:00:00Z",
    ...overrides,
  };
}

export function workOrder(overrides = {}) {
  return {
    id: uuid(),
    number: "12345",
    community: "Maple Ridge",
    building_number: "3",
    unit_number: "12",
    description: "Replace hallway bulb",
    priority: "normal",
    status: "Assigned",
    entry_mode: "imported",
    created_by_id: null,
    assigned_to_id: null,
    assigned_to_name: null,
    assigned_to_ids: [],
    assigned_to_names: [],
    item_count: 0,
    location: "Hallway",
    output_to: null,
    vendor_assignee: null,
    service_type: "Electrical",
    schedule_date: null,
    supervisor_id: null,
    supervisor_name: null,
    legacy: false,
    // WorkOrderDetail adds these to the card.
    notes: null,
    items: [],
    labor: [],
    active_labor_session: null,
    tracking_technician_ids: [],
    materials_total: "0.00",
    labor_minutes: 0,
    labor_billed_minutes: 0,
    labor_rate: "62.50",
    labor_total: "0.00",
    ...overrides,
  };
}

export function transaction(overrides = {}) {
  return {
    id: uuid(),
    item_id: uuid(),
    user_id: uuid(),
    transaction_type: "out",
    quantity: "1",
    billable_quantity: null,
    work_order_number: null,
    reason: null,
    created_at: "2026-09-10T12:00:00Z",
    recount_required: false,
    item_quantity: "9",
    ...overrides,
  };
}

// --- Work order card / detail -------------------------------------------
//
// `workOrder()` above is the single all-in-one shape P1 verified. P2 splits
// it in two because the list and the card body are different responses:
// `GET /work-orders/` answers WorkOrderCard rows, `GET /work-orders/{id}`
// answers a WorkOrderDetail. A test that seeds a detail into the list (or a
// card into the body) passes over code paths production never takes.
//
// Fields are read off backend/app/schemas/work_orders.py and guarded by the
// drift test in unit/api.endpoints.test.js.

export function workOrderCard(overrides = {}) {
  return {
    id: uuid(),
    number: "12345",
    community: null,
    building_number: null,
    unit_number: null,
    description: "Replace hallway bulb",
    priority: "Normal",
    status: "assigned",
    entry_mode: "dispense",
    created_by_id: null,
    assigned_to_id: null,
    assigned_to_name: null,
    assigned_to_ids: [],
    assigned_to_names: [],
    item_count: 0,
    location: "Hallway",
    output_to: null,
    vendor_assignee: null,
    service_type: "Electrical",
    schedule_date: "2026-09-10",
    supervisor_id: null,
    supervisor_name: null,
    legacy: false,
    ...overrides,
  };
}

// Cost fields default to a number rather than null: `null` is the *redacted*
// (below TechFM OA) case, which has its own tests, and defaulting to it would
// make every money assertion pass by rendering nothing.
export function workOrderDetail(overrides = {}) {
  return {
    ...workOrderCard(),
    notes: null,
    items: [],
    labor: [],
    active_labor_session: null,
    tracking_technician_ids: [],
    materials_total: "0.00",
    labor_minutes: 0,
    labor_billed_minutes: 0,
    labor_rate: "62.50",
    labor_total: "0.00",
    ...overrides,
  };
}

export function workOrderItem(overrides = {}) {
  return {
    id: uuid(),
    item_id: uuid(),
    item_name: "Bulb",
    item_barcode: "B1",
    item_quantity: "9",
    quantity: "1",
    mode: "dispense",
    unit_price: "2.50",
    billable_quantity: null,
    ...overrides,
  };
}

export function workOrderLabor(overrides = {}) {
  return {
    id: uuid(),
    technician_id: uuid(),
    technician_name: "Test User",
    minutes: 90,
    session_window: null,
    auto_closed: false,
    ...overrides,
  };
}

export function filterOptions(overrides = {}) {
  return {
    service_types: ["Electrical", "Plumbing"],
    priorities: ["Normal", "Urgent"],
    supervisors: [],
    communities: [],
    ...overrides,
  };
}

// --- User Hub ------------------------------------------------------------
//
// `GET /hub`. Shape read off backend/app/schemas/hub.py (HubResponse), which
// is the payload `loadUserHub` destructures before it renders anything --
// `payload.user.id` and `payload.user.role` decide which tabs even exist, so
// an empty object here would fail every boot rather than render an empty hub.
//
// `total_minutes_today` is a Pydantic computed field, not a stored one; it is
// present on the wire, so it is present here.
export function hubPayload(overrides = {}) {
  return {
    user: { id: uuid(), first_name: "Test", last_name: "User", role: "technician" },
    server_now: "2026-09-10T12:00:00Z",
    day: "2026-09-10",
    clock: {
      running_session: null,
      closed_minutes_today: 0,
      running_minutes_today: 0,
      adjustment_minutes_today: 0,
      adjustments: [],
      total_minutes_today: 0,
    },
    timeline: [],
    mine_total: 0,
    counts: { assigned: 0, in_progress: 0, ready_to_complete: 0 },
    priority: { assigned: 0, unassigned: null },
    startable: [],
    tools_out: [],
    stocked_requests: [],
    ...overrides,
  };
}

// --- Hub sub-shapes (backend/app/schemas/hub.py) ----------------------------
// The rows hubPayload() defaults to empty lists or null. One wire row each;
// a test passes them through hubPayload({ timeline: [hubTimelineEntry()] }).
export function hubRunningSession(overrides = {}) {
  return {
    work_order_id: uuid(), number: "7001",
    started_at: "2026-09-10T11:00:00Z", day_counting_from: "2026-09-10T11:00:00Z",
    ...overrides,
  };
}

export function hubAdjustment(overrides = {}) {
  return { minutes: 30, recorded_by_name: "Sue Super", work_order_number: "7001", ...overrides };
}

export function hubTimelineEntry(overrides = {}) {
  return {
    work_order_id: uuid(), number: "7001", started_at: "2026-09-10T13:00:00Z",
    ended_at: "2026-09-10T14:00:00Z", auto_closed: false, minutes: 60,
    ...overrides,
  };
}

export function hubStartable(overrides = {}) {
  return {
    work_order_id: uuid(), number: "7001", status: "assigned",
    community: null, building_number: null, unit_number: null, location: null,
    ...overrides,
  };
}

export function hubToolOut(overrides = {}) {
  return { tool_id: uuid(), name: "Drill", barcode: "T1", quantity: "1", since: "2026-09-08T12:00:00Z", ...overrides };
}

export function hubStockedRequest(overrides = {}) {
  return {
    request_id: uuid(), item_name: "Bulb", work_order_id: uuid(), work_order_number: "7001",
    quantity: "2", stocked_at: "2026-09-10T11:30:00Z",
    ...overrides,
  };
}

// --- History rows --------------------------------------------------------
//
// GET /transactions/ answers TransactionHistoryItem rows (a JOIN across
// transactions / items / users), not TransactionResponse. `item_price` and
// `billable_quantity` are present only for TechFM OA and above; the factory
// defaults them to the privileged shape and a role test nulls them.
export function historyRow(overrides = {}) {
  return {
    id: uuid(),
    item_id: uuid(),
    item_barcode: "B1",
    item_name: "Bulb",
    user_id: uuid(),
    user_name: "Test User",
    transaction_type: "dispense",
    quantity: "2",
    work_order_number: "7001",
    work_order_id: null,
    reason: null,
    item_price: "2.50",
    billable_quantity: null,
    created_at: "2026-09-10T12:00:00Z",
    ...overrides,
  };
}

// --- Hub sub-payloads (backend/app/schemas/hub.py) --------------------------
// Minimal-but-valid: one technician on the crew board, one community in the
// graphs, one row in the timesheet. Tests override the field under test.
export function hubCrew(overrides = {}) {
  return {
    server_now: "2026-09-10T12:00:00Z",
    led: { total: 1, in_progress: 1, ready_to_complete: 0 },
    priority: { assigned: 0, unassigned: 0 },
    crew_on_clock: 0,
    crew_total: 1,
    crew_minutes_today: 0,
    technicians: [{
      user: { id: uuid(), first_name: "Crew", last_name: "One", role: "technician" },
      running_session: null, minutes_today: 0, assigned: 1, in_progress: 0, ready_to_complete: 0,
      last_worked: null, flags: [],
    }],
    attention: [],
    ...overrides,
  };
}

export function hubAdmin(overrides = {}) {
  return {
    server_now: "2026-09-10T12:00:00Z",
    supervisor_minutes_today: 0,
    technician_minutes_today: 0,
    pipeline: { created: 0, assigned: 0, in_progress: 0, ready_to_complete: 0, completed: 0, review: 0 },
    priority: { assigned: 0, unassigned: 0 },
    on_the_clock: [],
    exceptions: { inventory_recounts: 0, missing_item_price: 0, catalogue_requests: 0, admin_review_queue: 0, stale_work_orders: 0 },
    billing: { materials_total: "0", labor_total: "0", total: "0", avg_days_to_complete: null, completed_per_day: [0, 0, 0, 0, 0, 0, 0], legacy_live_count: null },
    ...overrides,
  };
}

export function hubTimesheets(overrides = {}) {
  return {
    range: { start: "2026-09-07", end: "2026-09-13" },
    rows: [{ user: { id: uuid(), first_name: "Crew", last_name: "One", role: "technician" }, days: [], total_minutes: 0 }],
    crew_totals_by_day: [],
    ...overrides,
  };
}

export function hubGraphs(overrides = {}) {
  return {
    generated_at: "2026-09-10T12:00:00Z",
    weeks: 12,
    statuses: [{ key: "assigned", label: "Assigned" }],
    communities: [{ key: "maple", label: "Maple Ridge", total: 1, counts: { assigned: 1 }, service_types: [], priorities: [] }],
    duration: { range: { start: "2026-06-18", end: "2026-09-10" }, buckets: [] },
    ...overrides,
  };
}

// --- Mass stage (backend/app/schemas/mass_stages.py) ------------------------
export function stageItem(overrides = {}) {
  return {
    id: uuid(), item_id: uuid(), item_name: "Bulb", item_barcode: "B1",
    item_quantity: "10", planned_quantity: "2", loaded_quantity: "0", returned_quantity: "0",
    ...overrides,
  };
}

export function stageWorkOrder(overrides = {}) {
  return {
    id: uuid(), work_order_id: uuid(), work_order_number: "7001", unit_number: "12",
    status: "assigned", sort_order: 0, assigned_to_id: null, assigned_to_name: null, items: [],
    ...overrides,
  };
}

export function mergedItem(overrides = {}) {
  return {
    item_id: uuid(), item_name: "Bulb", item_barcode: "B1", on_hand: "10",
    planned_total: "4", loaded_total: "0", returned_total: "0", overflow: "0",
    net_consumed: "0", remaining_to_load: "4",
    ...overrides,
  };
}

export function massStageSummary(overrides = {}) {
  return {
    id: uuid(), community: "Scholars", building_name: "19", status: "planning",
    unit_count: 0, item_count: 0, created_at: "2026-09-10T12:00:00Z",
    ...overrides,
  };
}

export function massStageDetail(overrides = {}) {
  return {
    id: uuid(), community: "Scholars", building_name: "19", status: "planning",
    created_at: "2026-09-10T12:00:00Z", work_orders: [], merged_items: [],
    ...overrides,
  };
}
