// The one rule for tutorial scripts: every page in tutorials/index.js is
// mounted on its own sample for every role that can open it, and every step
// target must show for at least one role. House-rule limits and the reserved
// sample id prefix are checked here too. A UI change that breaks a tutorial
// fails this file.

import { afterEach, describe, expect, it } from "vitest";
import { bootApp } from "../helpers/app.js";
import { restoreBrowserStubs, stubScrollIntoView } from "../helpers/browserStubs.js";
import { workOrderCard, workOrderDetail } from "../helpers/factories.js";
import { TUTORIALS } from "../../../backend/static/tutorials/index.js";
import { ALL_ROLES, ROLE_RANK, roleAtLeast } from "../../../backend/static/roles.js";
import { restoreRects, stubRects, walkWaits } from "../helpers/starterWalkWaits.js";

const ROLES = ["technician", "supervisor", "techfm_oa", "admin", "owner"];
const PREFIX = "ffffffff-ffff-4fff-8fff-";
const PAGES = Object.keys(TUTORIALS).filter((p) => TUTORIALS[p].sample);
const lines = (v) => (Array.isArray(v) ? v : [v]);

function sampleIds(body, viewerId, out = []) {
  if (Array.isArray(body)) body.forEach((b) => sampleIds(b, viewerId, out));
  else if (body && typeof body === "object") {
    for (const [k, v] of Object.entries(body)) {
      if (k === "id" || k.endsWith("_id")) { if (typeof v === "string" && v !== viewerId) out.push(v); }
      else if (k.endsWith("_ids") && Array.isArray(v)) out.push(...v.filter((x) => x !== viewerId));
      else sampleIds(v, viewerId, out);
    }
  }
  return out;
}

it("the tutorial index is not empty", () => {
  expect(PAGES.length).toBeGreaterThan(0);
});

