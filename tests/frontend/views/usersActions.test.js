// Characterization coverage for the five row actions in views/users.js, each
// driven through the REAL dom.js overlay it opens: Edit Details
// (#user-name-*), Edit Role (#user-role-*), Reset Password (#pw-reset-*),
// Restore (no prompt) and Archive (#scan-confirm-overlay, twice on a 409).
//
// P1's unit/dom.prompts.test.js owns each prompt's own validation and focus
// behaviour; what is pinned here is what users.js does with the answer.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import {
  answerPasswordReset, answerUserName, answerUserRole, el, openUsers,
  requestFor, requests, restoreUsers, rowFor,
} from "../helpers/users.js";
import { confirmOverlay, confirmTitle } from "../helpers/dialogs.js";
import { user as userFactory } from "../helpers/factories.js";

afterEach(() => restoreUsers());

// An owner looking at one technician — the actor/target pair that unlocks
// every action at once.
async function withTarget(overrides = {}) {
  const user = userEvent.setup();
  const target = userFactory({
    first_name: "Tess", last_name: "Tech", full_name: "Tess Tech",
    username: "ttech", role: "technician", ...overrides,
  });
  const mounted = await openUsers({ role: "owner", users: [target] });
  return { ...mounted, target, user, row: () => rowFor(target.username) };
}

const click = (ctx, className) => ctx.user.click(ctx.row().querySelector(`.${className}`));

// Read the confirm title before answering — `answerConfirm` closes the overlay.
async function confirmTitled(expected, yes = true) {
  await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(false));
  expect(confirmTitle()).toBe(expected);
  document.getElementById(yes ? "scan-confirm-yes" : "scan-confirm-no").click();
  await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(true));
}

const reloaded = () => requestFor("/users/", "GET") !== null;

// `user.click()` awaits its own internal delays before dispatching, so an
// overlay assertion made right after starting the click would read the markup's
// placeholder text. Wait for the prompt to actually open first.
async function opened(id) {
  await vi.waitFor(() => expect(document.getElementById(id).hidden).toBe(false));
}

describe("Edit Details", () => {
  it("PATCHes the three fields and names the account by its NEW username", async () => {
    const ctx = await withTarget();
    server.use(http.patch(`/users/${ctx.target.id}/name`, () =>
      HttpResponse.json(userFactory({ username: "trenamed", full_name: "Tess Renamed" }))));

    const clicking = click(ctx, "edit-user-name-btn");
    await opened("user-name-overlay");
    expect(document.getElementById("user-name-title").textContent).toBe('Edit "ttech"');
    // allowUsername: true — the login-name field is shown, not hidden.
    expect(document.getElementById("user-name-username").hidden).toBe(false);
    expect(document.getElementById("user-name-first").value).toBe("Tess");
    await answerUserName({ first: "Tessa", last: "Techie", username: "trenamed" });
    await clicking;

    await vi.waitFor(() => expect(el.message().textContent).toBe('Updated "trenamed".'));
    expect(el.message().className).toBe("success");
    expect(requestFor(`/users/${ctx.target.id}/name`, "PATCH").body)
      .toEqual({ first_name: "Tessa", last_name: "Techie", username: "trenamed" });
    await vi.waitFor(() => expect(reloaded()).toBe(true));
  });

  it("Cancel writes nothing", async () => {
    const ctx = await withTarget();
    const clicking = click(ctx, "edit-user-name-btn");
    await answerUserName(null);
    await clicking;
    expect(requests()).toHaveLength(0);
    expect(el.message().textContent).toBe("");
  });

  it("dispatches user-names-updated even for someone else's row", async () => {
    const ctx = await withTarget();
    server.use(http.patch(`/users/${ctx.target.id}/name`, () => HttpResponse.json(userFactory())));
    const heard = vi.fn();
    document.addEventListener("user-names-updated", heard);
    try {
      const clicking = click(ctx, "edit-user-name-btn");
      await answerUserName({ first: "A", last: "B" });
      await clicking;
      await vi.waitFor(() => expect(heard).toHaveBeenCalledTimes(1));
    } finally {
      document.removeEventListener("user-names-updated", heard);
    }
  });

  it("a self-edit also rewrites state and the header identity button", async () => {
    const me = userFactory({
      first_name: "Olive", last_name: "Owner", full_name: "Olive Owner",
      username: "oowner", role: "owner",
    });
    const user = userEvent.setup();
    const { mod } = await openUsers({ role: "owner", currentUser: { id: me.id }, users: [me] });
    expect(mod).toBeTruthy();
    const updated = userFactory({
      id: me.id, username: "orenamed", full_name: "Olive Renamed", role: "admin",
    });
    server.use(http.patch(`/users/${me.id}/name`, () => HttpResponse.json(updated)));

    const clicking = user.click(rowFor("oowner").querySelector(".edit-user-name-btn"));
    await answerUserName({ first: "Olive", last: "Renamed", username: "orenamed" });
    await clicking;

    await vi.waitFor(() => expect(el.message().textContent).toBe('Updated "orenamed".'));
    const state = await import("../../../backend/static/state.js");
    expect(state.getCurrentUser()).toEqual(updated);
    expect(el.indicator().querySelector(".user-hub-name").textContent).toBe("Olive Renamed");
    // The indicator takes the response's role too, not the one it was showing.
    expect(el.indicator().querySelector(".user-hub-role").textContent).toBe("Admin");
    expect(el.indicator().getAttribute("aria-label")).toBe("Your hub — Olive Renamed, Admin");
  });

  it("a failure writes the module's copy and does not reload", async () => {
    const ctx = await withTarget();
    server.use(http.patch(`/users/${ctx.target.id}/name`, () =>
      HttpResponse.json({ detail: null }, { status: 500 })));
    const clicking = click(ctx, "edit-user-name-btn");
    await answerUserName({ first: "A", last: "B" });
    await clicking;

    await vi.waitFor(() => expect(el.message().className).toBe("error"));
    expect(el.message().textContent).toBe("Could not update the user's details.");
    expect(reloaded()).toBe(false);
  });
});

