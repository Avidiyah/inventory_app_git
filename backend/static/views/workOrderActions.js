// Work Orders: card delegation.
//
// Layer: the six listeners delegated off `#work-orders-list` -- the
// add-material and technician searches, the 26-branch click delegation, the
// Escape/focusout dismissals, the inline charge editor, and the entry-mode
// select. Registered as a side effect of importing this module, exactly as
// they were when they lived in the list.
//
// Exports nothing: the markup these branches act on is built in
// workOrderCardHtml.js, and the audit that keeps the two in step is
// tests/frontend/views/workOrders/actionCoverage.test.js.

import {
  apiAddWorkOrderItem,
  apiAddWorkOrderLabor,
  apiArchiveWorkOrder,
  apiCompleteWorkOrder,
  apiDeleteWorkOrderItem,
  apiDeleteWorkOrderLabor,
  apiHoldWorkOrder,
  apiResumeWorkOrder,
  apiSetWorkOrderItemBilling,
  apiStartWorkOrderTracking,
  apiStopWorkOrderTracking,
  apiUpdateWorkOrder,
  apiUpdateWorkOrderItem,
  apiUpdateWorkOrderLabor,
} from "../api.js";
import { confirmDialog, messageDialog, setMessage } from "../dom.js";
import { escapeHtml, filterRanked, friendlyError } from "../format.js";
import { openBillingEditor } from "./billingEditor.js";
import { catalogueRequestPromptHtml } from "./catalogueRequest.js";
import {
  hoursToMinutes,
  modeLabel,
  notesLogContentsHtml,
} from "./workOrderPresenters.js";
import {
  closeCombo,
  closeTechnicianResults,
  emptyTechnicianSelectionHtml,
  renderBody,
  renderTechnicianSearch,
  technicianSelectionHtml,
} from "./workOrderCardHtml.js";
import { getAllItems } from "./workOrderReferenceData.js";
import { exitSolo } from "./workOrderRouting.js";
import { loadWorkOrders, refreshCard } from "./workOrderList.js";

const listEl = document.getElementById("work-orders-list");

// --- add-material search (input delegation) ------------------------------

listEl.addEventListener("input", (event) => {
  const input = event.target;
  if (input.classList.contains("wo-tech-search")) {
    renderTechnicianSearch(input);
    return;
  }
  if (!input.classList.contains("ms-item-search")) return;
  const container = input.closest(".wo-add-item");
  const results = container.querySelector(".ms-item-results");
  delete container.dataset.itemId;
  delete container.dataset.materialRequestId;
  const q = input.value.trim().toLowerCase();
  if (!q) {
    results.hidden = true;
    results.innerHTML = "";
    return;
  }
  const matches = filterRanked(
    getAllItems(),
    (it) => [it.name, it.barcode],
    q
  ).slice(0, 8);
  // No match means the catalogue has no row for what they typed, so offer to
  // report it. The work order travels with the request: fulfilling it later
  // logs the material back onto this job retroactively.
  const cardEl = input.closest(".wo-card");
  results.innerHTML = matches.length
    ? matches
        .map(
          (it) =>
            `<button type="button" class="secondary-btn scan-choice-btn" data-action="pick-item" data-item-id="${escapeHtml(it.id)}" data-item-name="${escapeHtml(it.name)}">${escapeHtml(it.name)} <span class="ms-pick-barcode">${escapeHtml(it.barcode)}</span></button>`
        )
        .join("")
    : `<p class="hint">No matching items.</p>` +
      catalogueRequestPromptHtml({
        searchedText: input.value.trim(),
        workOrderId: cardEl ? cardEl.dataset.id : null,
        source: "work_orders",
      });
  results.hidden = false;
});

// --- actions (click delegation) ------------------------------------------

