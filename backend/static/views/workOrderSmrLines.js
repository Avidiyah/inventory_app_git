// Work Orders: an SMR order's Labor card, its Invoice section and the Ready
// row (user 2026-11-12: just labor entries, shaped like the Labor card; the
// vendor flow stays; the readings, the excluded lines and the history are
// off the card).
//
// Builders only, like workOrderCardHtml.js. The listeners live in
// workOrderSmrActions.js. Editing is Admin and above (TechFM OA ranks below
// Admin, so `isAdminPlus` would be the wrong floor).

import { escapeHtml, formatMoney } from "../format.js";
import { roleAtLeast } from "../roles.js";
import { getRole } from "../state.js";
import { tipHtml } from "../tooltip.js";
import { targetLaborHtml } from "./workOrderPresenters.js";

// The vocabulary of domain/work_orders_smr_lines.py; smrLines.test.js checks
// every entry here is still in that file.
export const SMR_VENDORS = ["Belfor", "Green Choice", "XXL Construction", "BT Restoration", "Unknown", "Admin"];
export const SMR_KINDS = ["field", "assessment", "audit", "staging", "material preparation", "clean-up"];
// What the entry row calls a kind: plain field work is just "Labor" (user, 2026-11-06).
const KIND_LABELS = { field: "Labor" };
const kindLabel = (kind) => KIND_LABELS[kind] || kind.replace(/(^|\s)\S/g, (c) => c.toUpperCase());
const kindSlug = (kind) => kind.replace(/[^a-z]+/g, "-");

export const canEditSmrLines = () => roleAtLeast(getRole(), "admin");

const hours = (n) => `${Number(n || 0).toFixed(1)} h`;
// ISO date -> MM/DD/YY, the form the block prints.
const shortDate = (iso) => (iso ? `${iso.slice(5, 7)}/${iso.slice(8, 10)}/${iso.slice(2, 4)}` : "");
const stamp = (iso) => new Date(iso).toLocaleDateString([], { month: "2-digit", day: "2-digit", year: "2-digit" });
const options = (values, selected, label = (v) => v) =>
  values.map((v) => `<option value="${escapeHtml(v)}"${v === selected ? " selected" : ""}>${escapeHtml(label(v))}</option>`).join("");

function workerLabel(line) {
  const name = line.worker_name || line.alias_on_paper || "Skilled Technician";
  return line.headcount > 1 ? `${name} ×${line.headcount}` : name;
}

// One line reads like a Labor entry: who and what kind on the left, the day
// and vendor under the name, the hours box with Update / Edit / Remove on the
// right. Below Admin the hours are text and there are no buttons.
function lineRowHtml(line, editable) {
  const when = line.work_date ? shortDate(line.work_date) : (line.week ? `Week ${line.week}` : "undated");
  const kind = line.kind === "field" ? "" : `<span class="wo-smr-line-kind wo-smr-line-kind--${escapeHtml(kindSlug(line.kind))}">${escapeHtml(kindLabel(line.kind))}</span>`;
  const crew = line.headcount > 1;
  const side = editable
    ? `<div class="wo-labor-actions">
         <input type="number" class="wo-smr-l-hours" value="${escapeHtml(line.hours_each)}" min="0.5" step="0.5" aria-label="${crew ? "Hours each" : "Hours"}">
         <button type="button" class="secondary-btn" data-action="smr-update-line">Update</button>
         <button type="button" class="secondary-btn" data-action="smr-edit-line">Edit</button>
         <button type="button" class="btn-danger" data-action="smr-delete-line">Remove</button>
       </div>`
    : `<span class="wo-smr-line-hours">${escapeHtml(crew ? `${line.headcount} × ${hours(line.hours_each)}` : hours(line.hours_each))}</span>`;
  return `<div class="wo-labor-entry wo-smr-line" data-line-id="${escapeHtml(line.id)}" data-line="${escapeHtml(JSON.stringify(line))}">
            <div>
              <span class="wo-smr-line-head"><strong>${escapeHtml(workerLabel(line))}</strong>${kind}</span>
              <span class="hint">${escapeHtml(when)} · ${escapeHtml(line.vendor)}${crew && editable ? " · hours each" : ""}</span>
            </div>
            ${side}
          </div>`;
}

