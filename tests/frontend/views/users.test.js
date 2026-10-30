// Characterization coverage for views/users.js: what `loadUsers` fetches and
// paints, the role-gated row-action matrix, the two <select> populators, and
// the create form.
//
// The five row actions and their overlays are in usersActions.test.js.
// `users.js` imports nothing from `views/`, so the fixture is a plain
// `mountView` -- no graph priming, unlike Items and Tools.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import {
  actionsIn, cells, el, historyOptions, mountUsers, openUsers, requestFor,
  requests, restoreUsers, roleOptions, rowFor, rows, search, scopeBtn, showScope,
} from "../helpers/users.js";
import { personWeek, user as userFactory } from "../helpers/factories.js";

afterEach(() => restoreUsers());

const ROLES = ["owner", "admin", "techfm_oa", "supervisor", "technician"];

// The frozen row-action matrix, read off the running code. Rows are the actor;
// columns the target; each cell the menu options that render, IN ORDER (Edit
// Details, Edit Role, then the lifecycle pair). An empty list renders the
// `<span class="empty">—</span>` placeholder instead of an action menu.
//
// The shape worth reading twice: a Supervisor acting on a Technician gets Edit
// Details, Reset Password and Archive but NOT Edit Role -- role changes are
// gated at techfm_oa on top of the usual outranks rule.
const MATRIX = {
  owner: {
    owner: { active: [], archived: [] },
    admin: { active: ["edit-details", "edit-role", "reset-password", "archive"], archived: ["edit-details", "restore"] },
    techfm_oa: { active: ["edit-details", "edit-role", "reset-password", "archive"], archived: ["edit-details", "restore"] },
    supervisor: { active: ["edit-details", "edit-role", "reset-password", "archive"], archived: ["edit-details", "restore"] },
    technician: { active: ["edit-details", "edit-role", "reset-password", "archive"], archived: ["edit-details", "restore"] },
  },
  admin: {
    owner: { active: [], archived: [] },
    admin: { active: [], archived: [] },
    techfm_oa: { active: ["edit-details", "edit-role", "reset-password", "archive"], archived: ["edit-details", "restore"] },
    supervisor: { active: ["edit-details", "edit-role", "reset-password", "archive"], archived: ["edit-details", "restore"] },
    technician: { active: ["edit-details", "edit-role", "reset-password", "archive"], archived: ["edit-details", "restore"] },
  },
  techfm_oa: {
    owner: { active: [], archived: [] },
    admin: { active: [], archived: [] },
    techfm_oa: { active: [], archived: [] },
    supervisor: { active: ["edit-details", "edit-role", "reset-password", "archive"], archived: ["edit-details", "restore"] },
    technician: { active: ["edit-details", "edit-role", "reset-password", "archive"], archived: ["edit-details", "restore"] },
  },
  supervisor: {
    owner: { active: [], archived: [] },
    admin: { active: [], archived: [] },
    techfm_oa: { active: [], archived: [] },
    supervisor: { active: [], archived: [] },
    technician: { active: ["edit-details", "reset-password", "archive"], archived: ["edit-details", "restore"] },
  },
  technician: {
    owner: { active: [], archived: [] },
    admin: { active: [], archived: [] },
    techfm_oa: { active: [], archived: [] },
    supervisor: { active: [], archived: [] },
    technician: { active: [], archived: [] },
  },
};

// Ten rows: every role once active and once archived, named so `rowFor` can
// find them.
const matrixRoster = () => ROLES.flatMap((role) => [
  userFactory({ username: `${role}-active`, role }),
  userFactory({ username: `${role}-archived`, role, archived_at: "2026-01-01T00:00:00Z" }),
]);

describe("loadUsers", () => {
  it("paints a four-column skeleton while the fetch is in flight", async () => {
    const { mod } = await mountUsers({ users: [] });
    const loading = mod.loadUsers();
    expect(rows()).toHaveLength(5);
    expect(rows()[0].className).toBe("skel-row");
    expect(rows()[0].querySelectorAll("td")).toHaveLength(4);
    await loading;
  });

  it("asks for archived users too — the History filter still needs them", async () => {
    const { mod } = await mountUsers({ users: [] });
    await mod.loadUsers();
    expect(requestFor("/users/", "GET").url).toBe("/users/?include_archived=true");
  });

  it("replaces the body with one error cell on a failure", async () => {
    const { mod } = await mountUsers({
      handlers: [http.get("/users/", () => HttpResponse.json({ detail: "Users are down" }, { status: 500 }))],
    });
    await mod.loadUsers();
    const cell = rows()[0].querySelector("td");
    expect(rows()).toHaveLength(1);
    expect(cell.getAttribute("colspan")).toBe("4");
    expect(cell.className).toBe("error");
    expect(cell.textContent).toBe("Users are down");
  });
});

