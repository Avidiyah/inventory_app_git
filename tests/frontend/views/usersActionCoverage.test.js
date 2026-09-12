// Users delegates on a click over class names, not on `data-action` or an
// <option value> — the roadmap's "delegated-action views" wording assumed
// `data-action`, and `auditActions` takes custom patterns for exactly this
// (P6 deviation 6). "Rendered" is the first class of a button whose name ends
// in `-btn`; "handled" is a `classList.contains` branch in the delegation.
import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { auditActions, VIEWS_DIR } from "../helpers/actionAudit.js";

const HERE = dirname(fileURLToPath(import.meta.url));

// Only this chunk's two files may satisfy the behaviour check.
const OURS = ["users.test.js", "usersActions.test.js"];

auditActions({
  name: "Users row actions",
  sources: [join(VIEWS_DIR, "users.js")],
  frozen: [
    "archive-user-btn", "edit-user-name-btn", "edit-user-role-btn",
    "reset-pw-btn", "restore-user-btn",
  ],
  behaviourDir: HERE,
  behaviourExclude: readdirSync(HERE).filter((f) => !OURS.includes(f)),
  // `[ "]` after the capture keeps `class="row-actions"` and `class="empty"`
  // out (they do not end in `-btn`) and stops the capture at the first class,
  // so `secondary-btn` never registers as an action of its own.
  renderedPattern: /class="([a-z-]+-btn)[ "]/g,
  handledPattern: /classList\.contains\("([a-z-]+-btn)"\)/g,
});
