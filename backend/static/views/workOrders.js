// View: Work Orders page.
//
// Layer: views. Owns the Work Orders page: a server-scoped list of standalone
// work orders (identity = number). Supervisor+ can create work orders and edit
// their attributes / assignee / archive; any in-scope user (incl. an assigned
// technician) can switch entry mode, mark complete/reopen, and log / edit /
// remove materials. Reached via the nav button or a Unit click in the Mass
// Stage tree (which calls `focusWorkOrder` before switching pages).

import {
  apiListWorkOrders,
  apiGetWorkOrder,
  apiCreateWorkOrder,
  apiUpdateWorkOrder,
  apiArchiveWorkOrder,
  apiAddWorkOrderItem,
  apiUpdateWorkOrderItem,
  apiDeleteWorkOrderItem,
  apiListItems,
  apiListUsers,
} from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { setMessage, confirmDialog } from "../dom.js";
import { getRole } from "../state.js";
import { roleAtLeast } from "../roles.js";

const listEl = document.getElementById("work-orders-list");
const listMessage = document.getElementById("work-orders-list-message");
const statusFilter = document.getElementById("work-orders-status-filter");
const searchInput = document.getElementById("work-orders-search");
const searchBtn = document.getElementById("work-orders-search-btn");

const createSection = document.getElementById("work-orders-create-section");
const createNumber = document.getElementById("wo-create-number");
const createCommunity = document.getElementById("wo-create-community");
const createBuilding = document.getElementById("wo-create-building");
const createUnit = document.getElementById("wo-create-unit");
const createAssignee = document.getElementById("wo-create-assignee");
const createBtn = document.getElementById("wo-create-btn");
const createMessage = document.getElementById("wo-create-message");

// Cached lists; loaded once per session.
let allItems = [];
let itemsLoaded = false;
let allTechs = [];
let techsLoaded = false;
// Work order id to expand once the list renders (set by a Mass Stage tree click).
let pendingFocusId = null;

export function focusWorkOrder(workOrderId) {
  pendingFocusId = workOrderId;
}

function isSupervisorPlus() {
  return roleAtLeast(getRole(), "supervisor");
}

function statusLabel(status) {
  return status === "in_progress" ? "In progress" : "Completed";
}

function statusBadge(status) {
  return `<span class="wo-status wo-status-${escapeHtml(status)}">${escapeHtml(statusLabel(status))}</span>`;
}

function modeLabel(mode) {
  return mode === "retroactive" ? "Retroactive" : "Dispense";
}

// Location meta string from a card/detail (any of the parts may be blank).
function placeMeta(c) {
  const parts = [];
  if (c.community) parts.push(c.community);
  if (c.building_number) parts.push(`Bldg ${c.building_number}`);
  if (c.unit_number) parts.push(`Unit ${c.unit_number}`);
  return parts.join(" · ");
}

function techOptions(selectedId) {
  return (
    `<option value="">Unassigned</option>` +
    allTechs
      .map(
        (t) =>
          `<option value="${escapeHtml(t.id)}"${t.id === selectedId ? " selected" : ""}>${escapeHtml(t.username)}</option>`
      )
      .join("")
  );
}

// --- list ----------------------------------------------------------------

