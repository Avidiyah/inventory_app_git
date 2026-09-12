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
  buttonsIn, cells, el, historyOptions, mountUsers, openUsers, requestFor,
  requests, restoreUsers, roleOptions, rowFor, rows,
} from "../helpers/users.js";
import { user as userFactory } from "../helpers/factories.js";

afterEach(() => restoreUsers());

const ROLES = ["owner", "admin", "techfm_oa", "supervisor", "technician"];

// The frozen row-action matrix, read off the running code. Rows are the actor;
// columns the target; each cell the buttons that render, IN ORDER (Edit
// Details, Edit Role, then the lifecycle pair). An empty list renders the
// `<span class="empty">—</span>` placeholder instead of a `.row-actions` div.
//
// The shape worth reading twice: a Supervisor acting on a Technician gets Edit
// Details, Reset Password and Archive but NOT Edit Role -- role changes are
// gated at techfm_oa on top of the usual outranks rule.
const MATRIX = {
  owner: {
    owner: { active: [], archived: [] },
    admin: { active: ["edit-user-name-btn", "edit-user-role-btn", "reset-pw-btn", "archive-user-btn"], archived: ["edit-user-name-btn", "restore-user-btn"] },
    techfm_oa: { active: ["edit-user-name-btn", "edit-user-role-btn", "reset-pw-btn", "archive-user-btn"], archived: ["edit-user-name-btn", "restore-user-btn"] },
    supervisor: { active: ["edit-user-name-btn", "edit-user-role-btn", "reset-pw-btn", "archive-user-btn"], archived: ["edit-user-name-btn", "restore-user-btn"] },
    technician: { active: ["edit-user-name-btn", "edit-user-role-btn", "reset-pw-btn", "archive-user-btn"], archived: ["edit-user-name-btn", "restore-user-btn"] },
  },
  admin: {
    owner: { active: [], archived: [] },
    admin: { active: [], archived: [] },
    techfm_oa: { active: ["edit-user-name-btn", "edit-user-role-btn", "reset-pw-btn", "archive-user-btn"], archived: ["edit-user-name-btn", "restore-user-btn"] },
    supervisor: { active: ["edit-user-name-btn", "edit-user-role-btn", "reset-pw-btn", "archive-user-btn"], archived: ["edit-user-name-btn", "restore-user-btn"] },
    technician: { active: ["edit-user-name-btn", "edit-user-role-btn", "reset-pw-btn", "archive-user-btn"], archived: ["edit-user-name-btn", "restore-user-btn"] },
  },
  techfm_oa: {
    owner: { active: [], archived: [] },
    admin: { active: [], archived: [] },
    techfm_oa: { active: [], archived: [] },
    supervisor: { active: ["edit-user-name-btn", "edit-user-role-btn", "reset-pw-btn", "archive-user-btn"], archived: ["edit-user-name-btn", "restore-user-btn"] },
    technician: { active: ["edit-user-name-btn", "edit-user-role-btn", "reset-pw-btn", "archive-user-btn"], archived: ["edit-user-name-btn", "restore-user-btn"] },
  },
  supervisor: {
    owner: { active: [], archived: [] },
    admin: { active: [], archived: [] },
    techfm_oa: { active: [], archived: [] },
    supervisor: { active: [], archived: [] },
    technician: { active: ["edit-user-name-btn", "reset-pw-btn", "archive-user-btn"], archived: ["edit-user-name-btn", "restore-user-btn"] },
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
  it("paints a six-column skeleton while the fetch is in flight", async () => {
    const { mod } = await mountUsers({ users: [] });
    const loading = mod.loadUsers();
    expect(rows()).toHaveLength(5);
    expect(rows()[0].className).toBe("skel-row");
    expect(rows()[0].querySelectorAll("td")).toHaveLength(6);
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
    expect(cell.getAttribute("colspan")).toBe("6");
    expect(cell.className).toBe("error");
    expect(cell.textContent).toBe("Users are down");
  });
});

