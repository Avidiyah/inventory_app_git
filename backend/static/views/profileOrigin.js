// The remembered hand-off from a crew member's profile to one work order, so
// the solo card's Back can return to that profile at that week (spec
// 2026-10-15-profile-day-cards-and-timesheet-links-design.md, E8).
//
// Layer: views (shared state, no DOM). Module-level and consumed once by the
// Back control; a nav click or logout clears it so a stale origin can never
// hijack a later Back. `{ page: "users" | "user-hub", userId, week }`.

let origin = null;

export function setProfileOrigin(next) { origin = next; }
export function peekProfileOrigin() { return origin; }
export function takeProfileOrigin() {
  const taken = origin;
  origin = null;
  return taken;
}
export function clearProfileOrigin() { origin = null; }
