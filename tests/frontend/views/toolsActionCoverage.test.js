// Tools delegates on its themed Actions menu (menus.js `initActionMenus`), like Items, so "rendered" is an
// <option value>. Unlike Items it guards the last branch with
// `action !== "delete"` rather than an equality, which the default
// `handledPattern` does not match -- hence the widened regex here.
import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { auditActions, VIEWS_DIR } from "../helpers/actionAudit.js";

const HERE = dirname(fileURLToPath(import.meta.url));

// Only this chunk's four files may satisfy the behaviour check; every other
// view file in this directory mentions "edit", "correct" and "delete" for its
// own reasons.
const OURS = [
  "toolsCustody.test.js", "toolsCheckout.test.js",
  "toolsInventory.test.js", "toolsScan.test.js",
];

auditActions({
  name: "Tools row actions",
  sources: [join(VIEWS_DIR, "tools.js")],
  frozen: ["correct", "delete", "edit"],
  behaviourDir: HERE,
  behaviourExclude: readdirSync(HERE).filter((f) => !OURS.includes(f)),
  // Each menu option is a `{ value, label }` object handed to actionMenuHtml.
  renderedPattern: /\{ value: "([a-z-]+)", label:/g,
  handledPattern: /action (?:===|!==) "([a-z-]+)"/g,
});
