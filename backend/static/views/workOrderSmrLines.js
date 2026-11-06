// Work Orders: the SMR "Paper corrections" section (spec
// docs/superpowers/specs/2026-11-04-smr-paper-import-design.md, Editor).
//
// Builders only, like workOrderCardHtml.js: the readings list, the lines
// table, the one add/edit form, the correction-block box and the totals line.
// The listeners live in workOrderSmrActions.js. Editing is Admin and above
// (TechFM OA ranks below Admin, so `isAdminPlus` would be the wrong floor).

import { escapeHtml, formatMoney } from "../format.js";
import { roleAtLeast } from "../roles.js";
import { getRole } from "../state.js";

// The vocabulary of domain/work_orders_smr_lines.py; smrLines.test.js checks
// every entry here is still in that file.
export const SMR_VENDORS = ["Belfor", "Green Choice", "XXL Construction", "BT Restoration", "Unknown", "Admin"];
export const SMR_KINDS = ["field", "assessment", "audit", "staging", "material preparation", "clean-up"];
// What the add row calls a kind: plain field work is just "Labor" (user, 2026-11-06).
const KIND_LABELS = { field: "Labor" };
const kindLabel = (kind) => KIND_LABELS[kind] || kind.replace(/(^|\s)\S/g, (c) => c.toUpperCase());
const kindSlug = (kind) => kind.replace(/[^a-z]+/g, "-");
export const SMR_DATE_BASES = [
  "paper", "paper (date in note)", "closed date (Young Hall rule)",
  "Week 1 placement (crew sheets, Supplement)", "week placement (weekly reports)",
];
export const SMR_GROUNDS = [
  "undated", "before Week 1", "after 07/12 (no invoices)", "awaiting invoice (GC, Week 7)",
  "reprint (no hours added)", "note only", "paper not found", "read, not charged (user)",
  "read, not charged (weekly reports)", "admin, never charged", "vendor unknown", "removed",
];
export const SMR_REASON_CODES = [
  "as_read", "crew_as_one", "crew_as_individuals", "arithmetic", "overhead_added", "overhead_twice",
  "accurate", "over_billed", "not_on_paper", "unit_mismatch", "date_found", "manual_check",
  "awaiting_invoice", "belfor_only", "time_gap", "held_out", "hours_on_paper_above_billed",
];

export const canEditSmrLines = () => roleAtLeast(getRole(), "admin");

const hours = (n) => `${Number(n || 0).toFixed(1)} h`;
// ISO date -> MM/DD/YY, the form the block prints.
const shortDate = (iso) => (iso ? `${iso.slice(5, 7)}/${iso.slice(8, 10)}/${iso.slice(2, 4)}` : "");
const stamp = (iso) => new Date(iso).toLocaleDateString([], { month: "2-digit", day: "2-digit", year: "2-digit" });
const options = (values, selected) =>
  values.map((v) => `<option value="${escapeHtml(v)}"${v === selected ? " selected" : ""}>${escapeHtml(v)}</option>`).join("");

function readingHtml(reading, editable) {
  const note = reading.raw_note
    ? `<details class="wo-smr-note"><summary>Note</summary><p>${escapeHtml(reading.raw_note)}</p></details>`
    : "";
  const read = reading.hours_as_read === null || reading.hours_as_read === undefined ? "no hours" : hours(reading.hours_as_read);
  const edit = editable
    ? `<button type="button" class="secondary-btn" data-action="smr-edit-reading">Edit</button>`
    : "";
  return `<div class="wo-smr-reading" data-reading-id="${escapeHtml(reading.id)}" data-reading="${escapeHtml(JSON.stringify(reading))}">
            <div>
              <span class="wo-smr-reading-head"><span class="wo-smr-printing">Printing ${escapeHtml(reading.printing_no)}</span><strong>${escapeHtml(read)}</strong><span class="hint">as read</span></span>
              <span class="hint">${escapeHtml(shortDate(reading.work_date) || "undated")}</span>${note}
            </div>
            ${edit}
          </div>`;
}

// The one reading form serves add and edit; `dataset.readingId` says which.
export function fillReadingForm(form, reading) {
  const set = (cls, value) => { form.querySelector(`.${cls}`).value = value ?? ""; };
  form.dataset.readingId = reading?.id || "";
  set("wo-smr-r-printing", reading?.printing_no);
  set("wo-smr-r-date", reading?.work_date);
  set("wo-smr-r-hours", reading?.hours_as_read);
  set("wo-smr-r-note", reading?.raw_note);
  form.querySelector('[data-action="smr-add-reading"]').textContent = reading ? "Save reading" : "Add reading";
  form.querySelector('[data-action="smr-cancel-reading"]').hidden = !reading;
}

