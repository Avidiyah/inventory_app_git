// View: the Supervisor hub's crew board.
//
// Layer: views. Renders inside the Dashboard tab body, below the personal
// tiles `hubTechnician.js` already drew (spec §5.3: P3a adds no new tab).
// Consumes exactly the `GET /hub/crew` payload `userHub.js` fetches for
// supervisor+ viewers; makes no requests of its own.
//
// Running-session minutes are computed once, against the payload's own
// `server_now`, rather than ticked live on a 1-second interval the way the
// clock widget's own hero figure is. A crew card's elapsed time only needs
// to be "as fresh as the last board refresh" -- the board already refetches
// on `labor.session.changed`, on reconnect, and on a 60-second safety timer
// (userHub.js), which is a materially different freshness bar than "the
// number I am personally staring at while it climbs."

import { escapeHtml } from "../format.js";
import { tipHtml } from "../tooltip.js";

function formatHm(totalMinutes) {
  const minutes = Math.max(0, Math.round(totalMinutes));
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m} m`;
  return `${h} h ${m} m`;
}

function tileHtml(label, value, sub) {
  return `
    <section class="hub-tile">
      <p class="hub-tile-label">${escapeHtml(label)}</p>
      <p class="hub-tile-value">${escapeHtml(String(value))}</p>
      ${sub ? `<p class="hub-tile-sub">${escapeHtml(sub)}</p>` : ""}
    </section>`;
}

function rollUpsHtml(payload, { isAdminPlus = false } = {}) {
  const tiles = [
    tileHtml(
      "Work orders I lead",
      payload.led.total,
      payload.led.in_progress ? `${payload.led.in_progress} in progress` : ""
    ),
  ];
  // "Crew on the clock" is dropped for techfm_oa+ viewers -- the new
  // company-wide Supervisor Time / Technician Time tiles (hubAdmin.js)
  // supersede it for that role tier.
  if (!isAdminPlus) {
    tiles.push(tileHtml("Crew on the clock", `${payload.crew_on_clock} of ${payload.crew_total}`, ""));
  }
  tiles.push(
    tileHtml(
      "Crew time today",
      formatHm(payload.crew_minutes_today),
      payload.crew_on_clock ? "ticking" : ""
    )
  );
  return `<div class="hub-tile-grid">${tiles.join("")}</div>`;
}

function attentionHtml(attention) {
  if (!attention.length) return "";
  const rows = attention
    .map(
      (item) =>
        `<li class="hub-attention-row"><span class="hub-attention-icon" aria-hidden="true">⚠</span><span>${escapeHtml(item.subject)} — ${escapeHtml(item.detail)}</span></li>`
    )
    .join("");
  return `
    <section class="hub-attention">
      <p class="hub-tile-label">⚠ Needs attention${tipHtml("hub.attention")} <span class="hub-tile-count">${attention.length}</span></p>
      <ul class="hub-attention-list">${rows}</ul>
    </section>`;
}

// D11: the label is "Last worked", not "Last seen" -- sessions are the only
// source, never a union across notes/materials/transactions.
function lastWorkedText(lastWorked) {
  if (!lastWorked) return "Never";
  return new Date(lastWorked).toLocaleString([], {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

// `domain/hub.py`'s flag vocabulary, rendered as a short word -- never color
// alone (spec §8). Anything not in this map still renders (readable snake
// case) rather than disappearing, so a future flag is visible immediately.
const FLAG_LABELS = {
  long_session: "long session",
  approaching_cap: "approaching cap",
  assigned_idle: "idle",
};

function flagsHtml(flags) {
  if (!flags.length) return "";
  const badges = flags
    .map((flag) => `<span class="hub-crew-flag">⚠ ${escapeHtml(FLAG_LABELS[flag] || flag.replace(/_/g, " "))}</span>`)
    .join("");
  return `<p class="hub-crew-flags">${badges}</p>`;
}

function technicianCardHtml(tech, serverNow) {
  const session = tech.running_session;
  const onClock = Boolean(session);
  const name = `${tech.user.first_name || ""} ${tech.user.last_name || ""}`.trim() || "Unknown";
  const subjectHtml = onClock
    ? `<p class="hub-crew-subject">WO ${escapeHtml(session.number)}</p>
       <p class="hub-crew-running">running ${escapeHtml(
         formatHm((new Date(serverNow).getTime() - new Date(session.started_at).getTime()) / 60000)
       )}</p>`
    : `<p class="hub-crew-subject">Last worked ${escapeHtml(lastWorkedText(tech.last_worked))}</p>`;

  return `
    <article class="hub-crew-card${onClock ? " hub-crew-card-on" : ""}">
      <p class="hub-crew-status">
        <span class="hub-crew-dot${onClock ? " hub-crew-dot-on" : ""}" aria-hidden="true"></span>
        <span class="hub-crew-name">${escapeHtml(name)}</span>
        <span class="hub-crew-clock-label">${onClock ? "ON CLOCK" : "OFF CLOCK"}</span>
      </p>
      ${subjectHtml}
      <p class="hub-crew-today">Today <strong>${escapeHtml(formatHm(tech.minutes_today))}</strong></p>
      <p class="hub-crew-counts">Assigned ${tech.assigned} · In-prog ${tech.in_progress} · Ready ${tech.ready_to_complete}</p>
      ${flagsHtml(tech.flags)}
    </article>`;
}

function crewHtml(payload) {
  if (!payload.technicians.length) {
    return `
      <section class="hub-crew">
        <p class="hub-tile-label">My crew${tipHtml("hub.crew")}</p>
        <p class="hint">No one is currently routed to you. Your crew appears here once a work order is assigned under your supervision.</p>
      </section>`;
  }
  return `
    <section class="hub-crew">
      <p class="hub-tile-label">My crew${tipHtml("hub.crew")}</p>
      <div class="hub-crew-grid">
        ${payload.technicians.map((tech) => technicianCardHtml(tech, payload.server_now)).join("")}
      </div>
    </section>`;
}

export function mountHubCrew(container, payload, { isAdminPlus = false } = {}) {
  container.innerHTML = rollUpsHtml(payload, { isAdminPlus }) + attentionHtml(payload.attention) + crewHtml(payload);
}
