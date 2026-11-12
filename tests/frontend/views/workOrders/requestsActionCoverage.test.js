// The Request card delegates `data-request-action` clicks off `document`
// (workOrderRequests.js) and branches on `action === "…"`. P2's audit
// excludes this file by name, so its four actions are audited here with the
// card's own rendered pattern. Only the two requests files may satisfy the
// check: "cancel" and "send" are ordinary enough to be quoted in a sibling's
// prose.
import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { auditActions, VIEWS_DIR } from "../../helpers/actionAudit.js";

const HERE = dirname(fileURLToPath(import.meta.url));

auditActions({
  name: "Request card actions",
  sources: [join(VIEWS_DIR, "workOrderRequests.js")],
  renderedPattern: /data-request-action="([a-z-]+)"/g,
  handledPattern: /action === "([a-z-]+)"/g,
  frozen: ["add-requested", "cancel", "pick", "send"],
  behaviourDir: HERE,
  behaviourExclude: readdirSync(HERE)
    .filter((f) => f !== "requests.test.js" && f !== "requestsActions.test.js"),
});
