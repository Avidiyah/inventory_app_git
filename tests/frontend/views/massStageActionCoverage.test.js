// The thirteen Mass Stage `data-action` branches, audited the same way the
// Work Orders set is: rendered and handled must agree, the inventory is
// frozen, and massStage.test.js must name every one.
import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { auditActions, PAGES_DIR, VIEWS_DIR } from "../helpers/actionAudit.js";

const HERE = dirname(fileURLToPath(import.meta.url));

auditActions({
  name: "Mass Stage actions",
  sources: [join(VIEWS_DIR, "massStage.js")],
  fragments: [join(PAGES_DIR, "mass-stage.html")],
  frozen: [
    "add-item", "add-work-order", "complete-stage", "delete-stage", "edit-item", "load-item",
    "open-wo", "pick-item", "remove-item", "remove-slot", "return-item", "reuse-stage", "save-stage",
  ],
  behaviourDir: HERE,
  behaviourExclude: readdirSync(HERE).filter((f) => f !== "massStage.test.js"),
});
