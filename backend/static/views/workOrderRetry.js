// Work Orders: offline-save recovery.
//
// Layer: sits beside workOrderActions.js rather than inside it (that file is
// already near the repo's line budget) and imports workOrderList.js the same
// way workOrderActions.js does -- never workOrderRouting.js, which is the
// other half of the cycle workOrderRouting.js's own header describes.
//
// Two jobs: replay a save that failed while the tab was offline (or the
// session had just expired) once the server is reachable again, and, when a
// 401 is about to hide the app, remember which card + editor to reopen after
// re-login so the operator lands back where they were instead of starting
// the work order over.

import {
  apiAddWorkOrderItem,
  apiAddWorkOrderLabor,
  apiUpdateWorkOrder,
  apiUpdateWorkOrderItem,
  apiUpdateWorkOrderLabor,
} from "../api.js";
import { setMessage } from "../dom.js";
import { friendlyError } from "../format.js";
import { subscribe } from "../realtime.js";
import {
  SECTION_SELECTOR,
  allDrafts,
  clearDraft,
  markDraftError,
  setPendingResume,
} from "../workOrderDrafts.js";
import { STATUS_CHANGED_EVENT, heldWorkOrderCards, refreshCard } from "./workOrderList.js";

const listEl = document.getElementById("work-orders-list");

// One entry per draftable `data-action` in workOrderActions.js. Each takes
// (workOrderId, payload, targetId) so the table stays a plain lookup.
const RETRY_ACTIONS = {
  "add-labor": (workOrderId, payload) => apiAddWorkOrderLabor(workOrderId, payload),
  "edit-labor": (workOrderId, payload, targetId) => apiUpdateWorkOrderLabor(workOrderId, targetId, payload),
  "add-item": (workOrderId, payload) => apiAddWorkOrderItem(workOrderId, payload),
  "edit-item": (workOrderId, payload, targetId) => apiUpdateWorkOrderItem(workOrderId, targetId, payload),
  "save-notes": (workOrderId, payload) => apiUpdateWorkOrder(workOrderId, payload),
  "save-details": (workOrderId, payload) => apiUpdateWorkOrder(workOrderId, payload),
};

// Called on a socket reconnect and once at boot (see auth.js). Safe to run
// with no drafts pending -- `allDrafts()` is then empty and this is a no-op.
export async function replayPendingDrafts() {
  for (const draft of allDrafts()) {
    // Already rejected by the server on a prior pass; needs a human to look
    // at it and resave, not another silent attempt.
    if (draft.lastError) continue;
    const replay = RETRY_ACTIONS[draft.action];
    if (!replay) continue;

    const cardEl = listEl?.querySelector(`.wo-card[data-id="${draft.workOrderId}"]`);
    try {
      await replay(draft.workOrderId, draft.payload, draft.targetId);
      clearDraft(draft.workOrderId, draft.section);
      if (cardEl) {
        await refreshCard(cardEl, SECTION_SELECTOR[draft.section]);
        const msg = cardEl.querySelector(".wo-message");
        if (msg) setMessage(msg, "Reconnected — your entry saved.", "success");
      }
    } catch (err) {
      // No status: still offline, or (at boot, before the session check has
      // resolved) not authenticated yet -- leave the draft for the next
      // reconnect. Any real status is the server actively saying no, which
      // won't change on its own.
      if (err?.status === undefined || err.status === 401) continue;
      markDraftError(draft.workOrderId, draft.section, err);
      // `.wo-message` loses its own class once `setMessage` has painted it
      // once (className is overwritten wholesale -- see docs/open-work.md),
      // so a card that already showed the original inline failure has none
      // left to select here.
      const msg = cardEl?.querySelector(".wo-message");
      if (msg) setMessage(msg, friendlyError(err, "Could not save your entry automatically."), "error");
    }
  }
}

subscribe(STATUS_CHANGED_EVENT, ({ reason }) => {
  if (reason !== "reconnect") return;
  void replayPendingDrafts();
});

// Called from auth.js's global 401 handler, before it hides the app. Picks
// the first held card -- solo mode and the list both only ever have one
// editor a person is realistically mid-entry on -- and remembers where to
// send them back after they sign in again.
export function captureHeldEditorForResume() {
  const [cardEl] = heldWorkOrderCards();
  if (!cardEl) return;
  const entry = Object.entries(SECTION_SELECTOR).find(([, selector]) => cardEl.querySelector(selector)?.open);
  if (!entry) return;
  setPendingResume({ workOrderId: cardEl.dataset.id, number: cardEl.dataset.number, section: entry[0] });
}