// The one entry row, shaped like Labor's, serves add and edit
// (`dataset.lineId` says which): a keyed name (blank = Skilled Technician),
// a headcount for a crew, hours each, the date, then the vendor flow.
function entryRowHtml(detail) {
  const last = (detail.smr_lines || []).at(-1);
  return `<div class="wo-add-labor wo-smr-add">
    <label><span>Name on paper</span><input type="text" class="wo-smr-a-name" placeholder="blank = Skilled Technician"></label>
    <label><span>Headcount${tipHtml("smr.crew")}</span><input type="number" class="wo-smr-a-headcount" min="1" step="1" value="1"></label>
    <label><span>Hours each</span><input type="number" class="wo-smr-a-hours" min="0.5" step="0.5" placeholder="e.g. 2"></label>
    <label><span>Date</span><input type="date" class="wo-smr-a-date"></label>
    <label><span>Vendor${tipHtml("smr.vendor")}</span><select class="wo-smr-a-vendor">${options(SMR_VENDORS, last?.vendor || "Belfor")}</select></label>
    <label><span>Reason${tipHtml("smr.reason")}</span><select class="wo-smr-a-kind">${options(SMR_KINDS, "field", kindLabel)}</select></label>
    <button type="button" data-action="smr-add-line">Add labor</button>
    <button type="button" class="secondary-btn" data-action="smr-cancel-line" hidden>Cancel</button>
  </div>`;
}

// Fill the entry row from a line (Edit) or put it back to add (Cancel). A
// kind the select does not list is appended so an imported combined kind
// survives a round trip.
export function fillEntryRow(row, line) {
  const set = (cls, value) => { row.querySelector(`.${cls}`).value = value ?? ""; };
  row.dataset.lineId = line?.id || "";
  set("wo-smr-a-name", line?.alias_on_paper || line?.worker_name);
  set("wo-smr-a-headcount", line?.headcount ?? 1);
  set("wo-smr-a-hours", line?.hours_each);
  set("wo-smr-a-date", line?.work_date);
  const kind = row.querySelector(".wo-smr-a-kind");
  if (line?.kind && ![...kind.options].some((o) => o.value === line.kind)) kind.add(new Option(line.kind, line.kind));
  kind.value = line?.kind || "field";
  if (line) set("wo-smr-a-vendor", line.vendor);
  row.querySelector('[data-action="smr-add-line"]').textContent = line ? "Save changes" : "Add labor";
  row.querySelector('[data-action="smr-cancel-line"]').hidden = !line;
}

// The six fields the row holds; the server links a keyed name to a known
// worker and fills every other column with its default.
export function readEntryRow(row) {
  const v = (cls) => row.querySelector(`.${cls}`).value.trim();
  return {
    work_date: v("wo-smr-a-date") || null,
    vendor: v("wo-smr-a-vendor"),
    alias_on_paper: v("wo-smr-a-name") || null,
    headcount: Number(v("wo-smr-a-headcount")) || 1,
    hours_each: v("wo-smr-a-hours"),
    kind: v("wo-smr-a-kind") || "field",
  };
}

// One line under the entries, like Labor's summary: the hours that bill and,
// for a role that sees money, the charge.
function totalHtml(detail) {
  const total = (detail.smr_lines || []).reduce((sum, line) => sum + Number(line.hours), 0);
  const charge = detail.labor_total === null || detail.labor_total === undefined
    ? ""
    : `<span class="wo-labor-charge">${escapeHtml(formatMoney(detail.labor_total))}</span>`;
  return `<div class="wo-labor-summary"><span>Total: <strong>${escapeHtml(hours(total))}</strong></span>${charge}</div>`;
}

export function smrLaborSectionHtml(detail) {
  const editable = canEditSmrLines();
  const lines = detail.smr_lines || [];
  const rows = lines.map((line) => lineRowHtml(line, editable)).join("") || `<p class="hint">No labor recorded yet.</p>`;
  const hint = editable
    ? `<p class="hint">One line per person or crew, from the vendor's paper. Update saves the hours; Remove deletes the line for good.${tipHtml("smr.remove")}</p>`
    : "";
  return `<details class="wo-section-card wo-labor-section wo-smr-section" open>
            <summary class="wo-section-summary">Labor</summary>
            <div class="wo-section-content">
              ${hint}
              <div class="wo-labor-list wo-smr-lines">${rows}</div>
              ${lines.length ? totalHtml(detail) : ""}
              ${targetLaborHtml(detail)}
              ${editable ? entryRowHtml(detail) : ""}
            </div>
          </details>`;
}

