// The Request section left the work-order card on 2026-11-06; its module
// (views/workOrderRequests.js) stays in the app, loaded and unmounted. This
// puts the section back on an opened card exactly as the card used to -- the
// same two pieces of markup and the same mount call -- so the module's tests
// still drive it through a real card.
//
// The mount is started, not awaited: it paints the form and the loading copy
// before its first await, which is the state the first test looks at. A card
// refresh rebuilds the body and drops the section again, as it would in the
// app today.

import { importView } from "./shell.js";

export async function attachRequestSection(cardEl, detail, items = []) {
  const mod = await importView("views/workOrderRequests.js");
  cardEl.querySelector(".wo-materials-section .wo-items")
    .insertAdjacentHTML("afterend", '<div class="wo-requested-lines"></div>');
  cardEl.querySelector(".wo-message").insertAdjacentHTML(
    "beforebegin",
    `<details class="wo-section-card wo-request-section">
       <summary class="wo-section-summary">Request</summary>
       <div class="wo-section-content"></div>
     </details>`,
  );
  void mod.mountWorkOrderRequests(cardEl, detail, { items });
  return mod;
}