describe("Edit Role", () => {
  it("offers the actor's assignable roles and PATCHes the chosen one", async () => {
    const ctx = await withTarget();
    server.use(http.patch(`/users/${ctx.target.id}/role`, () =>
      HttpResponse.json(userFactory({ username: "ttech", role: "supervisor" }))));

    const clicking = click(ctx, "edit-user-role-btn");
    await opened("user-role-overlay");
    const select = document.getElementById("user-role-select");
    expect(document.getElementById("user-role-title").textContent).toBe('Change role for "ttech"');
    expect(Array.from(select.options).map((o) => o.value))
      .toEqual(["admin", "techfm_oa", "supervisor", "technician"]);
    // N-P6-CHARACTERIZED: the modal labels roles by capitalising the slug
    // rather than through `roleLabel`, so TechFM OA reads "Techfm_oa".
    expect(Array.from(select.options).map((o) => o.textContent))
      .toEqual(["Admin", "Techfm_oa", "Supervisor", "Technician"]);
    // It opens on the role the user already holds, so Save is deliberate.
    expect(select.value).toBe("technician");
    expect(document.getElementById("user-role-modal-help").textContent)
      .toBe("Scan items and do basic work.");
    await answerUserRole("supervisor");
    await clicking;

    await vi.waitFor(() => expect(el.message().className).toBe("success"));
    // The copy uses the raw slug, not roleLabel — same family as the labels.
    expect(el.message().textContent)
      .toBe('"ttech" is now supervisor. They will need to sign in again.');
    expect(requestFor(`/users/${ctx.target.id}/role`, "PATCH").body).toEqual({ role: "supervisor" });
    await vi.waitFor(() => expect(reloaded()).toBe(true));
  });

  it("Cancel writes nothing", async () => {
    const ctx = await withTarget();
    const clicking = click(ctx, "edit-user-role-btn");
    await answerUserRole(null);
    await clicking;
    expect(requests()).toHaveLength(0);
  });

  it("re-saving the role the user already holds is a cancel, not a no-op write", async () => {
    const ctx = await withTarget();
    const clicking = click(ctx, "edit-user-role-btn");
    await answerUserRole("technician");
    await clicking;
    expect(requests()).toHaveLength(0);
    expect(el.message().textContent).toBe("");
  });

  it("a failure writes the module's copy", async () => {
    const ctx = await withTarget();
    server.use(http.patch(`/users/${ctx.target.id}/role`, () =>
      HttpResponse.json({ detail: null }, { status: 500 })));
    const clicking = click(ctx, "edit-user-role-btn");
    await answerUserRole("supervisor");
    await clicking;

    await vi.waitFor(() => expect(el.message().className).toBe("error"));
    expect(el.message().textContent).toBe("Could not change the user's role.");
  });
});

