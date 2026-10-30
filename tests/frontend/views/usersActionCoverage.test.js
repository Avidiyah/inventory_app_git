// Users renders one menus.js action menu per row (`{ value: "x", label }`)
// and branches on `action === "x"` in the initActionMenus callback. The
// profile link (`user-profile-btn`) is a name link, not a row action, and is
// covered by users.test.js directly.
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
  frozen: ["archive", "edit-details", "edit-role", "reset-password", "restore"],
  behaviourDir: HERE,
  behaviourExclude: readdirSync(HERE).filter((f) => !OURS.includes(f)),
  renderedPattern: /\{ value: "([a-z-]+)", label:/g,
  handledPattern: /action === "([a-z-]+)"/g,
});