describe.each(PAGES)("tutorials for %s", (page) => {
  const entry = TUTORIALS[page];

  it("scripts keep the house rules", () => {
    const keys = new Set();
    for (const s of entry.scripts) {
      expect(s.key).toMatch(new RegExp(`^${page}\\.[a-z0-9.-]+$`));
      expect(keys.has(s.key), `duplicate key ${s.key}`).toBe(false);
      keys.add(s.key);
      expect(typeof s.title).toBe("string");
      expect(s.steps.length).toBeLessThanOrEqual(8);
      if (s.here !== undefined) expect(typeof s.here).toBe("string");
      if (s.minRole !== undefined) expect(ROLES).toContain(s.minRole);
      for (const o of s.open || []) expect(typeof o).toBe("string");
      for (const step of s.steps) {
        const values = [step.text, ...Object.values(step.textFor || {})];
        for (const r of Object.keys(step.textFor || {})) expect(ROLES).toContain(r);
        for (const v of values) {
          expect(lines(v).length, `${s.key} ${step.target}`).toBeLessThanOrEqual(3);
          for (const line of lines(v)) {
            expect(line.length, line).toBeLessThanOrEqual(120);
            expect(line.replace(/\b[ap]\.m\./gi, "am").split(/[.!?]+(?=\s+[A-Z0-9"]|\s*$)/).filter(Boolean).length, `one sentence: ${line}`).toBe(1);
          }
        }
      }
    }
  });

  it("every step target shows for some role, and every script for every role", async () => {
    stubScrollIntoView();
    const tut0 = await import("../../../backend/static/tutorial.js");
    void tut0;
    const seen = new Set();
    // One boot per role. The Owner boot also yields PAGE_ACCESS and is reused:
    // a second back-to-back Owner boot races the first one's late responses.
    const first = await bootApp({ role: "owner", page });
    const roles = first.nav.PAGE_ACCESS[page];
    for (const role of roles) {
      const { nav, currentUser } = role === "owner" ? first : await bootApp({ role, page });
      const tut = await import("../../../backend/static/tutorial.js");
      const api = await import("../../../backend/static/api.js");
      const body = entry.sample(currentUser);
      expect(sampleIds(body, currentUser.id).filter((id) => !id.startsWith(PREFIX))).toEqual([]);
      // Let the boot's own page load land first, or it overwrites the sample render.
      await new Promise((r) => setTimeout(r, 300));
      api.setSampleResponder(tut.makeResponder(body));
      const { roleAtLeast } = await import("../../../backend/static/roles.js");
      for (const script of entry.scripts) {
        if (script.minRole && !roleAtLeast(role, script.minRole)) continue;
        nav.showPage(page);
        await new Promise((r) => setTimeout(r, 400)); // let the page reload land
        const reached = await tut.runOpen(script, role);
        const visible = tut.visibleSteps(script, role);
        expect(reached && visible.length > 0, `${script.key} has no visible step for ${role}`).toBe(true);
        visible.forEach(({ step }) => seen.add(step.target));
      }
      api.setSampleResponder(null);
    }
    restoreBrowserStubs();
    const unseen = entry.scripts.flatMap((s) => s.steps.map((st) => st.target)).filter((t) => !seen.has(t));
    expect(unseen, "targets never visible for any role").toEqual([]);
  }, 60000);
});

describe("starter scripts", () => {
  const entry = TUTORIALS.starter;
  const KEYS = ["starter.menu", "starter.inventory", "starter.field", "starter.people", "starter.review"];
  const GROUP = { "starter.inventory": "inventory", "starter.field": "field", "starter.people": "people", "starter.review": "review" };
  const OVERVIEW = ["#main-nav", "#auth-user-indicator", "#logout-btn"];
  const sentences = (l) => l.split(/[.!?]+(\s|$)/).filter((x) => x && x.trim() && !/^\s*$/.test(x)).length;
  afterEach(() => restoreRects());

  it("is registered as a page-less entry with sample:false scripts", () => {
    expect(entry, "starter missing from the index").toBeTruthy();
    expect(entry.sample).toBeUndefined();
    expect(entry.scripts.map((s) => s.key)).toEqual(KEYS);
    for (const s of entry.scripts) {
      expect(s.sample, s.key).toBe(false);
      expect(s.open, s.key).toBeUndefined();
      expect(s.here, s.key).toBeUndefined();
    }
  });

  it("keeps the data rules", () => {
    expect(entry, "starter missing from the index").toBeTruthy();
    for (const s of entry.scripts) {
      expect(s.steps.length, s.key).toBeLessThanOrEqual(8);
      for (const step of s.steps) {
        if (step.waitTap) {
          expect(step.waitTap).toMatch(/^\.nav-btn\[data-page="[a-z-]+"\]$/);
          if (step.via) expect(step.via).toMatch(/^\[data-nav-group="[a-z]+"\] \.nav-group-toggle$/);
          if (step.via) expect(sentences(step.viaText), `${s.key} viaText`).toBe(1);
          expect(lines(step.text).length, `${s.key} wait text`).toBe(1);
          expect(sentences(step.text), `${s.key} wait text`).toBe(1);
        } else {
          const page = (step.target.match(/^#([a-z-]+)-page$/) || [])[1];
          expect(OVERVIEW.includes(step.target) || !!page, `${s.key} target ${step.target}`).toBe(true);
        }
        for (const v of [step.text, ...Object.values(step.textFor || {})]) {
          expect(lines(v).length, s.key).toBeLessThanOrEqual(3);
          for (const line of lines(v)) {
            expect(line.length, line).toBeLessThanOrEqual(120);
            expect(sentences(line), `one sentence: ${line}`).toBe(1);
          }
        }
      }
    }
  });

  it("every role from minRole up walks every starter on the real nav", async () => {
    expect(entry, "starter missing from the index").toBeTruthy();
    stubScrollIntoView();
    for (const role of ROLES) {
      const { nav } = await bootApp({ role });
      stubRects();
      for (const s of entry.scripts) {
        const group = GROUP[s.key];
        const buttons = group
          ? [...document.querySelectorAll(`[data-nav-group="${group}"] .nav-btn:not([hidden])`)].map((b) => b.dataset.page).filter((p) => !p.startsWith("smr"))
          : [];
        if (s.minRole && !roleAtLeast(role, s.minRole)) {
          expect(buttons, `${s.key} offered to ${role}`).toEqual([]);
          continue;
        }
        expect(walkWaits(s, role, nav.canAccessPage), `${s.key} as ${role}`).toEqual(group ? buttons : ["saved-items"]);
      }
      restoreRects();
    }
    restoreBrowserStubs();
  }, 60000);
});

describe("catalogue rules across all pages", () => {
  it("minRole is not below the page minimum; a starter (no page) is exempt", async () => {
    const { nav } = await bootApp({ role: "owner" });
    const { pageMinRole } = await import("../../../backend/static/tutorials/relevance.js");
    const PAGE_ACCESS = nav.PAGE_ACCESS;
    for (const [page, { scripts }] of Object.entries(TUTORIALS)) {
      for (const s of scripts) {
        if (!s.minRole || !PAGE_ACCESS[page]) continue;
        expect(ROLE_RANK[s.minRole], `${s.key} minRole below the page minimum`).toBeGreaterThanOrEqual(ROLE_RANK[pageMinRole(page)]);
      }
    }
  });
  it("PAGE_ACCESS lists a contiguous top slice of the roles", async () => {
    const { nav } = await bootApp({ role: "owner" });
    for (const [page, roles] of Object.entries(nav.PAGE_ACCESS)) {
      expect(roles, page).toEqual(ALL_ROLES.slice(0, roles.length));
    }
  });
  it("keys are unique across pages and fit the server key rule", () => {
    const seen = new Set();
    for (const { scripts } of Object.values(TUTORIALS)) {
      for (const { key } of scripts) {
        expect(key).toMatch(/^[a-z0-9][a-z0-9.-]{0,79}$/);
        expect(seen.has(key), `duplicate key ${key}`).toBe(false);
        seen.add(key);
      }
    }
  });
});

describe("work-orders sample shapes", () => {
  it("cards and details carry every API field", () => {
    const body = TUTORIALS["work-orders"].sample({ id: "v", role: "technician", full_name: "V" });
    const cardKeys = Object.keys(workOrderCard());
    const detailKeys = Object.keys(workOrderDetail());
    for (const c of body["GET /work-orders/"]) {
      expect(Object.keys(c)).toEqual(expect.arrayContaining(cardKeys));
      expect(Object.keys(body[`GET /work-orders/${c.id}`])).toEqual(expect.arrayContaining(detailKeys));
    }
  });
});