export function blockStatusText(block) {
  if (!block) return "No correction block yet.";
  const pasted = block.pasted_at
    ? `pasted ${stamp(block.pasted_at)}${block.pasted_by_name ? ` by ${block.pasted_by_name}` : ""}`
    : "not yet pasted";
  return `v${block.version} · ${pasted}${block.stale ? ` · lines changed since v${block.version}` : ""}`;
}

function blockHtml(detail, editable) {
  const block = detail.smr_block;
  const text = block?.text
    ? `<textarea class="pricing-output wo-smr-block-text" readonly rows="${block.text.split("\n").length}">${escapeHtml(block.text)}</textarea>`
    : "";
  // Work description (user 2026-11-10): typed by a person, saved and printed
  // in the block by Generate.
  const description = editable
    ? `<label class="wo-smr-description"><span>Work description (prints in the block)</span><textarea class="wo-smr-description-text" rows="4" maxlength="4000" placeholder="Tasks done, including any not on the request, and why the hours are what they are.">${escapeHtml(detail.smr_description || "")}</textarea></label>`
    : "";
  const print = editable && block?.text ? `<button type="button" class="secondary-btn" data-action="smr-print-block">Print receipt</button>` : "";
  const buttons = editable
    ? `<button type="button" data-action="smr-generate-block">Generate correction block</button>` +
      (block && !block.pasted_at
        ? `<button type="button" class="secondary-btn" data-action="smr-mark-pasted" data-block-id="${escapeHtml(block.id)}">Mark pasted to NetFacilities</button>`
        : "")
    : "";
  return `<div class="wo-smr-block">${description}<p class="hint wo-smr-block-status">${escapeHtml(blockStatusText(block))}</p>${text}<div class="wo-smr-form-actions">${buttons}${print}</div></div>`;
}

// The invoicing steps, apart from the labor entries: description, Generate,
// Print, Mark pasted. Open for the roles that work it, folded for the rest.
export function smrInvoiceSectionHtml(detail) {
  if (!detail?.smr) return "";
  const editable = canEditSmrLines();
  return `<details class="wo-section-card wo-smr-invoice"${editable ? " open" : ""}>
            <summary class="wo-section-summary">Invoice</summary>
            <div class="wo-section-content">${blockHtml(detail, editable)}</div>
          </details>`;
}

// Ready to invoice: a person's stamp, offered while the order has a line in
// invoice Weeks 1–7 — the backend's gate, so a labor-only (no material) order
// can be stamped too; a stamp on an order that lost that line is held.
// Rendered at the top of the card, under the controls.
const inInvoicePeriod = (line) => line.exclusion_ground !== "removed" && line.week >= 1 && line.week <= 7;

export function readyRowHtml(detail, editable) {
  const stamp_ = detail.smr_ready;
  if (detail.smr_stage === "ready") {
    const who = stamp_?.by_name ? ` by ${stamp_.by_name}` : "";
    const text = `Ready to invoice · ${stamp(stamp_?.at)}${who}`;
    const btn = editable ? ` <button type="button" class="secondary-btn" data-action="smr-not-ready">Not ready</button>` : "";
    return `<p class="wo-smr-ready wo-smr-ready--ready">${escapeHtml(text)}${btn}</p>`;
  }
  if ((detail.smr_lines || []).some(inInvoicePeriod)) {
    return editable
      ? `<p class="wo-smr-ready"><button type="button" class="secondary-btn" data-action="smr-ready">Ready to invoice</button></p>`
      : `<p class="wo-smr-ready hint">Not yet ready to invoice</p>`;
  }
  const text = stamp_ ? "Ready stamp held until a line is in Weeks 1–7" : "Date a line in Weeks 1–7 to mark ready";
  return `<p class="wo-smr-ready hint">${text}</p>`;
}