describe("the table", () => {
  it("renders the four cells in order", async () => {
    const u = userFactory({
      first_name: "Ann", last_name: "Holder", full_name: "Ann Holder", username: "aholder", role: "techfm_oa",
    });
    await openUsers({ users: [u] });
    expect(cells(rowFor("aholder")).slice(0, 3)).toEqual(["Ann Holder", "aholder", "TechFM OA"]);
    // Owner over a TechFM OA: the full four-option menu.
    expect(actionsIn(rowFor("aholder"))).toEqual(["edit-details", "edit-role", "reset-password", "archive"]);
    // The Name cell leads the phone card.
    expect(rowFor("aholder").querySelector("td").hasAttribute("data-primary")).toBe(true);
  });

  it("falls back to 'Name unavailable' only when both names are missing", async () => {
    await openUsers({
      users: [
        // No full_name from the server: the cell is built from the parts.
        userFactory({ first_name: null, last_name: "Holder", full_name: null, username: "nofirst" }),
        userFactory({ first_name: "Ann", last_name: null, full_name: null, username: "nolast" }),
        userFactory({ first_name: null, last_name: null, full_name: null, username: "neither" }),
      ],
    });
    expect(cells(rowFor("nofirst"))[0]).toBe("Holder");
    expect(cells(rowFor("nolast"))[0]).toBe("Ann");
    expect(cells(rowFor("neither"))[0]).toBe("Name unavailable");
  });

  it("shows active users by default and archived ones under the Archived scope", async () => {
    await openUsers({
      users: [
        userFactory({ first_name: "Gone", last_name: "Away", full_name: "Gone Away", username: "gone", archived_at: "2026-01-01T00:00:00Z" }),
        userFactory({ first_name: "Still", last_name: "Here", username: "here" }),
      ],
    });
    expect(scopeBtn("active").getAttribute("aria-pressed")).toBe("true");
    expect(rowFor("gone")).toBeNull();
    expect(rowFor("here").classList.contains("archived-user")).toBe(false);

    showScope("archived");
    expect(scopeBtn("archived").getAttribute("aria-pressed")).toBe("true");
    expect(scopeBtn("active").getAttribute("aria-pressed")).toBe("false");
    expect(rowFor("here")).toBeNull();
    const archived = rowFor("gone");
    expect(archived.classList.contains("archived-user")).toBe(true);
    expect(cells(archived)[0]).toBe("Gone Away (archived)");
    expect(archived.querySelector(".muted").textContent).toBe("(archived)");
  });

  it("the search box narrows by name or username, with an empty line when nothing matches", async () => {
    const user = userEvent.setup();
    await openUsers({
      users: [
        userFactory({ first_name: "Ann", last_name: "Holder", username: "aholder" }),
        userFactory({ first_name: "Bob", last_name: "Smith", username: "bsmith" }),
      ],
    });
    await user.type(search(), "hold");
    expect(rows()).toHaveLength(1);
    expect(rowFor("aholder")).not.toBeNull();

    await user.clear(search());
    await user.type(search(), "bsm");
    expect(rowFor("bsmith")).not.toBeNull();
    expect(rowFor("aholder")).toBeNull();

    await user.clear(search());
    await user.type(search(), "zzz");
    expect(rows()).toHaveLength(1);
    expect(rows()[0].querySelector("td.empty").textContent).toBe("No active users match.");
  });

  it("escapes a name carrying markup", async () => {
    await openUsers({
      users: [userFactory({ full_name: '<img src=x onerror="boom">', username: "nasty" })],
    });
    expect(el.tbody().querySelector("img")).toBeNull();
    expect(cells(rowFor("nasty"))[0]).toBe('<img src=x onerror="boom">');
  });
});

