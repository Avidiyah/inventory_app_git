// Foundation: role hierarchy mirror for client-side UI gating.
//
// Layer: foundation (no DOM, no fetch, no state). This is the frontend
// twin of `app/domain/roles.py`. It exists ONLY to decide what to show
// or hide -- the backend remains the real authority and re-checks every
// request. Keep the rank values in sync with the Python module.

export const ROLE_RANK = {
  technician: 0,
  supervisor: 1,
  admin: 2,
  owner: 3,
};

// All roles, most-senior first.
export const ALL_ROLES = ["owner", "admin", "supervisor", "technician"];

function rank(role) {
  return role in ROLE_RANK ? ROLE_RANK[role] : -1;
}

// True if `role` has at least the authority of `minimum`.
export function roleAtLeast(role, minimum) {
  return rank(role) >= rank(minimum);
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
