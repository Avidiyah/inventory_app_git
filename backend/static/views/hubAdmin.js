// View: the Admin+ hub's company-wide time summary.
//
// Layer: views. Renders inside the Dashboard tab body, above the crew
// board mount point `hubTechnician.js` already draws. Consumes exactly the
// `GET /hub/admin` payload `userHub.js` fetches for techfm_oa+ viewers;
// makes no requests of its own.

import { escapeHtml } from "../format.js";

function formatHm(totalMinutes) {
  const minutes = Math.max(0, Math.round(totalMinutes));
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m} m`;
  return `${h} h ${m} m`;
}

function tileHtml(label, value) {
  return `
    <section class="hub-tile">
      <p class="hub-tile-label">${escapeHtml(label)}</p>
      <p class="hub-tile-value">${escapeHtml(value)}</p>
    </section>`;
}

export function mountHubAdminSummary(container, payload) {
  container.innerHTML = `
    <div class="hub-tile-grid">
      ${tileHtml("Supervisor Time", formatHm(payload.supervisor_minutes_today))}
      ${tileHtml("Technician Time", formatHm(payload.technician_minutes_today))}
    </div>`;
}