describe("the table", () => {
  it("renders the six cells in order", async () => {
    const created = "2026-03-04T15:30:00Z";
    const u = userFactory({
      first_name: "Ann", last_name: "Holder", username: "aholder",
      role: "techfm_oa", created_at: created,
    });
    await openUsers({ users: [u] });
    expect(cells(rowFor("aholder"))).toEqual([
      "Ann", "Holder", "aholder", "TechFM OA", new Date(created).toLocaleString(),
      // Owner over a TechFM OA: the full four-button set.
      "Edit DetailsEdit RoleReset Password🗑️",
    ]);
  });

  it("falls back to 'Name unavailable' per name column, independently", async () => {
    await openUsers({
      users: [
        userFactory({ first_name: null, last_name: "Holder", username: "nofirst" }),
        userFactory({ first_name: "Ann", last_name: null, username: "nolast" }),
        userFactory({ first_name: null, last_name: null, username: "neither" }),
      ],
    });
    expect(cells(rowFor("nofirst")).slice(0, 2)).toEqual(["Name unavailable", "Holder"]);
    expect(cells(rowFor("nolast")).slice(0, 2)).toEqual(["Ann", "Name unavailable"]);
    expect(cells(rowFor("neither")).slice(0, 2)).toEqual(["Name unavailable", "Name unavailable"]);
  });

  it("tags an archived row on the First Name cell and marks the tr", async () => {
    await openUsers({
      users: [
        userFactory({ first_name: "Gone", last_name: "Away", username: "gone", archived_at: "2026-01-01T00:00:00Z" }),
        userFactory({ first_name: "Still", last_name: "Here", username: "here" }),
      ],
    });
    const archived = rowFor("gone");
    expect(archived.classList.contains("archived-user")).toBe(true);
    expect(cells(archived)[0]).toBe("Gone (archived)");
    expect(archived.querySelector(".muted").textContent).toBe("(archived)");
    // The tag rides the First Name cell only.
    expect(cells(archived)[1]).toBe("Away");
    expect(rowFor("here").classList.contains("archived-user")).toBe(false);
  });

  it("escapes a name carrying markup", async () => {
    await openUsers({
      users: [userFactory({ first_name: '<img src=x onerror="boom">', username: "nasty" })],
    });
    expect(el.tbody().querySelector("img")).toBeNull();
    expect(cells(rowFor("nasty"))[0]).toBe('<img src=x onerror="boom">');
  });

  it.each([
    // N-P6-CHARACTERIZED: `new Date(null)` is the epoch, not Invalid Date, so a
    // user with no creation date reads as a 1970 account rather than as
    // missing. Junk reads "Invalid Date". The Items finding's twin.
    ["a null created_at", null, new Date(0).toLocaleString()],
    ["an unparseable created_at", "not-a-date", "Invalid Date"],
  ])("%s renders as %s", async (_label, created, expected) => {
    await openUsers({ users: [userFactory({ username: "odd", created_at: created })] });
    expect(cells(rowFor("odd"))[4]).toBe(expected);
  });
});

describe("the row-action matrix, frozen", () => {
  it.each(ROLES)("%s sees the right actions on every role, active and archived", async (actor) => {
    await openUsers({ role: actor, users: matrixRoster() });

    ROLES.forEach((target) => {
      ["active", "archived"].forEach((state) => {
        const row = rowFor(`${target}-${state}`);
        const expected = MATRIX[actor][target][state];
        expect(buttonsIn(row), `${actor} → ${target} (${state})`).toEqual(expected);
        if (expected.length === 0) {
          expect(row.querySelector(".empty").textContent).toBe("—");
          expect(row.querySelector(".row-actions")).toBeNull();
        }
      });
    });
  });

  it.each(ROLES)("a %s acting on their own row gets Edit Details and nothing else", async (role) => {
    const me = userFactory({ username: "me", role });
    await openUsers({ role, currentUser: { id: me.id }, users: [me] });
    // canManage(role, role) is false at every rank, so the self row is reached
    // only by the `actorId === user.id` half of canEditName.
    expect(buttonsIn(rowFor("me"))).toEqual(["edit-user-name-btn"]);
  });

  it("labels the archive button for assistive tech", async () => {
    const target = userFactory({ username: "tech", role: "technician" });
    await openUsers({ users: [target] });
    const archive = rowFor("tech").querySelector(".archive-user-btn");
    expect(archive.getAttribute("aria-label")).toBe("Archive user tech");
    expect(archive.getAttribute("title")).toBe("Archive user");
    expect(archive.dataset.name).toBe("tech");
    expect(archive.dataset.id).toBe(target.id);
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