describe("the row-action matrix, frozen", () => {
  it.each(ROLES)("%s sees the right actions on every role, active and archived", async (actor) => {
    await openUsers({ role: actor, users: matrixRoster() });

    ["active", "archived"].forEach((state) => {
      showScope(state);
      ROLES.forEach((target) => {
        const row = rowFor(`${target}-${state}`);
        const expected = MATRIX[actor][target][state];
        expect(actionsIn(row), `${actor} → ${target} (${state})`).toEqual(expected);
        if (expected.length === 0) {
          expect(row.querySelector(".empty").textContent).toBe("—");
          expect(row.querySelector(".action-menu")).toBeNull();
        }
      });
    });
  });

  it.each(ROLES)("a %s acting on their own row gets Edit Details and nothing else", async (role) => {
    const me = userFactory({ username: "me", role });
    await openUsers({ role, currentUser: { id: me.id }, users: [me] });
    // canManage(role, role) is false at every rank, so the self row is reached
    // only by the `actorId === user.id` half of canEditName.
    expect(actionsIn(rowFor("me"))).toEqual(["edit-details"]);
  });

  it("labels the menu for assistive tech and marks Archive as the danger item", async () => {
    const target = userFactory({ username: "tech", role: "technician" });
    await openUsers({ users: [target] });
    const menu = rowFor("tech").querySelector(".action-menu");
    expect(menu.querySelector(".menu-trigger").getAttribute("aria-label")).toBe("Actions for tech");
    expect(menu.dataset.id).toBe(target.id);
    expect(menu.querySelector('.menu-option[data-value="archive"]').classList.contains("menu-option-danger")).toBe(true);
  });
});

describe("the create-user role select", () => {
  it("offers an owner the four roles below them, with the first one's help text", async () => {
    await openUsers({ role: "owner", users: [] });
    expect(roleOptions()).toEqual(["admin", "techfm_oa", "supervisor", "technician"]);
    expect(el.roleSelect().value).toBe("admin");
    expect(el.roleHelp().textContent).toBe("Manage items and corrections.");
  });

  it("offers a technician nothing at all", async () => {
    await openUsers({ role: "technician", users: [] });
    expect(roleOptions()).toEqual([]);
    expect(el.roleSelect().value).toBe("");
    expect(el.roleHelp().textContent).toBe("");
  });

  it("rewrites the help text on change", async () => {
    await openUsers({ role: "owner", users: [] });
    const user = userEvent.setup();
    await user.selectOptions(el.roleSelect(), "technician");
    expect(el.roleHelp().textContent).toBe("Scan items and do basic work.");
  });

  it("keeps a chosen role across a reload when it is still offered", async () => {
    const { mod } = await openUsers({ role: "owner", users: [] });
    el.roleSelect().value = "supervisor";
    await mod.loadUsers();
    expect(el.roleSelect().value).toBe("supervisor");
  });

  it("drops it when the actor's own rank no longer offers it", async () => {
    const { mod } = await openUsers({ role: "owner", users: [] });
    el.roleSelect().value = "admin";
    const state = await import("../../../backend/static/state.js");
    state.setCurrentUser({ ...state.getCurrentUser(), role: "supervisor" });
    await mod.loadUsers();
    expect(roleOptions()).toEqual(["technician"]);
    expect(el.roleSelect().value).toBe("technician");
  });
});

describe("populateUserSelects", () => {
  it("rebuilds the History filter with a placeholder and every user, archived included", async () => {
    const ann = userFactory({ full_name: "Ann Holder", username: "a" });
    const gone = userFactory({ full_name: "Gone Away", username: "g", archived_at: "2026-01-01T00:00:00Z" });
    await openUsers({ users: [ann, gone] });

    expect(historyOptions()).toEqual([
      { value: "", label: "-- Select user --" },
      { value: ann.id, label: "Ann Holder" },
      { value: gone.id, label: "Gone Away" },
    ]);
  });

  it("preserves the selection when that user is still listed", async () => {
    const ann = userFactory({ username: "a" });
    const bob = userFactory({ username: "b" });
    const { mod } = await openUsers({ users: [ann, bob] });
    el.historySelect().value = bob.id;
    mod.populateUserSelects();
    expect(el.historySelect().value).toBe(bob.id);
  });

  it("falls back to the placeholder when that user is gone", async () => {
    const ann = userFactory({ username: "a" });
    const bob = userFactory({ username: "b" });
    const { mod } = await openUsers({ users: [ann, bob] });
    el.historySelect().value = bob.id;
    server.use(http.get("/users/", () => HttpResponse.json([ann])));
    await mod.loadUsers();
    expect(el.historySelect().value).toBe("");
  });
});