listEl.addEventListener("click", async (event) => {
  const btn = event.target.closest("[data-action]");
  if (!btn) return;
  const action = btn.dataset.action;

  if (action === "pick-item") {
    const container = btn.closest(".wo-add-item");
    container.dataset.itemId = btn.dataset.itemId;
    delete container.dataset.materialRequestId;
    container.querySelector(".ms-item-search").value = btn.dataset.itemName;
    const results = container.querySelector(".ms-item-results");
    results.hidden = true;
    results.innerHTML = "";
    container.querySelector(".wo-item-qty").focus();
    return;
  }

  if (action === "pick-technician") {
    const picker = btn.closest(".wo-tech-picker");
    const list = picker.querySelector(".wo-tech-selected-list");
    const technicianId = btn.dataset.technicianId;
    if (!list.querySelector(`[data-technician-id="${technicianId}"]`)) {
      list.querySelector(".wo-tech-empty")?.remove();
      list.insertAdjacentHTML(
        "beforeend",
        technicianSelectionHtml(technicianId, btn.dataset.technicianName)
      );
    }
    const input = picker.querySelector(".wo-tech-search");
    input.value = "";
    closeTechnicianResults(picker);
    input.focus();
    return;
  }

  if (action === "remove-technician") {
    const picker = btn.closest(".wo-tech-picker");
    const list = picker.querySelector(".wo-tech-selected-list");
    btn.closest(".wo-tech-selected-row")?.remove();
    if (!list.querySelector(".wo-tech-selected-row")) {
      list.innerHTML = emptyTechnicianSelectionHtml();
    }
    picker.querySelector(".wo-tech-search")?.focus();
    return;
  }

  if (action === "toggle-combo") {
    const combo = btn.closest(".wo-combo");
    const list = combo.querySelector(".wo-combo-list");
    const opening = list.hidden;
    // Only one open at a time -- picking in one shouldn't leave another
    // combo's listbox stranded open behind it.
    listEl.querySelectorAll(".wo-combo").forEach((other) => {
      if (other !== combo) closeCombo(other);
    });
    list.hidden = !opening;
    btn.setAttribute("aria-expanded", String(opening));
    return;
  }

  if (action === "pick-combo-option") {
    const combo = btn.closest(".wo-combo");
    const nativeSelect = combo.querySelector(".wo-combo-native");
    const label = combo.querySelector(".wo-combo-trigger-label");
    nativeSelect.value = btn.dataset.value;
    label.textContent = btn.textContent;
    combo.querySelectorAll(".wo-combo-option").forEach((opt) => {
      opt.setAttribute("aria-selected", String(opt === btn));
    });
    closeCombo(combo);
    combo.querySelector(".wo-combo-trigger")?.focus();
    return;
  }

  if (action === "back-to-work-orders") {
    // Above the `.wo-card` lookup below: this control lives in the list but
    // outside any card, so the `if (!cardEl) return` guard would swallow it.
    if (window.history.state?.solo) {
      // We pushed this entry. Unwinding it keeps Back and Forward agreeing
      // with the button; `popstate` does the actual restore.
      window.history.back();
    } else {
      // A cold deep link: there is no entry of ours to pop, and calling
      // back() would leave the app. loadWorkOrders normalizes the URL itself
      // (exitSolo).
      void loadWorkOrders();
    }
    return;
  }

  if (action === "open-netfacilities-wo") {
    // Placeholder pending real NetFacilities integration on this button --
    // same destination the domain layer's work_order_task_fallback generates
    // (app/domain/work_orders.py) for an imported task with no real one yet.
    const url = `https://system.netfacilities.com/tools/viewworkorders/${encodeURIComponent(btn.dataset.number)}`;
    window.open(url, "_blank", "noopener,noreferrer");
    return;
  }

  const cardEl = btn.closest(".wo-card");
  if (!cardEl) return;
  const workOrderId = cardEl.dataset.id;
  const msg = cardEl.querySelector(".wo-message");
  if (msg) setMessage(msg, "", "");

  try {
    if (action === "start-tracking-wo") {
      await apiStartWorkOrderTracking(workOrderId);
      await refreshCard(cardEl);
    } else if (action === "stop-tracking-wo") {
      const stopped = await apiStopWorkOrderTracking(workOrderId);
      await refreshCard(cardEl);
      // Stopping the last clock on a job moves it On-Hold by itself. Without
      // saying so, the badge changing on its own reads as something going
      // wrong. Chosen from the refreshed row, so the message and the server
      // cannot disagree. Re-queried after the refresh: renderBody replaced the
      // old element.
      if (stopped?.status === "on_hold") {
        setMessage(
          cardEl.querySelector(".wo-message"),
          "Work stopped. Nobody is charging, so this is now On-Hold.",
          "success"
        );
      }
    } else if (action === "notify-supervisor-wo") {
      let finished;
      try {
        finished = await apiCompleteWorkOrder(workOrderId);
      } catch (err) {
        // A co-worker's clock is still running: this is not a failure to
        // report inline, it's a rule the tapper needs to act on -- go find
        // that person -- so it gets the same pop-up treatment as the other
        // hard stop above rather than the quiet inline .wo-message text.
        if (
          err?.status === 400 &&
          err.detail === "All Users must Stop Charging before a Supervisor can be notified."
        ) {
          await messageDialog(err.detail);
          return;
        }
        throw err;
      }
      await refreshCard(cardEl);
      // A Technician's finish lands Ready to Complete, so the badge that
      // appears a moment later would otherwise read as a failed save. Chosen
      // from the row the server returned rather than from the role.
      if (finished?.status === "ready_to_complete") {
        setMessage(
          cardEl.querySelector(".wo-message"),
          "Sent to your supervisor for review.",
          "success"
        );
      }
    } else if (action === "send-back-wo") {
      // Rejection means "go finish the job", so the crew is live again rather
      // than paused -- which keeps On-Hold meaning purely "nobody is on it".
      await apiUpdateWorkOrder(workOrderId, { status: "in_progress" });
      await refreshCard(cardEl);
    } else if (action === "hold-assigned-wo") {
      await apiHoldWorkOrder(workOrderId);
      await refreshCard(cardEl);
    } else if (action === "resume-assigned-wo") {
      await apiResumeWorkOrder(workOrderId);
      await refreshCard(cardEl);
    } else if (action === "complete-wo") {
      await apiUpdateWorkOrder(workOrderId, { status: "completed" });
      await refreshCard(cardEl);
    } else if (action === "review-wo") {
      if (!(await confirmDialog("Are you sure this work order is ready for Review?"))) return;
      await apiUpdateWorkOrder(workOrderId, { status: "review" });
      await refreshCard(cardEl);
    } else if (action === "reopen-wo") {
      await apiUpdateWorkOrder(workOrderId, { status: "in_progress" });
      await refreshCard(cardEl);
    } else if (action === "archive-wo") {
      if (!(await confirmDialog(
        "Archive this work order? It will leave the active list and can be restored from History."
      ))) return;
      await apiArchiveWorkOrder(workOrderId);
      await loadWorkOrders();
    } else if (action === "cancel-edit") {
      // Re-fetch to throw away drafts and return the Edit details card to its
      // default collapsed state with the saved values restored.
      await refreshCard(cardEl);
    } else if (action === "save-details") {
      const body = cardEl.querySelector(".wo-body");
      // Only the fields the editor actually rendered: the legacy
      // community/building/unit inputs are absent on an imported work order,
      // and sending them as null would wipe values the editor never showed.
      const value = (selector) => {
        const el = body.querySelector(selector);
        return el ? el.value.trim() || null : undefined;
      };
      const patch = {
        status: value(".wo-edit-status"),
        location: value(".wo-edit-location"),
        service_type: value(".wo-edit-service-type"),
        schedule_date: value(".wo-edit-schedule-date"),
        output_to: value(".wo-edit-output-to"),
        vendor_assignee: value(".wo-edit-vendor"),
        description: value(".wo-edit-description"),
        priority: value(".wo-edit-priority"),
        supervisor_id: body.querySelector(".wo-edit-supervisor")?.value || null,
        expected_supervisor_id:
          body.querySelector(".wo-edit")?.dataset.originalSupervisorId || null,
        assigned_to_ids: Array.from(body.querySelectorAll(".wo-tech-selected-row")).map(
          (row) => row.dataset.technicianId
        ),
      };
      Object.keys(patch).forEach((k) => patch[k] === undefined && delete patch[k]);
      await apiUpdateWorkOrder(workOrderId, patch);
      await refreshCard(cardEl);
    } else if (action === "save-notes") {
      const notesInput = cardEl.querySelector(".wo-notes-input");
      const notesMessage = cardEl.querySelector(".wo-notes-message");
      const notes = notesInput.value.trim() || null;
      setMessage(notesMessage, "", "");
      if (!notes) {
        setMessage(notesMessage, "Enter a note before saving.", "error");
        return;
      }
      const updated = await apiUpdateWorkOrder(workOrderId, { notes });
      notesInput.value = "";
      const notesLog = cardEl.querySelector(".wo-notes-log");
      if (notesLog) notesLog.innerHTML = notesLogContentsHtml(updated.notes);
      setMessage(notesMessage, "Note saved.", "success");
      const notesSection = cardEl.querySelector(".wo-notes-section");
      if (notesSection) notesSection.open = false;
    } else if (action === "add-labor") {
      const section = btn.closest(".wo-labor-section");
      const technicianId = section.querySelector(".wo-labor-technician")?.value;
      const minutes = hoursToMinutes(section.querySelector(".wo-new-labor-hours")?.value);
      if (!technicianId) {
        setMessage(msg, "Assign and select a technician first.", "error");
        return;
      }
      if (!minutes) {
        setMessage(msg, "Enter actual labor hours greater than zero.", "error");
        return;
      }
      await apiAddWorkOrderLabor(workOrderId, { technicianId, minutes });
      await refreshCard(cardEl, ".wo-labor-section");
    } else if (action === "edit-labor") {
      const row = btn.closest(".wo-labor-entry");
      const minutes = hoursToMinutes(row.querySelector(".wo-labor-hours")?.value);
      if (!minutes) {
        setMessage(msg, "Enter actual labor hours greater than zero.", "error");
        return;
      }
      await apiUpdateWorkOrderLabor(workOrderId, row.dataset.laborId, { minutes });
      await refreshCard(cardEl, ".wo-labor-section");
    } else if (action === "remove-labor") {
      const row = btn.closest(".wo-labor-entry");
      if (!(await confirmDialog("Remove this labor entry from the work order?"))) return;
      await apiDeleteWorkOrderLabor(workOrderId, row.dataset.laborId);
      await refreshCard(cardEl, ".wo-labor-section");
    } else if (action === "add-item") {
      const container = btn.closest(".wo-add-item");
      const itemId = container.dataset.itemId;
      const qty = parseFloat(container.querySelector(".wo-item-qty").value);
      if (!itemId) {
        setMessage(msg, "Search and pick an item first.", "error");
        return;
      }
      if (!Number.isFinite(qty) || qty <= 0) {
        setMessage(msg, "Enter a quantity greater than zero.", "error");
        return;
      }
      const addedLine = await apiAddWorkOrderItem(workOrderId, {
        itemId,
        quantity: qty,
        materialRequestId: container.dataset.materialRequestId || null,
      });
      delete container.dataset.materialRequestId;
      await refreshCard(cardEl, ".wo-materials-section");
      const refreshedMessage = cardEl.querySelector(".wo-message");
      if (Number(addedLine.item_quantity) < 0) {
        setMessage(refreshedMessage, "Item added. Please re-count stock.", "error");
      } else {
        setMessage(refreshedMessage, "Item added.", "success");
      }
    } else if (action === "edit-item") {
      const row = btn.closest(".wo-item");
      const qty = parseFloat(row.querySelector(".wo-line-qty").value);
      if (!Number.isFinite(qty) || qty <= 0) {
        setMessage(msg, "Enter a quantity greater than zero.", "error");
        return;
      }
      await apiUpdateWorkOrderItem(workOrderId, row.dataset.woItemId, { quantity: qty });
      await refreshCard(cardEl, ".wo-materials-section");
    } else if (action === "remove-item") {
      const row = btn.closest(".wo-item");
      if (!(await confirmDialog("Remove this material from the work order?"))) return;
      await apiDeleteWorkOrderItem(workOrderId, row.dataset.woItemId);
      await refreshCard(cardEl, ".wo-materials-section");
    }
  } catch (err) {
    if (
      err?.status === 409 &&
      typeof err.detail === "string" &&
      err.detail.startsWith("This Work Order was already assigned to ")
    ) {
      await messageDialog(err.detail);
      window.location.reload();
      return;
    }
    if (msg) setMessage(msg, friendlyError(err, "That action did not work."), "error");
  }
});

