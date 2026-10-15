// Items delegates on its themed Actions menu (menus.js `initActionMenus`), so "rendered" is an <option value>,
// not a data-action. Same guarantee as the Work Orders audit, different regex.
import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { auditActions, VIEWS_DIR } from "../helpers/actionAudit.js";

const HERE = dirname(fileURLToPath(import.meta.url));

auditActions({
  name: "Items row actions",
  sources: [join(VIEWS_DIR, "items.js")],
  frozen: ["correct", "delete", "edit", "label", "notes", "threshold"],
  behaviourDir: HERE,
  // Only items.test.js may satisfy the check; the other view files in this
  // directory mention "delete" and "edit" for their own reasons.
  behaviourExclude: readdirSync(HERE).filter((f) => f !== "items.test.js"),
  // Each menu option is a `{ value, label }` object handed to actionMenuHtml.
  renderedPattern: /\{ value: "([a-z-]+)", label:/g,
});
