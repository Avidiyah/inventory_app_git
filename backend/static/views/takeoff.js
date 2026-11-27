// View: the Takeoff page (Owner, Admin, TechFM OA).
//
// Layer: views. Material planned on open work orders, one block per service
// type, one row per item. Each row is ONE markup: a table row at 600px and up,
// a stacked card below (CSS grid areas, styles.css "Takeoff page"). The server
// computes need, totals, shortfall and the shared flag; this view only draws
// them and records purchases through the Ordered control. Every save reloads
// the overview, so a pooled shortfall never goes stale on a sibling row.

import { apiCreateCorrection, apiGetTakeoff, apiSetTakeoffPurchase } from "../api.js";
import { setMessage } from "../dom.js";
import { escapeHtml, formatMoney, friendlyError, safeHttpUrl } from "../format.js";
import { skeletonList } from "../skeleton.js";

const listEl = document.getElementById("takeoff-list");
const messageEl = document.getElementById("takeoff-message");

const EMPTY_TEXT = "No takeoff material on open work orders.";
const CHECK = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';

// Rows whose work-order list is open, kept across the reload a save triggers.
const openLists = new Set();
let loadSequence = 0;

// "110.00" -> "110", "2.50" -> "2.5" (matches the backend's format_quantity).
const qty = (value) => String(Number(value));
// Two quantities summed without binary drift (0.1 + 0.2).
const plus = (a, b) => Number((Number(a) + Number(b)).toFixed(6));
const money = (value) => (value === null || value === undefined ? "—" : formatMoney(value));
const rowId = (group, row) => `${group.service_type_key}|${row.item_id}`;

function itemHtml(group, row) {
  const name = escapeHtml(row.item_name);
  const href = safeHttpUrl(row.product_link);
  const title = href
    ? `<a class="tk-item-name" href="${escapeHtml(href)}" target="_blank" rel="noopener">${name}</a>`
    : `<span class="tk-item-name">${name}</span>`;
  if (!row.work_orders.length) return title;
  const open = openLists.has(rowId(group, row));
  const links = row.work_orders.map((wo) =>
    `<button type="button" class="tk-wo" data-act="open-wo" data-id="${escapeHtml(wo.id)}">WO ${escapeHtml(wo.number)} ×${qty(wo.quantity)}</button>`
  ).join("");
  const count = row.work_orders.length;
  return `${title}
    <button type="button" class="tk-link tk-wos-toggle" data-act="wos" aria-expanded="${open}">${count} work order${count === 1 ? "" : "s"}</button>
    <div class="tk-wos"${open ? "" : " hidden"}>${links}</div>`;
}

function orderedHtml(row) {
  const short = Number(row.shortfall) > 0;
  const onWay = Number(row.on_the_way) > 0;
  const text = short
    ? `Order ${qty(row.shortfall)} more${row.shared ? '<small>shared with other service types</small>' : ""}`
    : (onWay ? "Ordered" : "Covered by stock");
  // The form is filled when it opens (openForm): an empty box adds to what is
  // on the way, a ticked box or the On the way figure edits or clears it.
  return `<button type="button" class="tk-ord ${short ? "tk-ord-need" : "tk-ord-ok"}" data-act="ord" aria-expanded="false">
      <span class="tk-box">${short ? "" : CHECK}</span><span class="tk-ord-t">${text}</span>
    </button>
    <div class="tk-form" hidden>
      <label><span class="tk-form-l"></span>
        <input type="number" min="0" step="any" inputmode="decimal"></label>
      <button type="button" data-act="save">Save</button>
      <button type="button" class="btn-danger" data-act="clear" hidden>Clear</button>
      <button type="button" class="secondary-btn" data-act="cancel">Cancel</button>
    </div>`;
}

function rowHtml(group, row) {
  const cellOf = (name, label, value) =>
    `<div class="tk-cell tk-${name}" role="cell"><span class="tk-lbl">${label}</span><span class="tk-val">${value}</span></div>`;
  return `<div class="tk-row" role="row" data-item-id="${escapeHtml(row.item_id)}"
        data-key="${escapeHtml(group.service_type_key)}" data-label="${escapeHtml(group.service_type_label)}"
        data-way="${escapeHtml(row.on_the_way)}" data-short="${escapeHtml(row.shortfall)}" data-stock="${escapeHtml(row.stock)}">
      <div class="tk-cell tk-item" role="cell">${itemHtml(group, row)}</div>
      ${cellOf("need", "Need", qty(row.need))}
      ${cellOf("price", "Price", money(row.price))}
      ${cellOf("total", "Total", money(row.total))}
      ${cellOf("stock", "In stock",
        `<button type="button" class="tk-link tk-way-btn" data-act="edit-stock">${qty(row.stock)}</button>`)}
      ${cellOf("way", "On the way", Number(row.on_the_way) > 0
        ? `<button type="button" class="tk-link tk-way-btn" data-act="edit-way">${qty(row.on_the_way)}</button>` : "—")}
      <div class="tk-cell tk-ordered" role="cell">${orderedHtml(row)}</div>
    </div>`;
}

function groupHtml(group) {
  return `<section class="tk-group" role="table" aria-label="${escapeHtml(group.service_type_label)}">
    <h3><span class="tk-group-title">${escapeHtml(group.service_type_label)}</span>
      <span class="tk-group-total">${formatMoney(group.total)} planned</span></h3>
    <div class="tk-head" role="row">
      <span role="columnheader">Item</span><span role="columnheader">Need</span><span role="columnheader">Price</span>
      <span role="columnheader">Total</span><span role="columnheader">In stock</span>
      <span role="columnheader">On the way</span><span role="columnheader">Ordered</span>
    </div>
    ${group.rows.map((row) => rowHtml(group, row)).join("")}
  </section>`;
}