function workerLabel(line) {
  const name = line.worker_name || line.alias_on_paper || "Skilled Technician";
  return line.headcount > 1 ? `${name} ×${line.headcount}` : name;
}

// One line reads like a Labor entry: who and what kind on the left, the
// hours on the right, the day and vendor under the name. The note is the
// reviewer's working narrative: kept one tap away, never in the way.
function lineRowHtml(line, editable) {
  const when = line.work_date ? shortDate(line.work_date) : (line.week ? `Week ${line.week}` : "undated");
  const status = line.status === "charged" ? "" : `<span class="wo-smr-line-status">excluded: ${escapeHtml(line.exclusion_ground || "")}</span>`;
  const kind = line.kind === "field" ? "" : `<span class="wo-smr-line-kind wo-smr-line-kind--${escapeHtml(kindSlug(line.kind))}">${escapeHtml(kindLabel(line.kind))}</span>`;
  const note = line.note
    ? `<details class="wo-smr-line-note"><summary>note</summary><p>${escapeHtml(line.note)}</p></details>`
    : "";
  const total = line.headcount > 1 ? `${line.headcount} × ${hours(line.hours_each)}` : hours(line.hours_each);
  const buttons = editable && line.exclusion_ground !== "removed"
    ? `<div class="wo-labor-actions wo-smr-line-actions">
         <button type="button" class="secondary-btn" data-action="smr-edit-line">Edit</button>
         ${line.status === "charged"
           ? `<button type="button" class="btn-danger" data-action="smr-exclude-line">Exclude</button>`
           : `<button type="button" class="secondary-btn" data-action="smr-charge-line">Charge</button>`}
       </div>`
    : "";
  return `<div class="wo-labor-entry wo-smr-line wo-smr-line--${escapeHtml(line.status)}" data-line-id="${escapeHtml(line.id)}" data-line="${escapeHtml(JSON.stringify(line))}">
            <div>
              <span class="wo-smr-line-head"><strong>${escapeHtml(workerLabel(line))}</strong>${kind}</span>
              <span class="hint">${escapeHtml(when)} · ${escapeHtml(line.vendor)}</span>${status}${note}
            </div>
            <div class="wo-smr-line-side">
              <span class="wo-smr-line-hours">${escapeHtml(total)}</span>
              ${buttons}
            </div>
          </div>`;
}

// The add row, shaped like Labor's: a keyed name (blank = Skilled Technician), a
// headcount for a crew, hours each and the date. Everything else takes the
// line's defaults; Edit opens the full form.
function addLineRowHtml(detail) {
  const last = (detail.smr_lines || []).at(-1);
  return `<div class="wo-add-labor wo-smr-add">
    <label><span>Name on paper</span><input type="text" class="wo-smr-a-name" placeholder="blank = Skilled Technician"></label>
    <label><span>Headcount</span><input type="number" class="wo-smr-a-headcount" min="1" step="1" value="1"></label>
    <label><span>Hours each</span><input type="number" class="wo-smr-a-hours" min="0.5" step="0.5" placeholder="e.g. 2"></label>
    <label><span>Date</span><input type="date" class="wo-smr-a-date"></label>
    <label><span>Vendor</span><select class="wo-smr-a-vendor">${options(SMR_VENDORS, last?.vendor || "Belfor")}</select></label>
    <label><span>Reason</span><select class="wo-smr-a-kind">${SMR_KINDS.map((k) => `<option value="${escapeHtml(k)}">${escapeHtml(kindLabel(k))}</option>`).join("")}</select></label>
    <button type="button" data-action="smr-add-line">Add line</button>
  </div>`;
}

export function readAddLineRow(section) {
  const v = (cls) => section.querySelector(`.${cls}`).value.trim();
  const work_date = v("wo-smr-a-date") || null;
  return {
    reading_id: null,
    work_date,
    date_basis: "paper",
    vendor: v("wo-smr-a-vendor"),
    worker_id: null,
    alias_on_paper: v("wo-smr-a-name") || null,
    headcount: Number(v("wo-smr-a-headcount")) || 1,
    hours_each: v("wo-smr-a-hours"),
    kind: v("wo-smr-a-kind") || "field",
    reason_code: "as_read",
    // An undated line cannot charge (D10): it waits, excluded as undated,
    // and charges itself the moment a date lands on it.
    status: work_date ? "charged" : "excluded",
    exclusion_ground: work_date ? null : "undated",
    note: null,
    reason: "keyed from the paper",
  };
}

