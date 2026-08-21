// View: the Priorities card at the top of the User Hub Dashboard tab.
//
// Layer: views. Renders inside the Dashboard tab body, above the personal
// counts tiles hubTechnician.js draws. Every role gets one card, but its
// shape differs: a Technician sees one number (assigned to them); a
// Supervisor or Admin+ viewer sees two (assigned within their scope,
// unassigned within their scope). Consumes whichever of the personal/crew/
// admin payloads userHub.js has already fetched; makes no requests of its
// own.

import { escapeHtml } from "../format.js";
import { roleAtLeast } from "../roles.js";

function tileHtml(label, value, sub) {
  return `
    <section class="hub-tile">
      <p class="hub-tile-label">${escapeHtml(label)}</p>
      <p class="hub-tile-value">${escapeHtml(String(value))}</p>
      ${sub ? `<p class="hub-tile-sub">${escapeHtml(sub)}</p>` : ""}
    </section>`;
}

// Supervisor and Admin+ share this two-tile shape; only the source payload
// and the "your crew" / "company-wide" wording differ.
function scopedHtml(priority, scopeLabel) {
  return `
    <div class="hub-tile-grid">
      ${tileHtml(`High priority — ${scopeLabel}`, priority.assigned, "")}
      ${tileHtml("High priority — unassigned", priority.unassigned, priority.unassigned ? "needs a technician" : "")}
    </div>`;
}

export function mountHubPriorities(container, { role, personal, crew, admin } = {}) {
  if (!container) return;
  const isAdminPlus = roleAtLeast(role, "techfm_oa");
  const isSupervisor = role === "supervisor";

  let body;
  if (isAdminPlus) {
    // Company-wide (admin_hub), not the viewer's own led set -- an
    // Admin/Owner/TechFM OA may also be routed as a supervisor on some work
    // orders, but the card's promise for this role tier is company-wide.
    if (!admin) {
      container.innerHTML = "";
      return;
    }
    body = scopedHtml(admin, "company-wide");
  } else if (isSupervisor) {
    if (!crew) {
      container.innerHTML = "";
      return;
    }
    body = scopedHtml(crew, "your crew");
  } else {
    if (!personal) {
      container.innerHTML = "";
      return;
    }
    body = `<div class="hub-tile-grid">${tileHtml("High priority — assigned to you", personal.assigned, "")}</div>`;
  }

  container.innerHTML = `<section class="hub-priorities"><p class="hub-tile-label">Priorities</p>${body}</section>`;
}
