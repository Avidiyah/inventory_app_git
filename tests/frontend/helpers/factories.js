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
