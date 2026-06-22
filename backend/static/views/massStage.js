// View: Mass Stage page (planning).
//
// Layer: views. Owns the Mass Stage page: create a stage for a building, then
// add rooms (each with one work order) and planned items per room, and Save
// (planning -> loading). Stages and rooms are expandable one-line cards
// (<details>); planned items are rows inside a room with inline qty edit.
//
// Self-contained UI state (a cached item list for the add-item search) lives
// in this module, like transactions.js's batch state -- it is not shared with
// other views, so it does not belong in state.js. The loading/returns UI
// (merged list, Staged, Unused materials) is added in Phase 7.

import {
  apiListStages,
  apiCreateStage,
  apiGetStage,
  apiUpdateStage,
  apiDeleteStage,
  apiAddRoom,
  apiUpdateRoom,
  apiDeleteRoom,
  apiAddStageItem,
  apiUpdateStageItem,
  apiDeleteStageItem,
  apiLoadStageItem,
  apiReturnStageItem,
  apiReuseStage,
  apiListItems,
  apiListUsers,
  apiAssignRoom,
} from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { setMessage, confirmDialog } from "../dom.js";

const listEl = document.getElementById("mass-stage-list");
const listMessage = document.getElementById("mass-stage-list-message");
const createInput = document.getElementById("mass-stage-building-input");
const createBtn = document.getElementById("mass-stage-create-btn");
const createMessage = document.getElementById("mass-stage-create-message");

// Cached item list for the add-item search; loaded once per session.
let allItems = [];
let itemsLoaded = false;
// Cached technician list for the room "Assign to" dropdown; loaded once.
let allTechs = [];
let techsLoaded = false;
// Stage id to auto-expand after a reload (set right after creating one).
let autoOpenId = null;

function statusBadge(status) {
  return `<span class="stage-status stage-status-${escapeHtml(status)}">${escapeHtml(status)}</span>`;
}

// Summary meta text. A building with one room is a lightweight "work order"
// entry; two or more rooms make it a full mass-stage card (the display
// threshold -- see docs/mass-staging/phase-10-saved-workorders.md).
function stageMetaText(roomCount, itemCount) {
  if (roomCount >= 2) return `${roomCount} units · ${itemCount} items`;
  return roomCount === 1 ? "1 work order" : "no units";
}

// --- list + lazy detail --------------------------------------------------

