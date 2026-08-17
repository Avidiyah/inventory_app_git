// Foundation: role hierarchy mirror for client-side UI gating.
//
// Layer: foundation (no DOM, no fetch, no state). This is the frontend
// twin of `app/domain/roles.py`. It exists ONLY to decide what to show
// or hide -- the backend remains the real authority and re-checks every
// request. Keep the rank values and labels in sync with the Python module;
// tests/test_role_mirror_parity.py enforces it.

export const ROLE_RANK = {
  technician: 0,
  supervisor: 1,
  techfm_oa: 2,
  admin: 3,
  owner: 4,
};

// All roles, most-senior first.
export const ALL_ROLES = ["owner", "admin", "techfm_oa", "supervisor", "technician"];

// Human-facing names. Everything else in the UI used to capitalise the raw
// slug, which cannot produce "TechFM OA", so the mapping is explicit here and
// `roleLabel` is the single way to render a role. Mirrors ROLE_LABELS in
// app/domain/roles.py; the pair is pinned by tests/test_role_mirror_parity.py.
export const ROLE_LABELS = {
  owner: "Owner",
  admin: "Admin",
  techfm_oa: "TechFM OA",
  supervisor: "Supervisor",
  technician: "Technician",
};

// Human-facing name for `role`. An unrecognised value comes back unchanged
// rather than blank, so a stale account still renders something readable; a
// missing one says so, because the Tools custody card concatenates this into
// "<role> · <created>" and a blank would leave a dangling separator.
export function roleLabel(role) {
  return ROLE_LABELS[role] || role || "Unknown role";
}

function rank(role) {
  return role in ROLE_RANK ? ROLE_RANK[role] : -1;
}

// True if `role` has at least the authority of `minimum`.
export function roleAtLeast(role, minimum) {
  return rank(role) >= rank(minimum);
}

// Operational Work Order assignment eligibility mirrors app/domain/roles.py.
// Owner retains full authority but is not an assignment target. TechFM OA is
// a routing choice for the same reason Admin is.
export function canBeWorkOrderSupervisor(role) {
  return role === "admin" || role === "techfm_oa" || role === "supervisor";
}

export function canBeWorkOrderTechnician(role) {
  return role === "supervisor" || role === "technician";
}

// True if an actor may create/reset/delete a user holding `targetRole`.
export function canManage(actorRole, targetRole) {
  return rank(actorRole) > rank(targetRole) && targetRole in ROLE_RANK;
}

// Roles an actor may assign when creating a user, most-senior first.
export function assignableRoles(actorRole) {
  const actorRank = rank(actorRole);
  return ALL_ROLES.filter(r => ROLE_RANK[r] < actorRank);
}
