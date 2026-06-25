// View: Mass Stage page (truck planning).
//
// Layer: views. Owns the Mass Stage page: a Community -> Building -> Unit tree.
// Create a stage for a community + building, add work orders (each a unit slot
// referencing a standalone work order) and planned items, then Save
// (planning -> loading) and load onto the truck. A unit links out to the Work
// Orders page (the work order owns its number / status / assignee).

import {
  apiListStages,
  apiCreateStage,
  apiGetStage,
  apiUpdateStage,
  apiDeleteStage,
  apiAddStageWorkOrder,
  apiDeleteStageWorkOrder,
  apiAddStageItem,
  apiUpdateStageItem,
  apiDeleteStageItem,
  apiLoadStageItem,
  apiReturnStageItem,
  apiReuseStage,
  apiListItems,
  apiListUsers,
} from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { setMessage, confirmDialog } from "../dom.js";
import { showPage } from "./nav.js";
import { focusWorkOrder } from "./workOrders.js";

const listEl = document.getElementById("mass-stage-list");
const listMessage = document.getElementById("mass-stage-list-message");
const communitySelect = document.getElementById("mass-stage-community-select");
const communityNewInput = document.getElementById("mass-stage-community-new");
const createInput = document.getElementById("mass-stage-building-input");
const createBtn = document.getElementById("mass-stage-create-btn");
const createMessage = document.getElementById("mass-stage-create-message");

const COMMUNITY_SEEDS = ["Scholars", "Centennial", "Cimarron"];
const NEW_COMMUNITY = "__new__";

let allItems = [];
let itemsLoaded = false;
let allTechs = [];
let techsLoaded = false;
let autoOpenId = null;
let autoOpenCommunity = null;

function statusBadge(status) {
  return `<span class="stage-status stage-status-${escapeHtml(status)}">${escapeHtml(status)}</span>`;
}

