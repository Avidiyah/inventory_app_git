// Who a tutorial is for (0b spec 5.4). Layer: pure helpers over PAGE_ACCESS and
// roles.js; used by the red dot, the Hub tab and the Users counts.
//
// An entry is the catalogue shape { page, key, title, minRole? }. A "starter"
// entry has no page in PAGE_ACCESS: its audience is its minRole alone.

import { PAGE_ACCESS } from "../views/nav.js";
import { ROLE_RANK, roleAtLeast, roleLabel } from "../roles.js";

// Lowest-ranked role PAGE_ACCESS lists for the page; null for an unknown page.
export function pageMinRole(page) {
  const roles = PAGE_ACCESS[page];
  if (!roles?.length) return null;
  return roles.reduce((lo, r) => (ROLE_RANK[r] < ROLE_RANK[lo] ? r : lo));
}

export function relevant(entry, role) {
  if (!(role in ROLE_RANK)) return false;
  const pageRoles = PAGE_ACCESS[entry.page];
  if (pageRoles ? !pageRoles.includes(role) : !entry.minRole) return false;
  return !entry.minRole || roleAtLeast(role, entry.minRole);
}

// "Everyone", else "<Role label> and above" for the higher of page minimum and minRole.
export function audienceLabel(entry) {
  const lo = pageMinRole(entry.page);
  const min = entry.minRole && (!lo || ROLE_RANK[entry.minRole] > ROLE_RANK[lo]) ? entry.minRole : lo;
  return !min || min === "technician" ? "Everyone" : `${roleLabel(min)} and above`;
}