describe("creating a user", () => {
  const fill = ({ first = "New", last = "Person", username = "nperson", password = "hunter2" } = {}) => {
    el.firstName().value = first;
    el.lastName().value = last;
    el.username().value = username;
    el.password().value = password;
  };

  it.each([
    ["neither name", { first: "", last: "" }, "First name and last name are required."],
    ["no first name", { first: "" }, "First name and last name are required."],
    ["no last name", { last: "" }, "First name and last name are required."],
    ["no username", { username: "" }, "Username is required."],
    ["a password under four characters", { password: "abc" }, "Password must be at least 4 characters."],
  ])("refuses %s", async (_label, overrides, expected) => {
    await openUsers({ role: "owner", users: [] });
    fill(overrides);
    el.createBtn().click();

    await vi.waitFor(() => expect(el.createMessage().textContent).toBe(expected));
    expect(el.createMessage().className).toBe("error");
    expect(requests()).toHaveLength(0);
  });

  it("refuses an empty role — which is what a technician's own form offers", async () => {
    // The only way to reach "Select a role.": assignableRoles(technician) is
    // empty, so the select has no options and its value is "".
    await openUsers({ role: "technician", users: [] });
    fill();
    el.createBtn().click();

    await vi.waitFor(() => expect(el.createMessage().textContent).toBe("Select a role."));
    expect(requests()).toHaveLength(0);
  });

  it("posts a snake_case body, names the account off the RESPONSE and clears the form", async () => {
    await openUsers({ role: "owner", users: [] });
    server.use(http.post("/users/", () => HttpResponse.json(
      userFactory({ first_name: "Server", last_name: "Says", full_name: "Server Says", role: "supervisor" }))));
    fill();
    el.roleSelect().value = "technician";
    el.createBtn().click();

    await vi.waitFor(() => expect(el.createMessage().className).toBe("success"));
    // Not "New Person created as technician." -- the copy reads the response.
    expect(el.createMessage().textContent).toBe("Server Says created as supervisor.");
    expect(requestFor("/users/", "POST").body).toEqual({
      username: "nperson", first_name: "New", last_name: "Person",
      password: "hunter2", role: "technician",
    });

    expect(el.firstName().value).toBe("");
    expect(el.lastName().value).toBe("");
    expect(el.username().value).toBe("");
    expect(el.password().value).toBe("");
    // The role select is deliberately left where it was, for a second create.
    expect(el.roleSelect().value).toBe("technician");
    await vi.waitFor(() => expect(requestFor("/users/", "GET")).not.toBeNull());
  });

  it("trims the names and username before posting", async () => {
    await openUsers({ role: "owner", users: [] });
    server.use(http.post("/users/", () => HttpResponse.json(userFactory())));
    fill({ first: "  New  ", last: "  Person  ", username: "  nperson  " });
    el.createBtn().click();

    await vi.waitFor(() => expect(el.createMessage().className).toBe("success"));
    const body = requestFor("/users/", "POST").body;
    expect([body.first_name, body.last_name, body.username]).toEqual(["New", "Person", "nperson"]);
    // `loadUsers()` is fired without an await, so settle it inside the test
    // rather than letting it reach MSW after resetHandlers.
    await vi.waitFor(() => expect(requestFor("/users/", "GET")).not.toBeNull());
  });

  it("keeps what was typed on a failure", async () => {
    await openUsers({ role: "owner", users: [] });
    server.use(http.post("/users/", () =>
      HttpResponse.json({ detail: "That username is taken." }, { status: 409 })));
    fill();
    el.createBtn().click();

    await vi.waitFor(() => expect(el.createMessage().className).toBe("error"));
    expect(el.createMessage().textContent).toBe("That username is taken.");
    expect(el.username().value).toBe("nperson");
    expect(el.password().value).toBe("hunter2");
  });
});