listEl.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (event.target.classList.contains("wo-tech-search")) {
    closeTechnicianResults(event.target.closest(".wo-tech-picker"));
    return;
  }
  const combo = event.target.closest(".wo-combo");
  if (combo) closeCombo(combo);
});

listEl.addEventListener("focusout", (event) => {
  const picker = event.target.closest(".wo-tech-picker");
  if (picker) {
    setTimeout(() => {
      if (!picker.contains(document.activeElement)) closeTechnicianResults(picker);
    }, 0);
    return;
  }
  const combo = event.target.closest(".wo-combo");
  if (combo) {
    setTimeout(() => {
      if (!combo.contains(document.activeElement)) closeCombo(combo);
    }, 0);
  }
});

// --- Inline line-billing editor (Admin/Owner) ----------------------------
//
// The editor UI is shared with History (`views/billingEditor.js`); here we
// just supply the line's numbers and how to persist the change, then refresh
// the card. The "Edit charge" button only renders for those who may see cost,
// so no extra role check is needed.
listEl.addEventListener("click", (event) => {
  const editBtn = event.target.closest(".wo-edit-charge-btn");
  if (!editBtn) return;

  const cell = editBtn.closest(".wo-line-charge");
  const row = editBtn.closest(".wo-item");
  const cardEl = editBtn.closest(".wo-card");
  if (!cell || !row || !cardEl) return;

  const workOrderId = cardEl.dataset.id;
  const woItemId = row.dataset.woItemId;
  openBillingEditor(cell, {
    quantity: Number(cell.dataset.quantity),
    billable: Number(cell.dataset.billable),
    onSave: async (value) => {
      await apiSetWorkOrderItemBilling(workOrderId, woItemId, value);
      await refreshCard(cardEl, ".wo-materials-section");  // repaint the card (line charge + total)
    },
  });
});

// Mode select change.
listEl.addEventListener("change", async (event) => {
  const sel = event.target;
  if (!sel.classList.contains("wo-mode-select")) return;
  const cardEl = sel.closest(".wo-card");
  if (!cardEl) return;
  const msg = cardEl.querySelector(".wo-message");
  try {
    await apiUpdateWorkOrder(cardEl.dataset.id, { entry_mode: sel.value });
    if (msg) setMessage(msg, `New entries will be ${modeLabel(sel.value).toLowerCase()}.`, "success");
  } catch (err) {
    if (msg) setMessage(msg, friendlyError(err, "Could not switch mode."), "error");
  }
});