export async function loadWorkOrders() {
  if (!itemsLoaded) {
    try {
      allItems = await apiListItems();
      itemsLoaded = true;
    } catch {
      allItems = [];
    }
  }
  if (!techsLoaded && isSupervisorPlus()) {
    try {
      allTechs = (await apiListUsers()).filter((u) => u.role === "technician");
      techsLoaded = true;
      if (createAssignee) createAssignee.innerHTML = techOptions("");
    } catch {
      allTechs = [];
    }
  }
  if (createSection) createSection.hidden = !isSupervisorPlus();

  const status = statusFilter.value;
  const q = searchInput.value.trim();
  try {
    let cards = await apiListWorkOrders({ status, q });
    if (pendingFocusId && !cards.some((c) => c.id === pendingFocusId)) {
      statusFilter.value = "";
      cards = await apiListWorkOrders({ status: "", q });
    }
    renderCards(cards);
    setMessage(listMessage, "", "");
    if (pendingFocusId) {
      const card = listEl.querySelector(`details.wo-card[data-id="${pendingFocusId}"]`);
      if (card) {
        card.open = true;
        card.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      pendingFocusId = null;
    }
  } catch (err) {
    listEl.innerHTML = "";
    setMessage(listMessage, friendlyError(err, "Could not load work orders."), "error");
  }
}

function renderCards(cards) {
  listEl.innerHTML = "";
  if (!cards.length) {
    listEl.innerHTML = `<p class="hint">No work orders match.</p>`;
    return;
  }
  cards.forEach((c) => listEl.appendChild(buildCard(c)));
}

function buildCard(card) {
  const el = document.createElement("details");
  el.className = "wo-card";
  el.dataset.id = card.id;

  const summary = document.createElement("summary");
  summary.className = "wo-summary";
  const place = placeMeta(card);
  const assignee = card.assigned_to_username ? ` · ${escapeHtml(card.assigned_to_username)}` : "";
  summary.innerHTML =
    `<span class="wo-title">WO ${escapeHtml(card.number)}</span>` +
    statusBadge(card.status) +
    `<span class="wo-meta">${place ? escapeHtml(place) + " · " : ""}${card.item_count} items${assignee}</span>`;

  const body = document.createElement("div");
  body.className = "wo-body";
  body.innerHTML = `<p class="hint">Loading…</p>`;

  el.appendChild(summary);
  el.appendChild(body);
  el.addEventListener("toggle", () => {
    if (el.open && !el.dataset.loaded) openDetail(card.id, body, el);
  });
  return el;
}

async function openDetail(workOrderId, bodyEl, cardEl) {
  try {
    const detail = await apiGetWorkOrder(workOrderId);
    renderBody(detail, bodyEl);
    if (cardEl) {
      cardEl.dataset.loaded = "1";
      const badge = cardEl.querySelector(".wo-status");
      if (badge) {
        badge.className = `wo-status wo-status-${detail.status}`;
        badge.textContent = statusLabel(detail.status);
      }
      const meta = cardEl.querySelector(".wo-meta");
      if (meta) {
        const place = placeMeta(detail);
        const assignee = detail.assigned_to_username ? ` · ${detail.assigned_to_username}` : "";
        meta.textContent = `${place ? place + " · " : ""}${detail.items.length} items${assignee}`;
      }
    }
  } catch (err) {
    bodyEl.innerHTML = `<p class="error">${escapeHtml(friendlyError(err, "Could not load this work order."))}</p>`;
  }
}

// --- detail rendering ----------------------------------------------------

function renderBody(detail, bodyEl) {
  const sup = isSupervisorPlus();
  const items =
    detail.items.map((it) => renderLineHtml(it)).join("") ||
    `<p class="hint">No materials logged yet.</p>`;

  const statusAction =
    detail.status === "in_progress"
      ? `<button type="button" data-action="complete-wo">Mark completed</button>`
      : `<button type="button" class="secondary-btn" data-action="reopen-wo">Reopen</button>`;

  const archive = sup
    ? `<button type="button" class="btn-danger" data-action="archive-wo">Archive</button>`
    : "";

  const modeControl =
    `<div class="wo-mode-row">
       <label>New entries:</label>
       <select class="wo-mode-select">
         <option value="dispense"${detail.entry_mode === "dispense" ? " selected" : ""}>Dispense (moves stock)</option>
         <option value="retroactive"${detail.entry_mode === "retroactive" ? " selected" : ""}>Retroactive (paper sheet, no stock)</option>
       </select>
     </div>`;

  // Supervisor+ attribute editor (community / building / unit / assignee).
  const details = sup
    ? `<div class="wo-edit">
         <input type="text" class="wo-edit-community" value="${escapeHtml(detail.community || "")}" placeholder="Community">
         <input type="text" class="wo-edit-building" value="${escapeHtml(detail.building_number || "")}" placeholder="Building #">
         <input type="text" class="wo-edit-unit" value="${escapeHtml(detail.unit_number || "")}" placeholder="Unit #">
         <select class="wo-edit-assignee">${techOptions(detail.assigned_to_id || "")}</select>
         <button type="button" class="secondary-btn" data-action="save-details">Save details</button>
       </div>`
    : "";

  bodyEl.innerHTML =
    `<div class="wo-controls">${modeControl}${statusAction}${archive}</div>` +
    details +
    `<div class="wo-items">${items}</div>` +
    `<div class="wo-add-item">
       <div class="wo-add-item-row">
         <input type="text" class="ms-item-search" placeholder="Search item by name or barcode">
         <input type="number" class="wo-item-qty" placeholder="Qty" min="0" step="any">
         <button type="button" data-action="add-item">Add</button>
       </div>
       <div class="ms-item-results scan-chooser" hidden></div>
     </div>` +
    `<p class="wo-message"></p>`;
}

function renderLineHtml(it) {
  const modeTag = `<span class="wo-line-mode wo-line-mode-${escapeHtml(it.mode)}">${escapeHtml(modeLabel(it.mode))}</span>`;
  return `<div class="wo-item" data-wo-item-id="${escapeHtml(it.id)}">
            <div class="wo-item-head">
              <span class="ms-item-name">${escapeHtml(it.item_name)}</span>
              <span class="ms-item-barcode">${escapeHtml(it.item_barcode)}</span>
              ${modeTag}
              <span class="wo-onhand">On hand: ${escapeHtml(it.item_quantity)}</span>
            </div>
            <div class="wo-item-actions">
              <input type="number" class="wo-line-qty" value="${escapeHtml(it.quantity)}" min="0" step="any" aria-label="Quantity">
              <button type="button" class="secondary-btn" data-action="edit-item">Update</button>
              <button type="button" class="btn-danger" data-action="remove-item">Remove</button>
            </div>
          </div>`;
}

async function refreshCard(cardEl) {
  const body = cardEl.querySelector(".wo-body");
  await openDetail(cardEl.dataset.id, body, cardEl);
}

// --- add-material search (input delegation) ------------------------------

listEl.addEventListener("input", (event) => {
  const input = event.target;
  if (!input.classList.contains("ms-item-search")) return;
  const container = input.closest(".wo-add-item");
  const results = container.querySelector(".ms-item-results");
  delete container.dataset.itemId;
  const q = input.value.trim().toLowerCase();
  if (!q) {
    results.hidden = true;
    results.innerHTML = "";
    return;
  }
  const matches = allItems
    .filter(
      (it) =>
        it.name.toLowerCase().includes(q) ||
        (it.barcode && it.barcode.toLowerCase().includes(q))
    )
    .slice(0, 8);
  results.innerHTML = matches.length
    ? matches
        .map(
          (it) =>
            `<button type="button" class="secondary-btn scan-choice-btn" data-action="pick-item" data-item-id="${escapeHtml(it.id)}" data-item-name="${escapeHtml(it.name)}">${escapeHtml(it.name)} <span class="ms-pick-barcode">${escapeHtml(it.barcode)}</span></button>`
        )
        .join("")
    : `<p class="hint">No matching items.</p>`;
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
    container.querySelector(".ms-item-search").value = btn.dataset.itemName;
    const results = container.querySelector(".ms-item-results");
    results.hidden = true;
    results.innerHTML = "";
    container.querySelector(".wo-item-qty").focus();
    return;
  }

  const cardEl = btn.closest(".wo-card");
  if (!cardEl) return;
  const workOrderId = cardEl.dataset.id;
  const msg = cardEl.querySelector(".wo-message");
  if (msg) setMessage(msg, "", "");

  try {
    if (action === "complete-wo") {
      await apiUpdateWorkOrder(workOrderId, { status: "completed" });
      await refreshCard(cardEl);
    } else if (action === "reopen-wo") {
      await apiUpdateWorkOrder(workOrderId, { status: "in_progress" });
      await refreshCard(cardEl);
    } else if (action === "archive-wo") {
      if (!(await confirmDialog("Archive this work order? It is hidden but the number stays reserved."))) return;
      await apiArchiveWorkOrder(workOrderId);
      await loadWorkOrders();
    } else if (action === "save-details") {
      const body = cardEl.querySelector(".wo-body");
      await apiUpdateWorkOrder(workOrderId, {
        community: body.querySelector(".wo-edit-community").value.trim() || null,
        building_number: body.querySelector(".wo-edit-building").value.trim() || null,
        unit_number: body.querySelector(".wo-edit-unit").value.trim() || null,
        assigned_to_id: body.querySelector(".wo-edit-assignee").value || null,
      });
      await refreshCard(cardEl);
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
      await apiAddWorkOrderItem(workOrderId, { itemId, quantity: qty });
      await refreshCard(cardEl);
    } else if (action === "edit-item") {
      const row = btn.closest(".wo-item");
      const qty = parseFloat(row.querySelector(".wo-line-qty").value);
      if (!Number.isFinite(qty) || qty <= 0) {
        setMessage(msg, "Enter a quantity greater than zero.", "error");
        return;
      }
      await apiUpdateWorkOrderItem(workOrderId, row.dataset.woItemId, { quantity: qty });
      await refreshCard(cardEl);
    } else if (action === "remove-item") {
      const row = btn.closest(".wo-item");
      if (!(await confirmDialog("Remove this material from the work order?"))) return;
      await apiDeleteWorkOrderItem(workOrderId, row.dataset.woItemId);
      await refreshCard(cardEl);
    }
  } catch (err) {
    if (msg) setMessage(msg, friendlyError(err, "That action did not work."), "error");
  }
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

// --- create (Supervisor+) ------------------------------------------------

async function createWorkOrder() {
  const number = createNumber.value.trim();
  setMessage(createMessage, "", "");
  if (!number) {
    setMessage(createMessage, "Enter a work order number.", "error");
    return;
  }
  try {
    await apiCreateWorkOrder({
      number,
      community: createCommunity.value.trim() || null,
      buildingNumber: createBuilding.value.trim() || null,
      unitNumber: createUnit.value.trim() || null,
      assignedToId: createAssignee.value || null,
    });
    createNumber.value = "";
    createCommunity.value = "";
    createBuilding.value = "";
    createUnit.value = "";
    createAssignee.value = "";
    await loadWorkOrders();
    setMessage(createMessage, "Work order saved.", "success");
  } catch (err) {
    setMessage(createMessage, friendlyError(err, "Could not create the work order."), "error");
  }
}

if (createBtn) createBtn.addEventListener("click", createWorkOrder);
if (createNumber) {
  createNumber.addEventListener("keydown", (event) => {
    if (event.key === "Enter") createWorkOrder();
  });
}

// --- filter / search controls --------------------------------------------

if (searchBtn) searchBtn.addEventListener("click", loadWorkOrders);
if (searchInput) {
  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") loadWorkOrders();
  });
}
if (statusFilter) statusFilter.addEventListener("change", loadWorkOrders);
