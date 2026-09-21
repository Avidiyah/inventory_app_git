// User Requests delegates on a click over class names, with the markup in one
// module (userRequestCards.js) and the delegation in another (userRequests.js)
// -- so `sources` takes both. "Rendered" is the first `user-request-*` class of
// a <button>; "handled" is an `event.target.closest(".user-request-*")` in the
// delegation, minus the three structural selectors (`card`, `item-search`,
// `mode`) that name containers and inputs rather than actions (P7 deviation 8).
import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { auditActions, VIEWS_DIR } from "../helpers/actionAudit.js";

const HERE = dirname(fileURLToPath(import.meta.url));

// Only this chunk's three files may satisfy the behaviour check.
const OURS = ["userRequests.test.js", "userRequestsActions.test.js", "userRequestsFulfil.test.js"];

auditActions({
  name: "User Requests row actions",
  sources: [join(VIEWS_DIR, "userRequestCards.js"), join(VIEWS_DIR, "userRequests.js")],
  frozen: [
    "user-request-action", "user-request-close-cancel", "user-request-close-open",
    "user-request-close-save", "user-request-count-save", "user-request-edit-cancel",
    "user-request-edit-open", "user-request-edit-save", "user-request-fulfill-cancel",
    "user-request-fulfill-open", "user-request-fulfill-save", "user-request-item-pick",
    "user-request-price-save", "user-request-stock",
  ],
  behaviourDir: HERE,
  behaviourExclude: readdirSync(HERE).filter((f) => !OURS.includes(f)),
  renderedPattern: /<button[^>]*class="[^"]*\b(user-request-[a-z-]+)\b/g,
  handledPattern: /event\.target\.closest\("\.(user-request-(?!card|item-search|mode)[a-z-]+)"\)/g,
});
