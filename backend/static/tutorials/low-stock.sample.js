// Made-up records for the Low Stock tutorial. Every id carries the reserved
// tutorial prefix ffffffff-ffff-4fff-8fff-. One row lands in each recency tab.

export function sample() {
  const P = "ffffffff-ffff-4fff-8fff-";
  const ago = (ms) => new Date(Date.now() - ms).toISOString();
  const HOUR = 60 * 60 * 1000;
  const row = (id, barcode, name, quantity, threshold, used, last, extra) => ({
    id: P + id, barcode, name, quantity, low_stock_threshold: threshold, location: "Aisle 3",
    notes: {}, barcodes: [], price: "6.75", product_link: null, created_at: ago(90 * 24 * HOUR),
    dispensed_last_7_days: used, last_dispensed_at: last, ...extra,
  });
  return {
    "GET /items/low-stock": [
      row("000000000051", "P-TRAP-15", "1-1/2 in. P-trap", "2", 5, "6", ago(2 * HOUR),
        { barcodes: ["P-TRAP-15-BAG"], product_link: "https://example.com/p-trap" }),
      row("000000000052", "SUPPLY-38", "3/8 in. braided supply line", "1", 4, "3", ago(72 * HOUR),
        { price: "8.20" }),
      row("000000000053", "TAPE-PTFE", "Thread seal tape", "0", 3, "0", null, { price: "1.10" }),
    ],
  };
}