describe("Reset Password", () => {
  it("POSTs the new password and does NOT reload — the only action that does not", async () => {
    const ctx = await withTarget();
    server.use(http.post(`/users/${ctx.target.id}/reset-password`, () => HttpResponse.json({ ok: true })));

    const clicking = click(ctx, "reset-pw-btn");
    await opened("pw-reset-overlay");
    expect(document.getElementById("pw-reset-title").textContent).toBe('New password for "ttech"');
    await answerPasswordReset("hunter2");
    await clicking;

    await vi.waitFor(() => expect(el.message().textContent).toBe('Password reset for "ttech".'));
    expect(el.message().className).toBe("success");
    expect(requestFor(`/users/${ctx.target.id}/reset-password`, "POST").body)
      .toEqual({ password: "hunter2" });
    expect(reloaded()).toBe(false);
  });

  it("Cancel writes nothing", async () => {
    const ctx = await withTarget();
    const clicking = click(ctx, "reset-pw-btn");
    await answerPasswordReset(null);
    await clicking;
    expect(requests()).toHaveLength(0);
  });

  it("a failure writes the module's copy", async () => {
    const ctx = await withTarget();
    server.use(http.post(`/users/${ctx.target.id}/reset-password`, () =>
      HttpResponse.json({ detail: null }, { status: 500 })));
    const clicking = click(ctx, "reset-pw-btn");
    await answerPasswordReset("hunter2");
    await clicking;

    await vi.waitFor(() => expect(el.message().className).toBe("error"));
    expect(el.message().textContent).toBe("Could not reset the password. Try again.");
  });
});

describe("Restore", () => {
  const archived = () => ({ archived_at: "2026-01-01T00:00:00Z" });

  it("POSTs with no prompt at all, then reloads", async () => {
    const ctx = await withTarget(archived());
    server.use(http.post(`/users/${ctx.target.id}/restore`, () => HttpResponse.json({ ok: true })));

    await click(ctx, "restore-user-btn");
    await vi.waitFor(() => expect(el.message().textContent).toBe('Restored "ttech".'));
    expect(el.message().className).toBe("success");
    expect(requestFor(`/users/${ctx.target.id}/restore`, "POST")).not.toBeNull();
    expect(confirmOverlay().hidden).toBe(true);
    await vi.waitFor(() => expect(reloaded()).toBe(true));
  });

  it("a failure writes the module's copy", async () => {
    const ctx = await withTarget(archived());
    server.use(http.post(`/users/${ctx.target.id}/restore`, () =>
      HttpResponse.json({ detail: null }, { status: 500 })));

    await click(ctx, "restore-user-btn");
    await vi.waitFor(() => expect(el.message().className).toBe("error"));
    expect(el.message().textContent).toBe("Could not restore the user. Try again.");
  });
});