function stageMetaText(unitCount, itemCount) {
  if (!unitCount) return "no units";
  return `${unitCount} ${unitCount === 1 ? "unit" : "units"} · ${itemCount} items`;
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

// --- list + lazy detail --------------------------------------------------

export async function loadStages() {
  if (!itemsLoaded) {
    try {
      allItems = await apiListItems();
      itemsLoaded = true;
    } catch {
      allItems = [];
    }
  }
  if (!techsLoaded) {
    try {
      allTechs = (await apiListUsers()).filter((u) => u.role === "technician");
      techsLoaded = true;
    } catch {
      allTechs = [];
    }
  }
  try {
    const stages = await apiListStages();
    renderStageList(stages);
    setMessage(listMessage, "", "");
  } catch (err) {
    listEl.innerHTML = "";
    setMessage(listMessage, friendlyError(err, "Could not load mass stages."), "error");
  }
}

function buildStageCard(stage) {
  const card = document.createElement("details");
  card.className = "stage-card";
  card.dataset.stageId = stage.id;

  const summary = document.createElement("summary");
  summary.className = "stage-summary";
  summary.innerHTML =
    `<span class="stage-title">${escapeHtml(stage.building_name)}</span>` +
    statusBadge(stage.status) +
    `<span class="stage-meta">${stageMetaText(stage.unit_count, stage.item_count)}</span>`;

  const body = document.createElement("div");
  body.className = "stage-body";
  body.innerHTML = `<p class="hint">Loading…</p>`;

  card.appendChild(summary);
  card.appendChild(body);

  card.addEventListener("toggle", () => {
    if (card.open && !card.dataset.loaded) openStageDetail(stage.id, body, card);
  });

  if (autoOpenId && stage.id === autoOpenId) {
    autoOpenId = null;
    card.open = true;
  }
  return card;
}

function renderStageList(stages) {
  refreshCommunityOptions(stages);
  listEl.innerHTML = "";
  if (!stages.length) {
    listEl.innerHTML = `<p class="hint">No mass stages yet. Create one above.</p>`;
    return;
  }

  // Tier 1: group buildings by community.
  const byCommunity = new Map();
  stages.forEach((s) => {
    const key = s.community || "Unfiled";
    if (!byCommunity.has(key)) byCommunity.set(key, []);
    byCommunity.get(key).push(s);
  });

  [...byCommunity.keys()]
    .sort((a, b) => a.localeCompare(b))
    .forEach((community) => {
      const group = document.createElement("details");
      group.className = "community-group";
      group.dataset.community = community;
      const buildings = byCommunity.get(community);

      const summary = document.createElement("summary");
      summary.className = "community-summary";
      summary.innerHTML =
        `<span class="community-title">${escapeHtml(community)}</span>` +
        `<span class="community-meta">${buildings.length} ${buildings.length === 1 ? "building" : "buildings"}</span>`;
      group.appendChild(summary);

      // Tier 2: building (stage) cards.
      buildings.forEach((stage) => group.appendChild(buildStageCard(stage)));

      if (autoOpenCommunity && community === autoOpenCommunity) {
        autoOpenCommunity = null;
        group.open = true;
      }
      listEl.appendChild(group);
    });
}

async function openStageDetail(stageId, bodyEl, cardEl) {
  try {
    const stage = await apiGetStage(stageId);
    renderStageBody(stage, bodyEl);
    if (cardEl) {
      cardEl.dataset.loaded = "1";
      const distinct = new Set();
      stage.work_orders.forEach((s) => s.items.forEach((i) => distinct.add(i.item_id)));
      const meta = cardEl.querySelector(".stage-meta");
      if (meta) meta.textContent = stageMetaText(stage.work_orders.length, distinct.size);
    }
  } catch (err) {
    bodyEl.innerHTML = `<p class="error">${escapeHtml(friendlyError(err, "Could not load this stage."))}</p>`;
  }
}

// --- detail rendering ----------------------------------------------------

function renderStageBody(stage, bodyEl) {
  if (stage.status === "planning") {
    renderPlanningBody(stage, bodyEl);
  } else {
    renderLoadingBody(stage, bodyEl);
  }
}

function renderPlanningBody(stage, bodyEl) {
  const slots = stage.work_orders.map((slot) => renderSlotHtml(slot, true)).join("");
  const slotsHtml = slots || `<p class="hint">No units yet.</p>`;

  bodyEl.innerHTML =
    `<div class="ms-rooms">${slotsHtml}</div>` +
    `<div class="ms-add-room">
       <input type="text" class="ms-unit-number" placeholder="Unit # (optional)">
       <input type="text" class="ms-room-wo" placeholder="Work order #">
       <select class="ms-add-assignee">${techOptions("")}</select>
       <button type="button" data-action="add-work-order">Add work order</button>
     </div>` +
    `<div class="ms-stage-actions">
       <button type="button" data-action="save-stage">Save Mass Stage</button>
       <button type="button" class="btn-danger" data-action="delete-stage">Delete</button>
     </div>` +
    `<p class="ms-stage-message"></p>`;
}

function renderLoadingBody(stage, bodyEl) {
  const loading = stage.status === "loading";
  const merged =
    (stage.merged_items || []).map((m) => renderMergedHtml(m, loading)).join("") ||
    `<p class="hint">No items planned.</p>`;
  const slots =
    stage.work_orders.map((slot) => renderSlotHtml(slot, false)).join("") ||
    `<p class="hint">No units.</p>`;
  const complete = loading
    ? `<button type="button" data-action="complete-stage">Mark Completed</button>`
    : "";
  const reuse = !loading
    ? `<button type="button" data-action="reuse-stage">Stage again</button>`
    : "";

  bodyEl.innerHTML =
    `<h3 class="ms-subhead">Load list</h3>` +
    `<div class="ms-merged">${merged}</div>` +
    `<h3 class="ms-subhead">Units</h3>` +
    `<div class="ms-rooms">${slots}</div>` +
    `<div class="ms-stage-actions">
       ${complete}
       ${reuse}
       <button type="button" class="btn-danger" data-action="delete-stage">Delete</button>
     </div>` +
    `<p class="ms-stage-message"></p>`;
}

function renderMergedHtml(m, loading) {
  const overflow =
    Number(m.overflow) > 0
      ? `<span class="ms-overflow">+${escapeHtml(m.overflow)} over</span>`
      : "";
  const need = loading ? m.remaining_to_load : m.planned_total;
  const short = shortBy(need, m.on_hand);
  const shortFlag = short > 0 ? `<span class="ms-short">short by ${escapeHtml(short)}</span>` : "";
  const stats = `Planned ${escapeHtml(m.planned_total)} · Loaded ${escapeHtml(m.loaded_total)} · Remaining ${escapeHtml(m.remaining_to_load)} · On hand ${escapeHtml(m.on_hand)}`;
  const actions = loading
    ? `<div class="ms-merged-actions">
         <input type="number" class="ms-load-qty" value="${escapeHtml(m.remaining_to_load)}" min="0" step="any" aria-label="Load quantity">
         <button type="button" data-action="load-item" data-item-id="${escapeHtml(m.item_id)}" data-item-name="${escapeHtml(m.item_name)}">Staged</button>
         <input type="number" class="ms-return-qty" placeholder="Unused" min="0" step="any" aria-label="Unused quantity">
         <button type="button" class="secondary-btn" data-action="return-item" data-item-id="${escapeHtml(m.item_id)}">Return</button>
       </div>`
    : `<div class="ms-merged-stats-ro">Returned ${escapeHtml(m.returned_total)} · Consumed ${escapeHtml(m.net_consumed)}</div>`;
  return `<div class="ms-merged-item" data-item-id="${escapeHtml(m.item_id)}">
            <div class="ms-merged-head">
              <span class="ms-item-name">${escapeHtml(m.item_name)}</span>
              <span class="ms-item-barcode">${escapeHtml(m.item_barcode)}</span>
              ${overflow}
              ${shortFlag}
            </div>
            <div class="ms-merged-stats">${stats}</div>
            ${actions}
          </div>`;
}

// `slot` is a StageWorkOrderDetail: id (slot id), work_order_id, work_order_number,
// unit_number, status, assigned_to_username, items[].
function renderSlotHtml(slot, planning) {
  const items = slot.items.map((it) => renderItemHtml(it, planning)).join("");
  const itemsHtml = items || `<p class="hint">No items yet.</p>`;

  const addItem = planning
    ? `<div class="ms-add-item" data-slot-id="${escapeHtml(slot.id)}">
         <div class="ms-add-item-row">
           <input type="text" class="ms-item-search" placeholder="Search item by name or barcode">
           <input type="number" class="ms-item-qty" placeholder="Qty" min="0" step="any">
           <button type="button" data-action="add-item">Add</button>
         </div>
         <div class="ms-item-results scan-chooser" hidden></div>
       </div>`
    : "";

  const removeSlot = planning
    ? `<button type="button" class="btn-danger ms-room-remove" data-action="remove-slot" data-slot-id="${escapeHtml(slot.id)}">Remove unit</button>`
    : "";

  // The work order owns its number / status / assignee -- a unit always links
  // out to the Work Orders page to edit those.
  const openWo = `<button type="button" class="secondary-btn wo-open-btn" data-action="open-wo" data-wo-id="${escapeHtml(slot.work_order_id)}">Open work order →</button>`;

  const assigneeMeta = slot.assigned_to_username ? ` · ${escapeHtml(slot.assigned_to_username)}` : "";
  const unit = slot.unit_number ? escapeHtml(slot.unit_number) : "—";

  return `<details class="room-card" data-slot-id="${escapeHtml(slot.id)}">
            <summary class="room-summary">
              <span class="room-title">Unit ${unit}</span>
              <span class="room-meta">WO ${escapeHtml(slot.work_order_number)} · ${slot.items.length} items${assigneeMeta}</span>
            </summary>
            <div class="room-body">
              ${openWo}
              <div class="ms-items">${itemsHtml}</div>
              ${addItem}
              ${removeSlot}
            </div>
          </details>`;
}

function shortBy(need, onHand) {
  const diff = Number(need) - Number(onHand);
  return diff > 0 ? diff : 0;
}

function coverageHtml(need, onHand) {
  const short = shortBy(need, onHand);
  const flag = short > 0 ? ` <span class="ms-short">short by ${escapeHtml(short)}</span>` : "";
  return `<span class="ms-onhand">On hand: ${escapeHtml(onHand)}</span>${flag}`;
}

function renderItemHtml(it, planning) {
  const head =
    `<span class="ms-item-name">${escapeHtml(it.item_name)}</span>` +
    `<span class="ms-item-barcode">${escapeHtml(it.item_barcode)}</span>` +
    coverageHtml(it.planned_quantity, it.item_quantity);
  const tail = planning
    ? `<input type="number" class="ms-item-planned" value="${escapeHtml(it.planned_quantity)}" min="0" step="any">
       <button type="button" class="secondary-btn" data-action="edit-item">Update</button>
       <button type="button" class="btn-danger" data-action="remove-item">Remove</button>`
    : `<span class="ms-item-planned-ro">Planned: ${escapeHtml(it.planned_quantity)}</span>`;
  return `<div class="ms-item" data-item-id="${escapeHtml(it.id)}">${head}${tail}</div>`;
}

// Re-fetch one stage's detail and re-render its body, preserving open slots.
async function refreshStage(stageCard) {
  const body = stageCard.querySelector(".stage-body");
  const openSlots = new Set(
    [...body.querySelectorAll("details.room-card[open]")].map((d) => d.dataset.slotId)
  );
  await openStageDetail(stageCard.dataset.stageId, body, stageCard);
  openSlots.forEach((sid) => {
    const d = body.querySelector(`details.room-card[data-slot-id="${sid}"]`);
    if (d) d.open = true;
  });
}

// --- create stage --------------------------------------------------------

function selectedCommunity() {
  if (!communitySelect) return "";
  if (communitySelect.value === NEW_COMMUNITY) {
    return communityNewInput ? communityNewInput.value.trim() : "";
  }
  return communitySelect.value;
}

function refreshCommunityOptions(stages) {
  if (!communitySelect) return;
  const prev = communitySelect.value;
  const used = stages.map((s) => s.community).filter(Boolean);
  const names = [...new Set([...COMMUNITY_SEEDS, ...used])].sort((a, b) => a.localeCompare(b));
  communitySelect.innerHTML =
    names.map((n) => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join("") +
    `<option value="${NEW_COMMUNITY}">+ New community…</option>`;
  if (prev && [...names, NEW_COMMUNITY].includes(prev)) communitySelect.value = prev;
  toggleNewCommunity();
}

function toggleNewCommunity() {
  if (!communityNewInput || !communitySelect) return;
  communityNewInput.hidden = communitySelect.value !== NEW_COMMUNITY;
}

async function createStage() {
  const community = selectedCommunity();
  const building = createInput.value.trim();
  setMessage(createMessage, "", "");
  if (!community) {
    setMessage(createMessage, "Choose or enter a community.", "error");
    return;
  }
  if (!building) {
    setMessage(createMessage, "Enter a building number.", "error");
    return;
  }
  try {
    const stage = await apiCreateStage(community, building);
    createInput.value = "";
    if (communityNewInput) communityNewInput.value = "";
    autoOpenId = stage.id;
    autoOpenCommunity = community;
    await loadStages();
    setMessage(createMessage, "Mass stage created.", "success");
  } catch (err) {
    setMessage(createMessage, friendlyError(err, "Could not create the stage."), "error");
  }
}

if (communitySelect) communitySelect.addEventListener("change", toggleNewCommunity);
createBtn.addEventListener("click", createStage);
createInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") createStage();
});