export async function loadStages() {
  if (!itemsLoaded) {
    try {
      allItems = await apiListItems();
      itemsLoaded = true;
    } catch {
      allItems = []; // search just returns nothing until a later reload
    }
  }
  if (!techsLoaded) {
    try {
      allTechs = (await apiListUsers()).filter((u) => u.role === "technician");
      techsLoaded = true;
    } catch {
      allTechs = []; // assign dropdown just shows "Unassigned" until a reload
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

function buildStageCard(stage, compact) {
  const card = document.createElement("details");
  card.className = compact ? "stage-card stage-card-compact" : "stage-card";
  card.dataset.stageId = stage.id;

  const summary = document.createElement("summary");
  summary.className = "stage-summary";
  summary.innerHTML =
    `<span class="stage-title">${escapeHtml(stage.building_name)}</span>` +
    statusBadge(stage.status) +
    `<span class="stage-meta">${stageMetaText(stage.room_count, stage.item_count)}</span>`;

  const body = document.createElement("div");
  body.className = "stage-body";
  body.innerHTML = `<p class="hint">Loading…</p>`;

  card.appendChild(summary);
  card.appendChild(body);

  // Lazy-load the full detail the first time the card is opened.
  card.addEventListener("toggle", () => {
    if (card.open && !card.dataset.loaded) openStageDetail(stage.id, body, card);
  });

  if (autoOpenId && stage.id === autoOpenId) {
    autoOpenId = null;
    card.open = true; // fires `toggle` -> loads detail
  }
  return card;
}

function renderStageList(stages) {
  listEl.innerHTML = "";
  if (!stages.length) {
    listEl.innerHTML = `<p class="hint">No mass stages yet. Create one above.</p>`;
    return;
  }
  // Display threshold: a building becomes a full card only with 2+ rooms.
  // Single-room (or empty) buildings stay lightweight entries below.
  const multi = stages.filter((s) => s.room_count >= 2);
  const single = stages.filter((s) => s.room_count < 2);

  multi.forEach((stage) => listEl.appendChild(buildStageCard(stage, false)));

  if (single.length) {
    const heading = document.createElement("h3");
    heading.className = "ms-single-heading";
    heading.textContent = "Single work orders";
    listEl.appendChild(heading);
    single.forEach((stage) => listEl.appendChild(buildStageCard(stage, true)));
  }
}

async function openStageDetail(stageId, bodyEl, cardEl) {
  try {
    const stage = await apiGetStage(stageId);
    renderStageBody(stage, bodyEl);
    if (cardEl) {
      cardEl.dataset.loaded = "1";
      // Keep the summary counts fresh after edits.
      const distinct = new Set();
      stage.rooms.forEach((r) => r.items.forEach((i) => distinct.add(i.item_id)));
      const meta = cardEl.querySelector(".stage-meta");
      if (meta) meta.textContent = stageMetaText(stage.rooms.length, distinct.size);
    }
  } catch (err) {
    bodyEl.innerHTML = `<p class="error">${escapeHtml(friendlyError(err, "Could not load this stage."))}</p>`;
  }
}

// --- detail rendering ----------------------------------------------------

function renderStageBody(stage, bodyEl) {
  // Planning = editable rooms/items; loading/completed = the load list.
  if (stage.status === "planning") {
    renderPlanningBody(stage, bodyEl);
  } else {
    renderLoadingBody(stage, bodyEl);
  }
}

function renderPlanningBody(stage, bodyEl) {
  const rooms = stage.rooms.map((room) => renderRoomHtml(room, true)).join("");
  const roomsHtml = rooms || `<p class="hint">No units yet.</p>`;

  bodyEl.innerHTML =
    `<div class="ms-rooms">${roomsHtml}</div>` +
    `<div class="ms-add-room">
       <input type="text" class="ms-room-number" placeholder="Unit #">
       <input type="text" class="ms-room-wo" placeholder="Work order #">
       <button type="button" data-action="add-room">Next Unit</button>
     </div>` +
    `<div class="ms-stage-actions">
       <button type="button" data-action="save-stage">Save Mass Stage</button>
       <button type="button" class="btn-danger" data-action="delete-stage">Delete</button>
     </div>` +
    `<p class="ms-stage-message"></p>`;
}

// Loading + completed: the per-item merged load list plus read-only rooms.
function renderLoadingBody(stage, bodyEl) {
  const loading = stage.status === "loading";
  const merged =
    (stage.merged_items || []).map((m) => renderMergedHtml(m, loading)).join("") ||
    `<p class="hint">No items planned.</p>`;
  const rooms =
    stage.rooms.map((room) => renderRoomHtml(room, false)).join("") ||
    `<p class="hint">No units.</p>`;
  const complete = loading
    ? `<button type="button" data-action="complete-stage">Mark Completed</button>`
    : "";
  // A completed stage can be reused: copies the building + rooms (work orders
  // cleared) into a fresh planning stage. The completed one stays as the record.
  const reuse = !loading
    ? `<button type="button" data-action="reuse-stage">Stage again</button>`
    : "";

  bodyEl.innerHTML =
    `<h3 class="ms-subhead">Load list</h3>` +
    `<div class="ms-merged">${merged}</div>` +
    `<h3 class="ms-subhead">Units</h3>` +
    `<div class="ms-rooms">${rooms}</div>` +
    `<div class="ms-stage-actions">
       ${complete}
       ${reuse}
       <button type="button" class="btn-danger" data-action="delete-stage">Delete</button>
     </div>` +
    `<p class="ms-stage-message"></p>`;
}

// A merged-item row (the unit loaded onto the truck). `m` is a MergedItem.
function renderMergedHtml(m, loading) {
  const overflow =
    Number(m.overflow) > 0
      ? `<span class="ms-overflow">+${escapeHtml(m.overflow)} over</span>`
      : "";
  // Coverage: while loading, the concern is the remaining-to-load vs stock;
  // otherwise compare the full plan vs stock.
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

function renderRoomHtml(room, planning) {
  const items = room.items.map((it) => renderItemHtml(it, planning)).join("");
  const itemsHtml = items || `<p class="hint">No items yet.</p>`;

  const addItem = planning
    ? `<div class="ms-add-item" data-room-id="${escapeHtml(room.id)}">
         <div class="ms-add-item-row">
           <input type="text" class="ms-item-search" placeholder="Search item by name or barcode">
           <input type="number" class="ms-item-qty" placeholder="Qty" min="0" step="any">
           <button type="button" data-action="add-item">Add</button>
         </div>
         <div class="ms-item-results scan-chooser" hidden></div>
       </div>`
    : "";

  const removeRoom = planning
    ? `<button type="button" class="btn-danger ms-room-remove" data-action="remove-room" data-room-id="${escapeHtml(room.id)}">Remove unit</button>`
    : "";

  // Editable work order in planning (reused stages start with it cleared).
  const woEdit = planning
    ? `<div class="ms-room-wo-edit">
         <label>Work order</label>
         <input type="text" class="ms-room-wo-input" value="${escapeHtml(room.work_order_number)}" placeholder="Work order #">
         <button type="button" class="secondary-btn" data-action="update-room">Update</button>
       </div>`
    : "";

  // Assign the work order to a technician (planning only). Options come from the
  // cached technician list; the current assignee is preselected.
  const assignEdit = planning
    ? `<div class="ms-room-assign">
         <label>Assign to</label>
         <select class="ms-room-assignee">
           <option value="">Unassigned</option>
           ${allTechs
             .map(
               (t) =>
                 `<option value="${escapeHtml(t.id)}"${
                   t.id === room.assigned_to_id ? " selected" : ""
                 }>${escapeHtml(t.username)}</option>`
             )
             .join("")}
         </select>
         <button type="button" class="secondary-btn" data-action="assign-room">Assign</button>
       </div>`
    : "";

  const assigneeMeta = room.assigned_to_username
    ? ` · ${escapeHtml(room.assigned_to_username)}`
    : "";

  return `<details class="room-card" data-room-id="${escapeHtml(room.id)}">
            <summary class="room-summary">
              <span class="room-title">Unit ${escapeHtml(room.room_number)}</span>
              <span class="room-meta">WO ${escapeHtml(room.work_order_number) || "—"} · ${room.items.length} items${assigneeMeta}</span>
            </summary>
            <div class="room-body">
              ${woEdit}
              ${assignEdit}
              <div class="ms-items">${itemsHtml}</div>
              ${addItem}
              ${removeRoom}
            </div>
          </details>`;
}

// How much `need` exceeds `onHand` (0 when covered). Values may arrive as
// numbers or strings, so coerce.
function shortBy(need, onHand) {
  const diff = Number(need) - Number(onHand);
  return diff > 0 ? diff : 0;
}

// On-hand label + a shortfall flag when `need` can't be covered by stock.
function coverageHtml(need, onHand) {
  const short = shortBy(need, onHand);
  const flag = short > 0 ? ` <span class="ms-short">short by ${escapeHtml(short)}</span>` : "";
  return `<span class="ms-onhand">On hand: ${escapeHtml(onHand)}</span>${flag}`;
}

// `it` is a StageItemDetail: `id` is the stage-item id, `item_id` the inventory
// item, plus item_name / item_barcode / planned_quantity / item_quantity (on-hand).
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

// Re-fetch one stage's detail and re-render its body, preserving which rooms
// were open (a mutation rebuilds the body HTML).
async function refreshStage(stageCard) {
  const body = stageCard.querySelector(".stage-body");
  const openRooms = new Set(
    [...body.querySelectorAll("details.room-card[open]")].map((d) => d.dataset.roomId)
  );
  await openStageDetail(stageCard.dataset.stageId, body, stageCard);
  openRooms.forEach((rid) => {
    const d = body.querySelector(`details.room-card[data-room-id="${rid}"]`);
    if (d) d.open = true;
  });
}

// --- create --------------------------------------------------------------

async function createStage() {
  const name = createInput.value.trim();
  setMessage(createMessage, "", "");
  if (!name) {
    setMessage(createMessage, "Enter a building name.", "error");
    return;
  }
  try {
    const stage = await apiCreateStage(name);
    createInput.value = "";
    autoOpenId = stage.id; // expand the new card after the reload
    await loadStages();
    setMessage(createMessage, "Mass stage created.", "success");
  } catch (err) {
    setMessage(createMessage, friendlyError(err, "Could not create the stage."), "error");
  }
}

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
  // Typing invalidates a previous pick.
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

  // Picking a search result doesn't need a stage context.
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

  const stageCard = btn.closest(".stage-card");
  if (!stageCard) return;
  const stageId = stageCard.dataset.stageId;
  const msg = stageCard.querySelector(".ms-stage-message");
  setMessage(msg, "", "");

  try {
    if (action === "add-room") {
      const wrap = btn.closest(".ms-add-room");
      const number = wrap.querySelector(".ms-room-number").value.trim();
      const wo = wrap.querySelector(".ms-room-wo").value.trim();
      if (!number || !wo) {
        setMessage(msg, "Enter a unit number and work order.", "error");
        return;
      }
      await apiAddRoom(stageId, { roomNumber: number, workOrderNumber: wo });
      await refreshStage(stageCard);
    } else if (action === "remove-room") {
      if (!window.confirm("Remove this unit and its planned items?")) return;
      await apiDeleteRoom(stageId, btn.dataset.roomId);
      await refreshStage(stageCard);
    } else if (action === "update-room") {
      const roomCard = btn.closest(".room-card");
      const wo = roomCard.querySelector(".ms-room-wo-input").value.trim();
      if (!wo) {
        setMessage(msg, "Enter a work order for the unit.", "error");
        return;
      }
      await apiUpdateRoom(stageId, roomCard.dataset.roomId, { work_order_number: wo });
      await refreshStage(stageCard);
    } else if (action === "assign-room") {
      const roomCard = btn.closest(".room-card");
      const assignedToId = roomCard.querySelector(".ms-room-assignee").value || null;
      await apiAssignRoom(stageId, roomCard.dataset.roomId, assignedToId);
      await refreshStage(stageCard);
    } else if (action === "reuse-stage") {
      if (!window.confirm("Start a new staging for this community? Units are copied (work orders cleared) and item lists start empty.")) return;
      const fresh = await apiReuseStage(stageId);
      autoOpenId = fresh.id;
      await loadStages();
    } else if (action === "add-item") {
      const container = btn.closest(".ms-add-item");
      const roomId = container.dataset.roomId;
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
      await apiAddStageItem(stageId, roomId, { itemId, plannedQuantity: qty });
      await refreshStage(stageCard);
    } else if (action === "edit-item") {
      const roomId = btn.closest(".room-card").dataset.roomId;
      const row = btn.closest(".ms-item");
      const qty = parseFloat(row.querySelector(".ms-item-planned").value);
      if (!Number.isFinite(qty) || qty <= 0) {
        setMessage(msg, "Enter a quantity greater than zero.", "error");
        return;
      }
      await apiUpdateStageItem(stageId, roomId, row.dataset.itemId, { plannedQuantity: qty });
      await refreshStage(stageCard);
    } else if (action === "remove-item") {
      const roomId = btn.closest(".room-card").dataset.roomId;
      const row = btn.closest(".ms-item");
      await apiDeleteStageItem(stageId, roomId, row.dataset.itemId);
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
    // `msg` may be detached after a full list reload (save/delete) -- harmless.
    setMessage(msg, friendlyError(err, "That action did not work."), "error");
  }
});