describe("Archive", () => {
  const ARCHIVE_COPY =
    'Archive user "ttech"? They will no longer be able to log in, but their history is kept and they can be restored.';
  const TOOLS_COPY = '"ttech" still has tools checked out. Check them all in now and archive?';

  // 409 until the caller retries with ?force_return_tools=true.
  const answerArchive = (id, { force = true, status = null, detail = null } = {}) =>
    server.use(http.post(`/users/${id}/archive`, ({ request }) => {
      const forced = new URL(request.url).searchParams.get("force_return_tools") === "true";
      if (status) return HttpResponse.json({ detail }, { status });
      if (!forced && force) return HttpResponse.json({ detail: "Still holds tools" }, { status: 409 });
      return HttpResponse.json({ ok: true });
    }));

  it("No on the first prompt writes nothing", async () => {
    const ctx = await withTarget();
    const clicking = click(ctx, "archive-user-btn");
    await confirmTitled(ARCHIVE_COPY, false);
    await clicking;
    expect(requests()).toHaveLength(0);
    expect(el.message().textContent).toBe("");
  });

  it("Yes archives on the first try when the user holds nothing", async () => {
    const ctx = await withTarget();
    answerArchive(ctx.target.id, { force: false });
    const clicking = click(ctx, "archive-user-btn");
    await confirmTitled(ARCHIVE_COPY);
    await clicking;

    await vi.waitFor(() => expect(el.message().textContent).toBe('Archived "ttech".'));
    expect(el.message().className).toBe("success");
    expect(requestFor(`/users/${ctx.target.id}/archive`, "POST").url)
      .toBe(`/users/${ctx.target.id}/archive`);
    await vi.waitFor(() => expect(reloaded()).toBe(true));
  });

  it("a 409 asks a second time, and Yes retries with force_return_tools", async () => {
    const ctx = await withTarget();
    answerArchive(ctx.target.id);
    const clicking = click(ctx, "archive-user-btn");
    await confirmTitled(ARCHIVE_COPY);
    await confirmTitled(TOOLS_COPY);
    await clicking;

    await vi.waitFor(() => expect(el.message().textContent).toBe('Archived "ttech".'));
    const archives = requests().filter((r) => r.url.includes("/archive"));
    expect(archives.map((r) => r.url)).toEqual([
      `/users/${ctx.target.id}/archive`,
      `/users/${ctx.target.id}/archive?force_return_tools=true`,
    ]);
  });

  it("No on the tools prompt leaves the slot BLANK, not an error", async () => {
    const ctx = await withTarget();
    answerArchive(ctx.target.id);
    const clicking = click(ctx, "archive-user-btn");
    await confirmTitled(ARCHIVE_COPY);
    await confirmTitled(TOOLS_COPY, false);
    await clicking;

    // confirmArchivedReuse throws {cancelled: true}, which the view swallows.
    await vi.waitFor(() => expect(requests()).toHaveLength(1));
    expect(el.message().textContent).toBe("");
    expect(el.message().className).toBe("");
  });

  it("a non-409 failure skips the second prompt entirely", async () => {
    const ctx = await withTarget();
    answerArchive(ctx.target.id, { status: 500 });
    const clicking = click(ctx, "archive-user-btn");
    await confirmTitled(ARCHIVE_COPY);
    await clicking;

    await vi.waitFor(() => expect(el.message().className).toBe("error"));
    expect(el.message().textContent).toBe("Could not archive the user. Try again.");
    expect(confirmOverlay().hidden).toBe(true);
  });
});

describe("what the delegation ignores", () => {
  it("a click on the row-actions container itself", async () => {
    const ctx = await withTarget();
    await ctx.user.click(ctx.row().querySelector(".row-actions"));
    expect(requests()).toHaveLength(0);
    expect(document.getElementById("user-name-overlay").hidden).toBe(true);
    expect(confirmOverlay().hidden).toBe(true);
  });

  it.each([["edit-user-name-btn"], ["edit-user-role-btn"]])(
    "%s on a row whose user has left the cache — no prompt", async (className) => {
      const ctx = await withTarget();
      ctx.row().querySelector(`.${className}`).dataset.id = "no-such-user";
      await click(ctx, className);
      expect(requests()).toHaveLength(0);
      expect(document.getElementById("user-name-overlay").hidden).toBe(true);
      expect(document.getElementById("user-role-overlay").hidden).toBe(true);
    });

  it("but Reset Password, Restore and Archive never look the user up at all", async () => {
    // They read `data-id` and `data-name` straight off the button, so a stale
    // row still sends a request for whatever id the markup carries.
    const ctx = await withTarget();
    ctx.row().querySelector(".reset-pw-btn").dataset.id = "no-such-user";
    server.use(http.post("/users/no-such-user/reset-password", () => HttpResponse.json({ ok: true })));

    const clicking = click(ctx, "reset-pw-btn");
    await answerPasswordReset("hunter2");
    await clicking;
    await vi.waitFor(() =>
      expect(requestFor("/users/no-such-user/reset-password", "POST")).not.toBeNull());
  });
});