export async function loadTakeoff() {
  const sequence = ++loadSequence;
  // Only when no rows are up: a reload after a save keeps them in place.
  if (!listEl.children.length) {
    setMessage(messageEl, "", "");
    listEl.innerHTML = skeletonList(4);
  }
  try {
    const overview = await apiGetTakeoff();
    if (sequence !== loadSequence) return;
    const groups = overview?.groups || [];
    listEl.innerHTML = groups.map(groupHtml).join("");
    setMessage(messageEl, groups.length ? "" : EMPTY_TEXT, "");
  } catch (err) {
    if (sequence !== loadSequence) return;
    listEl.replaceChildren();
    setMessage(messageEl, friendlyError(err, "Could not load Takeoff."), "error");
  }
}

async function openWorkOrder(id) {
  const [{ focusWorkOrder }, { showPage }] = await Promise.all([
    import("./workOrders.js"), import("./nav.js"),
  ]);
  focusWorkOrder(id);
  showPage("work-orders");
}

// Mode "stock" writes a stock correction (reason "<service type> Audit");
// every other mode records the on-the-way purchase.
async function save(row, quantity) {
  const buttons = row.querySelectorAll(".tk-form button");
  const correcting = row.querySelector(".tk-form").dataset.mode === "stock";
  buttons.forEach((b) => { b.disabled = true; });
  try {
    await (correcting
      ? apiCreateCorrection({ itemId: row.dataset.itemId, newQuantity: quantity, reason: `${row.dataset.label} Audit` })
      : apiSetTakeoffPurchase({
        itemId: row.dataset.itemId,
        serviceTypeKey: row.dataset.key,
        serviceTypeLabel: row.dataset.label,
        quantity,
      }));
    await loadTakeoff();
  } catch (err) {
    buttons.forEach((b) => { b.disabled = false; });
    setMessage(messageEl, friendlyError(err, correcting ? "Could not correct the stock count." : "Could not save that purchase."), "error");
  }
}

function closeForm(row) {
  row.querySelector(".tk-form").hidden = true;
  row.querySelector(".tk-ord").setAttribute("aria-expanded", "false");
}

// mode "add": ordered more (sends on the way + entered). Mode "edit": the
// on-the-way figure itself, which can be changed or cleared. Mode "stock": the
// counted shelf quantity, saved as a correction.
const FORM_MODES = {
  add: { label: "How many did you order?", field: "short" },
  edit: { label: "On the way", field: "way" },
  stock: { label: "New stock count", field: "stock" },
};

function openForm(row, mode) {
  const form = row.querySelector(".tk-form");
  form.dataset.mode = mode;
  form.querySelector(".tk-form-l").textContent = FORM_MODES[mode].label;
  form.querySelector("input").value = qty(row.dataset[FORM_MODES[mode].field]);
  form.querySelector('[data-act="clear"]').hidden = mode !== "edit" || !(Number(row.dataset.way) > 0);
  form.hidden = false;
  row.querySelector(".tk-ord").setAttribute("aria-expanded", "true");
  form.querySelector("input").focus();
}

function submitEntered(row) {
  const form = row.querySelector(".tk-form");
  const raw = form.querySelector("input").value.trim();
  const entered = Number(raw);
  const adding = form.dataset.mode === "add";
  if (!raw || !Number.isFinite(entered) || entered < 0 || (adding && entered === 0)) {
    setMessage(messageEl, "Enter a quantity.", "error");
    return;
  }
  return save(row, adding ? plus(row.dataset.way, entered) : entered);
}

listEl.addEventListener("click", (event) => {
  const btn = event.target.closest("[data-act]");
  const row = btn?.closest(".tk-row");
  if (!row) return;
  const act = btn.dataset.act;
  if (act === "wos") {
    const list = row.querySelector(".tk-wos");
    list.hidden = !list.hidden;
    const id = `${row.dataset.key}|${row.dataset.itemId}`;
    if (list.hidden) openLists.delete(id); else openLists.add(id);
    btn.setAttribute("aria-expanded", String(!list.hidden));
  } else if (act === "open-wo") {
    void openWorkOrder(btn.dataset.id);
  } else if (act === "ord") {
    const form = row.querySelector(".tk-form");
    const adding = Number(row.dataset.short) > 0;
    if (!form.hidden && form.dataset.mode === (adding ? "add" : "edit")) closeForm(row);
    else openForm(row, adding ? "add" : "edit");
  } else if (act === "edit-way") {
    openForm(row, "edit");
  } else if (act === "edit-stock") {
    const form = row.querySelector(".tk-form");
    if (!form.hidden && form.dataset.mode === "stock") closeForm(row);
    else openForm(row, "stock");
  } else if (act === "save") {
    void submitEntered(row);
  } else if (act === "clear") {
    void save(row, 0);
  } else if (act === "cancel") {
    closeForm(row);
  }
});

listEl.addEventListener("keydown", (event) => {
  const input = event.target.closest(".tk-form input");
  if (!input) return;
  const row = input.closest(".tk-row");
  if (event.key === "Enter") { event.preventDefault(); void submitEntered(row); }
  else if (event.key === "Escape") closeForm(row);
});