// --- add-item search (input delegation) ----------------------------------

listEl.addEventListener("input", (event) => {
  const input = event.target;
  if (!input.classList.contains("ms-item-search")) return;
  const container = input.closest(".ms-add-item");
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
    const container = btn.closest(".ms-add-item");
    container.dataset.itemId = btn.dataset.itemId;
    container.querySelector(".ms-item-search").value = btn.dataset.itemName;
    const results = container.querySelector(".ms-item-results");
    results.hidden = true;
    results.innerHTML = "";
    container.querySelector(".ms-item-qty").focus();
    return;
  }

  // Open a unit's work order on the Work Orders page (tier-3). No stage context.
  if (action === "open-wo") {
    focusWorkOrder(btn.dataset.woId);
    showPage("work-orders");
    return;
  }

  const stageCard = btn.closest(".stage-card");
  if (!stageCard) return;
  const stageId = stageCard.dataset.stageId;
  const msg = stageCard.querySelector(".ms-stage-message");
  setMessage(msg, "", "");

  try {
    if (action === "add-work-order") {
      const wrap = btn.closest(".ms-add-room");
      const unit = wrap.querySelector(".ms-unit-number").value.trim();
      const wo = wrap.querySelector(".ms-room-wo").value.trim();
      const assignedToId = wrap.querySelector(".ms-add-assignee").value || null;
      if (!wo) {
        setMessage(msg, "Enter a work order number.", "error");
        return;
      }
      await apiAddStageWorkOrder(stageId, { workOrderNumber: wo, unitNumber: unit || null, assignedToId });
      await refreshStage(stageCard);
    } else if (action === "remove-slot") {
      if (!window.confirm("Remove this unit from the plan? (The work order itself is kept.)")) return;
      await apiDeleteStageWorkOrder(stageId, btn.dataset.slotId);
      await refreshStage(stageCard);
    } else if (action === "reuse-stage") {
      if (!window.confirm("Start a new staging for this community + building? Item lists start empty.")) return;
      const fresh = await apiReuseStage(stageId);
      autoOpenId = fresh.id;
      await loadStages();
    } else if (action === "add-item") {
      const container = btn.closest(".ms-add-item");
      const slotId = container.dataset.slotId;
      const itemId = container.dataset.itemId;
      const qty = parseFloat(container.querySelector(".ms-item-qty").value);
      if (!itemId) {
        setMessage(msg, "Search and pick an item first.", "error");
        return;
      }
      if (!Number.isFinite(qty) || qty <= 0) {
        setMessage(msg, "Enter a quantity greater than zero.", "error");
        return;
      }
      await apiAddStageItem(stageId, slotId, { itemId, plannedQuantity: qty });
      await refreshStage(stageCard);
    } else if (action === "edit-item") {
      const slotId = btn.closest(".room-card").dataset.slotId;
      const row = btn.closest(".ms-item");
      const qty = parseFloat(row.querySelector(".ms-item-planned").value);
      if (!Number.isFinite(qty) || qty <= 0) {
        setMessage(msg, "Enter a quantity greater than zero.", "error");
        return;
      }
      await apiUpdateStageItem(stageId, slotId, row.dataset.itemId, { plannedQuantity: qty });
      await refreshStage(stageCard);
    } else if (action === "remove-item") {
      const slotId = btn.closest(".room-card").dataset.slotId;
      const row = btn.closest(".ms-item");
      await apiDeleteStageItem(stageId, slotId, row.dataset.itemId);
      await refreshStage(stageCard);
    } else if (action === "load-item") {
      const row = btn.closest(".ms-merged-item");
      const qty = parseFloat(row.querySelector(".ms-load-qty").value);
      if (!Number.isFinite(qty) || qty <= 0) {
        setMessage(msg, "Enter a quantity greater than zero.", "error");
        return;
      }
      const ok = await confirmDialog(`Load ${qty} × ${btn.dataset.itemName} onto the truck?`);
      if (!ok) return;
      await apiLoadStageItem(stageId, { itemId: btn.dataset.itemId, quantity: qty });
      await refreshStage(stageCard);
    } else if (action === "return-item") {
      const row = btn.closest(".ms-merged-item");
      const qty = parseFloat(row.querySelector(".ms-return-qty").value);
      if (!Number.isFinite(qty) || qty <= 0) {
        setMessage(msg, "Enter a quantity to return.", "error");
        return;
      }
      await apiReturnStageItem(stageId, { itemId: btn.dataset.itemId, quantity: qty });
      await refreshStage(stageCard);
    } else if (action === "complete-stage") {
      if (!window.confirm("Mark this building complete? The stage becomes read-only.")) return;
      await apiUpdateStage(stageId, { status: "completed" });
      await loadStages();
    } else if (action === "save-stage") {
      if (!window.confirm("Save this mass stage? It moves to loading and the plan is locked.")) return;
      await apiUpdateStage(stageId, { status: "loading" });
      await loadStages();
    } else if (action === "delete-stage") {
      if (!window.confirm("Delete this mass stage? This cannot be undone.")) return;
      await apiDeleteStage(stageId);
      await loadStages();
    }
  } catch (err) {
    setMessage(msg, friendlyError(err, "That action did not work."), "error");
  }
});
