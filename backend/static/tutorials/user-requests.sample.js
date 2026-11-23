// Made-up requests for the User Requests tutorials. Every id carries the
// reserved tutorial prefix. The page does not filter the list by tab, so one
// body answers every tab and shows all four cards.

export function sample() {
  const P = "ffffffff-ffff-4fff-8fff-";
  const ago = (hours) => new Date(Date.now() - hours * 3600 * 1000).toISOString();
  const requester = { id: P + "000000000401", name: "Sam Sample" };
  const request = (n, extra) => ({
    id: P + "0000000000" + n, request_type: "material_request", status: "open", message: "",
    item_id: null, item_name: null, item_barcode: null, item_price: null, item_product_link: null,
    item_quantity: null, transaction_id: null, work_order_id: null, work_order_number: null,
    created_by_id: requester.id, created_by_name: requester.name, details: {},
    created_at: ago(3), resolved_at: null, resolved_by_id: null, resolved_by_name: null,
    resolution_note: null, work_order_archived: false, skipped: [], updated: false, ...extra,
  });
  return {
    "GET /user-requests/counts": {
      material_request: { open: 1 },
      catalogue_request: { open: 1 },
      inventory_recount: { open: 1 },
      missing_item_price: { open: 1 },
    },
    "GET /user-requests/": [
      request("41", {
        request_type: "material_request", message: "Need more 1-1/2 in. P-traps",
        item_id: P + "000000000101", item_name: "1-1/2 in. P-trap", item_barcode: "P-TRAP-15",
        item_price: "6.75", item_quantity: "0", work_order_id: P + "000000000001", work_order_number: "SAMPLE-1",
        details: { quantity: "4", product_link: null, note: "Shelf looked empty this morning" },
      }),
      request("42", {
        request_type: "catalogue_request", message: "No catalogue row for this part",
        work_order_id: P + "000000000002", work_order_number: "SAMPLE-2",
        details: { searched_text: "Garbage disposal flange", quantity: "2", note: "Brushed nickel" },
      }),
      request("43", {
        request_type: "inventory_recount", message: "Dispense came up short",
        item_id: P + "000000000102", item_name: "3/8 in. braided supply line", item_barcode: "SUPPLY-38",
        item_quantity: "1", work_order_id: P + "000000000001", work_order_number: "SAMPLE-1",
        details: { recorded_quantity_before: "2", dispensed_quantity: "3", shortage_quantity: "1" },
      }),
      request("44", {
        request_type: "missing_item_price", message: "Material used with no price",
        item_id: P + "000000000103", item_name: "Thread seal tape", item_barcode: "TAPE-PTFE",
        work_order_id: P + "000000000001", work_order_number: "SAMPLE-1",
        details: { work_order_numbers: ["SAMPLE-1"] },
      }),
    ],
  };
}
