// View helper: the SMR page's read-only Hours tab (spec 2026-11-04 D3).
//
// Layer: views (leaf under smr.js). Hours by worker × week and by vendor ×
// week from the paper-correction lines only, each cell "charged / excluded";
// a CSV download of the same table. Admin+; smr.js shows and hides the
// panel, this module fills it on demand.

import { apiSmrHours, apiSmrHoursCsv } from "../api.js";
import { setMessage } from "../dom.js";
import { escapeHtml, friendlyError } from "../format.js";

const panel = document.getElementById("smr-hours");
const message = document.getElementById("smr-message");
const csvBtn = document.getElementById("smr-hours-csv-btn");

const hours = (value) => (Number(value) || 0).toFixed(1);

function weekHeader(week, rows) {
  if (week === null) return "NO WEEK";
  const label = rows.find((r) => r.week === week)?.week_label || `Week ${week}`;
  return label.toUpperCase();
}

// One table: a row per name, a column per week, cells "charged / excluded",
// a TOTAL column and a TOTAL row (charged lines only count toward TOTAL).
function tableHtml(title, rows, weeks) {
  const names = [...new Map(rows.map((r) => [`${r.vendor}\u0000${r.name}`, r])).values()];
  const cell = (r) => (r ? `${hours(r.charged_hours)} / ${hours(r.excluded_hours)}` : "");
  const sum = (list, key) => list.reduce((acc, r) => acc + (Number(r[key]) || 0), 0);
  const head = ["NAME", "VENDOR", ...weeks.map((w) => weekHeader(w, rows)), "TOTAL"];
  const body = names.map((who) => {
    const mine = rows.filter((r) => r.vendor === who.vendor && r.name === who.name);
    return [
      who.name, who.vendor,
      ...weeks.map((w) => cell(mine.find((r) => r.week === w))),
      `${hours(sum(mine, "charged_hours"))} / ${hours(sum(mine, "excluded_hours"))}`,
    ];
  });
  const foot = [
    "TOTAL", "",
    ...weeks.map((w) => cell({ charged_hours: sum(rows.filter((r) => r.week === w), "charged_hours"), excluded_hours: sum(rows.filter((r) => r.week === w), "excluded_hours") })),
    `${hours(sum(rows, "charged_hours"))} / ${hours(sum(rows, "excluded_hours"))}`,
  ];
  const tr = (cells, tag = "td") => `<tr>${cells.map((c) => `<${tag}>${escapeHtml(String(c))}</${tag}>`).join("")}</tr>`;
  return `<h3 class="smr-hours-title">${escapeHtml(title)}</h3>
    <table class="smr-hours-table"><thead>${tr(head, "th")}</thead><tbody>${body.map((r) => tr(r)).join("")}</tbody><tfoot>${tr(foot)}</tfoot></table>`;
}

export function hoursHtml(data) {
  const rows = data.rows || [];
  const weeks = data.weeks || [];
  if (!rows.length) return `<p class="smr-empty">NO LINES YET. HOURS APPEAR ONCE PAPER LINES ARE KEYED.</p>`;
  return `<p class="smr-hours-note">CHARGED / EXCLUDED HOURS PER MON–SUN WEEK, FROM PAPER LINES ONLY · TOTAL ${hours(data.charged_hours)} / ${hours(data.excluded_hours)}</p>`
    + tableHtml("BY WORKER", rows.filter((r) => r.group === "worker"), weeks)
    + tableHtml("BY VENDOR", rows.filter((r) => r.group === "vendor"), weeks);
}

export async function loadSmrHours() {
  if (!panel) return;
  panel.innerHTML = `<p class="smr-empty">LOADING…</p>`;
  try {
    panel.innerHTML = hoursHtml(await apiSmrHours());
  } catch (err) {
    panel.innerHTML = "";
    setMessage(message, friendlyError(err, "Could not load the Hours table."), "error");
  }
}

if (csvBtn) {
  csvBtn.addEventListener("click", async () => {
    csvBtn.disabled = true;
    try {
      const { blob, filename } = await apiSmrHoursCsv();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
      setMessage(message, `DOWNLOADED ${filename}`, "success");
    } catch (err) {
      setMessage(message, friendlyError(err, "Could not download the Hours CSV."), "error");
    } finally {
      csvBtn.disabled = false;
    }
  });
}