describe("the profile hand-off", () => {
  const PROFILE_BTN = `.${"user-profile-btn"}`;
  const PROFILE_ROLES = ["technician", "supervisor", "techfm_oa", "admin"];
  const crew = () => ROLES.map((role) => userFactory({ role }));

  it.each(["owner", "admin", "techfm_oa", "supervisor"])("renders a name button only on crew rows for an %s", async (role) => {
    const users = crew();
    await openUsers({ role, users });
    for (const target of users) {
      const button = rowFor(target.username).querySelector(PROFILE_BTN);
      expect(Boolean(button), `${role} -> ${target.role}`).toBe(PROFILE_ROLES.includes(target.role));
    }
  });

  it.each(["technician"])("renders no name button for a %s viewer", async (role) => {
    await openUsers({ role, users: crew() });
    expect(document.querySelectorAll(PROFILE_BTN)).toHaveLength(0);
  });

  it("swaps the table for the profile and Back restores it without refetching", async () => {
    const users = crew();
    const tech = users.find((u) => u.role === "technician");
    server.use(http.get("/hub/people/:id/week", () => HttpResponse.json({
      user: tech, archived: false, week_start: "2026-09-14", week_end: "2026-09-20",
      server_now: "2026-09-16T15:00:00Z", days: [], total_clocked_minutes: 0,
      total_charged_minutes: 0, total_adjustment_minutes: 0, total_completed: 0, reviewable: false,
    })));
    await openUsers({ role: "admin", users });
    rowFor(tech.username).querySelector(PROFILE_BTN).click();
    await vi.waitFor(() => expect(document.querySelector(".user-profile-header")).not.toBeNull());
    expect(document.getElementById("users-table").hidden).toBe(true);
    expect(document.querySelector(".user-profile-header").textContent).toContain(tech.last_name);
    document.querySelector(".user-profile-back").click();
    expect(document.getElementById("users-table").hidden).toBe(false);
    expect(document.getElementById("user-profile").hidden).toBe(true);
    expect(rows().length).toBe(users.length);
  });
});

describe("openUserProfile", () => {
  it("loads the list if needed and mounts the profile at the week", async () => {
    const tech = userFactory({ role: "technician", first_name: "Ann", last_name: "Lee" });
    server.use(http.get("/hub/people/:id/week", ({ request }) =>
      HttpResponse.json({ ...personWeek(), week_start: new URL(request.url).searchParams.get("week") })));
    const { mod } = await mountUsers({ role: "admin", users: [tech] });
    await mod.openUserProfile(tech.id, { week: "2026-09-07" });
    const profile = document.getElementById("user-profile");
    await vi.waitFor(() => expect(profile.querySelector(".user-profile")).not.toBeNull());
    expect(document.getElementById("users-table").hidden).toBe(true);
    expect(requestFor("/users/")).toBeDefined();
    await vi.waitFor(() => expect(requestFor("/hub/people/")?.url).toContain("week=2026-09-07"));
  });

  it("survives the page loader's refresh that showPage fires alongside it", async () => {
    // Back from a work order: nav.js's showPage("saved-users") starts
    // loadUsers, and the Back branch calls openUserProfile right after. The
    // refresh's table repaint must not hide the profile it raced.
    const tech = userFactory({ role: "technician", first_name: "Ann", last_name: "Lee" });
    const { mod } = await openUsers({ role: "admin", users: [tech] });
    // The list is held until released, so it answers after the profile's
    // module import has had time to land -- the browser's order, where that
    // import is cached from the first profile click.
    let release;
    const held = new Promise((resolve) => { release = resolve; });
    server.use(
      http.get("/hub/people/:id/week", () => HttpResponse.json(personWeek())),
      http.get("/users/", async () => { await held; return HttpResponse.json([tech]); }),
    );
    const refresh = mod.loadUsers();
    const opening = mod.openUserProfile(tech.id, { week: null });
    await new Promise((resolve) => setTimeout(resolve, 300));
    release();
    await refresh;
    await opening;
    const profile = document.getElementById("user-profile");
    await vi.waitFor(() => expect(profile.querySelector(".user-profile")).not.toBeNull());
    expect(profile.hidden).toBe(false);
    expect(document.getElementById("users-table").hidden).toBe(true);
  });
});