function lineFormHtml(detail) {
  const readings = (detail.smr_readings || [])
    .map((r) => `<option value="${escapeHtml(r.id)}">Printing ${escapeHtml(r.printing_no)}</option>`).join("");
  return `<div class="wo-smr-line-form" hidden>
    <label><span>Reading</span><select class="wo-smr-f-reading"><option value="">none</option>${readings}</select></label>
    <label><span>Date</span><input type="date" class="wo-smr-f-date"></label>
    <label><span>Date basis</span><select class="wo-smr-f-basis">${options(SMR_DATE_BASES, "paper")}</select></label>
    <label><span>Vendor</span><select class="wo-smr-f-vendor">${options(SMR_VENDORS, "Belfor")}</select></label>
    <label><span>Name on paper</span><input type="text" class="wo-smr-f-alias" placeholder="blank = Skilled Technician"></label>
    <label><span>Headcount</span><input type="number" class="wo-smr-f-headcount" min="1" step="1" value="1"></label>
    <label><span>Hours each</span><input type="number" class="wo-smr-f-hours" min="0.5" step="0.5"></label>
    <label><span>Kind</span><select class="wo-smr-f-kind">${options(SMR_KINDS, "field")}</select></label>
    <label><span>Reason code</span><select class="wo-smr-f-code">${options(SMR_REASON_CODES, "as_read")}</select></label>
    <label><span>Status</span><select class="wo-smr-f-status"><option value="charged">charged</option><option value="excluded">excluded</option></select></label>
    <label><span>Exclusion ground (optional)</span><select class="wo-smr-f-ground"><option value="">none</option>${options(SMR_GROUNDS)}</select></label>
    <label class="wo-smr-wide"><span>Note (prints under the line)</span><input type="text" class="wo-smr-f-note"></label>
    <label class="wo-smr-wide"><span>Why (kept in the line's history)</span><input type="text" class="wo-smr-f-reason" required></label>
    <div class="wo-smr-form-actions">
      <button type="button" data-action="smr-save-line">Save line</button>
      <button type="button" class="secondary-btn" data-action="smr-cancel-line">Cancel</button>
    </div>
  </div>`;
}

// Fill the shared form from a line (edit) or blank it (add). Exported for
// the actions module; a kind the select does not list is appended so an
// imported combined kind survives a round trip.
export function fillLineForm(form, line) {
  const set = (cls, value) => { form.querySelector(`.${cls}`).value = value ?? ""; };
  form.dataset.lineId = line?.id || "";
  set("wo-smr-f-reading", line?.reading_id);
  set("wo-smr-f-date", line?.work_date);
  set("wo-smr-f-basis", line?.date_basis || "paper");
  set("wo-smr-f-vendor", line?.vendor || "Belfor");
  set("wo-smr-f-alias", line?.alias_on_paper || line?.worker_name);
  set("wo-smr-f-headcount", line?.headcount ?? 1);
  set("wo-smr-f-hours", line?.hours_each);
  const kind = form.querySelector(".wo-smr-f-kind");
  if (line?.kind && ![...kind.options].some((o) => o.value === line.kind)) kind.add(new Option(line.kind, line.kind));
  kind.value = line?.kind || "field";
  set("wo-smr-f-code", line?.reason_code || "as_read");
  set("wo-smr-f-status", line?.status || "charged");
  set("wo-smr-f-ground", line?.exclusion_ground);
  set("wo-smr-f-note", line?.note);
  set("wo-smr-f-reason", "");
}

export function readLineForm(form) {
  const v = (cls) => form.querySelector(`.${cls}`).value.trim();
  return {
    reading_id: v("wo-smr-f-reading") || null,
    work_date: v("wo-smr-f-date") || null,
    date_basis: v("wo-smr-f-basis"),
    vendor: v("wo-smr-f-vendor"),
    alias_on_paper: v("wo-smr-f-alias") || null,
    headcount: Number(v("wo-smr-f-headcount")) || 1,
    hours_each: v("wo-smr-f-hours"),
    kind: v("wo-smr-f-kind"),
    reason_code: v("wo-smr-f-code"),
    status: v("wo-smr-f-status"),
    exclusion_ground: v("wo-smr-f-ground") || null,
    note: v("wo-smr-f-note") || null,
    reason: v("wo-smr-f-reason"),
  };
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
  const buttons = editable
    ? `<button type="button" data-action="smr-generate-block">Generate correction block</button>` +
      (block && !block.pasted_at
        ? `<button type="button" class="secondary-btn" data-action="smr-mark-pasted" data-block-id="${escapeHtml(block.id)}">Mark pasted to NetFacilities</button>`
        : "")
    : "";
  return `<div class="wo-smr-block"><p class="hint wo-smr-block-status">${escapeHtml(blockStatusText(block))}</p>${text}<div class="wo-smr-form-actions">${buttons}</div></div>`;
}

