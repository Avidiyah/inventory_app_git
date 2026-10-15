// Pure week helpers shared by the Admin week surfaces (Hours grid, user
// profile). No DOM, no fetch. Dates are ISO `YYYY-MM-DD` Mondays computed in
// UTC so a viewer's zone cannot move the week boundary.

// `8:00`, not format.js's `8 h 0 m`: a column of hours reads as clock times.
export function formatHm(totalMinutes) {
  const minutes = Math.max(0, Math.round(Number(totalMinutes) || 0));
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
}

export function isoDate(iso) {
  return new Date(`${iso}T00:00:00Z`);
}

export function weekLabel(start, end) {
  const options = { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" };
  return `${isoDate(start).toLocaleDateString([], options)} – ${isoDate(end).toLocaleDateString([], options)}`;
}

export function shiftMonday(iso, days) {
  const monday = isoDate(iso);
  monday.setUTCDate(monday.getUTCDate() + days);
  return monday.toISOString().slice(0, 10);
}

const CENTRAL_TIME_ZONE = "America/Chicago";

export function timeLabel(instant) {
  return new Date(instant).toLocaleTimeString([], {
    hour: "numeric", minute: "2-digit", timeZone: CENTRAL_TIME_ZONE,
  });
}

// `7:02 AM – 3:30 PM, 4:00 PM – running` for a list of {started_at, ended_at}.
export function spanList(spans) {
  return spans.map((s) => `${timeLabel(s.started_at)} – ${s.ended_at ? timeLabel(s.ended_at) : "running"}`).join(", ");
}
