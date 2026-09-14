// The Low Stock card delegates `data-action` clicks off `#low-stock-list`
// (lowStockCard.js); lowStock.js itself wires the threshold input by class
// and has no delegation table. Default patterns, P2's four checks.
import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { auditActions, VIEWS_DIR } from "../helpers/actionAudit.js";

const HERE = dirname(fileURLToPath(import.meta.url));

auditActions({
  name: "Low Stock card actions",
  sources: [join(VIEWS_DIR, "lowStockCard.js")],
  frozen: ["add-barcode", "remove-barcode", "save-correction", "save-item"],
  behaviourDir: HERE,
  // Only lowStockCard.test.js may satisfy the check: itemEditor.test.js and
  // the Items audit mention "remove-barcode" for the Saved Items editor.
  behaviourExclude: readdirSync(HERE).filter((f) => f !== "lowStockCard.test.js"),
});