function totals(detail) {
  const charged = (detail.smr_lines || [])
    .filter((l) => l.status === "charged")
    .reduce((sum, l) => sum + Number(l.hours), 0);
  const billed = (detail.smr_legacy_labor_minutes || 0) / 60;
  return { charged, billed, change: charged - billed };
}

export function totalsText(detail) {
  const { charged, billed, change } = totals(detail);
  const money = detail.labor_total === null || detail.labor_total === undefined ? "" : ` · ${formatMoney(detail.labor_total)}`;
  return `Billed (NetFacilities) ${hours(billed)} · Corrected ${hours(charged)} · Change ${change >= 0 ? "+" : "-"}${hours(Math.abs(change))}${money}`;
}

// Four tiles: what NetFacilities billed, what the paper corrects it to, the
// difference (signed, colored), and the charge.
export function totalsHtml(detail) {
  const { charged, billed, change } = totals(detail);
  const tile = (label, value, cls = "") =>
    `<div class="wo-smr-stat${cls}"><span class="wo-smr-stat-label">${label}</span><span class="wo-smr-stat-value">${escapeHtml(value)}</span></div>`;
  const sign = change > 0 ? " wo-smr-stat--up" : change < 0 ? " wo-smr-stat--down" : "";
  const money = detail.labor_total === null || detail.labor_total === undefined ? "" : tile("Charge", formatMoney(detail.labor_total));
  return `<div class="wo-smr-totals" aria-label="${escapeHtml(totalsText(detail))}">
            ${tile("Billed (NetFacilities)", hours(billed))}
            ${tile("Corrected", hours(charged))}
            ${tile("Change", `${change >= 0 ? "+" : "-"}${hours(Math.abs(change))}`, sign)}
            ${money}
          </div>`;
}

// Ready for invoice (spec 2026-11-06): a person's stamp, offered only while
// the order has a dated line; a stamp on an order that lost its date is held.
export function readyRowHtml(detail, editable) {
  const stamp_ = detail.smr_ready;
  if (detail.smr_stage === "ready") {
    const who = stamp_?.by_name ? ` by ${stamp_.by_name}` : "";
    const text = `Ready for invoice · ${stamp(stamp_?.at)}${who}`;
    const btn = editable ? ` <button type="button" class="secondary-btn" data-action="smr-not-ready">Not ready</button>` : "";
    return `<p class="wo-smr-ready wo-smr-ready--ready">${escapeHtml(text)}${btn}</p>`;
  }
  if (detail.smr_stage === "dated") {
    return editable
      ? `<p class="wo-smr-ready"><button type="button" class="secondary-btn" data-action="smr-ready">Ready for invoice</button></p>`
      : `<p class="wo-smr-ready hint">Not yet ready for invoice</p>`;
  }
  const text = stamp_ ? "Ready stamp held until a line is dated" : "Date a line to mark ready";
  return `<p class="wo-smr-ready hint">${text}</p>`;
}

export function smrSectionHtml(detail) {
  if (!detail?.smr) return "";
  const editable = canEditSmrLines();
  const readings = (detail.smr_readings || []).map((r) => readingHtml(r, editable)).join("") || `<p class="hint">No paper read yet.</p>`;
  const rows = (detail.smr_lines || []).map((line) => lineRowHtml(line, editable)).join("");
  const table = `<div class="wo-labor-list wo-smr-lines">${rows || `<p class="hint">No correction lines.</p>`}</div>`;
  const readingForm = editable
    ? `<div class="wo-smr-reading-form">
         <label><span>Printing</span><input type="number" class="wo-smr-r-printing" min="1" step="1"></label>
         <label><span>Date</span><input type="date" class="wo-smr-r-date"></label>
         <label><span>Hours as read</span><input type="number" class="wo-smr-r-hours" min="0" step="0.5"></label>
         <label class="wo-smr-wide"><span>Note from the paper</span><input type="text" class="wo-smr-r-note"></label>
         <button type="button" class="secondary-btn" data-action="smr-add-reading">Add reading</button>
         <button type="button" class="secondary-btn" data-action="smr-cancel-reading" hidden>Cancel</button>
       </div>`
    : "";
  const addLine = editable ? addLineRowHtml(detail) : "";
  return `<details class="wo-section-card wo-smr-section" open>
            <summary class="wo-section-summary">Paper corrections</summary>
            <div class="wo-section-content">
              <div class="wo-smr-readings">${readings}</div>
              ${readingForm}
              ${table}
              ${addLine}
              ${editable ? lineFormHtml(detail) : ""}
              ${totalsHtml(detail)}
              ${readyRowHtml(detail, editable)}
              ${blockHtml(detail, editable)}
            </div>
          </details>`;
}
