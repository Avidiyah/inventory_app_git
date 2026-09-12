// Characterization coverage for views/notes.js: the summary items.js renders
// in the Notes cell, the editor's one-row-per-key form and its type ladder,
// and the save path's validation, body, success and failure.
//
// The editor opens the way a user opens it -- the row action `<select>` on a
// loaded row (P5c's pattern, this chunk's setup) -- and saves through its real
// button. `formatNoteValue`, `detectNoteType` and `getNoteValueRaw` are P1's
// unit tests; this file pins what the editor does with them.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import {
  actionSelect, clearRequests, el, mountItems, requestFor, requests, restoreItems, rows,
} from "../helpers/items.js";
import { importView } from "../helpers/shell.js";
import { item as itemFactory } from "../helpers/factories.js";

afterEach(() => restoreItems());

const byId = (id) => document.getElementById(id);
const message = () => byId("notes-message");
const noteRows = () => Array.from(byId("notes-rows").querySelectorAll(".note-row"));
const keyIn = (row) => row.querySelector(".note-key");
const typeIn = (row) => row.querySelector(".note-type");
const valueIn = (row) => row.querySelector(".note-value");
const saveClick = () => byId("notes-save-btn").click();

// One admin row, loaded and ready for its action select. `fake` installs fake
// timers before the mount, for the tests that advance the 1 s auto-close.
async function loadedRow({ role = "admin", fake = false, ...overrides } = {}) {
  if (fake) vi.useFakeTimers();
  const user = userEvent.setup(fake ? { advanceTimers: vi.advanceTimersByTime } : {});
  const target = itemFactory({ name: "Target", ...overrides });
  const mounted = await mountItems({ role, items: [target] });
  await user.click(el.loadAllBtn());
  await vi.waitFor(() => expect(rows()).toHaveLength(1));
  clearRequests();
  return { ...mounted, target, user };
}

async function openNotes(ctx) {
  await ctx.user.selectOptions(actionSelect(0), "notes");
  expect(el.notesSection().hidden).toBe(false);
}

describe("renderNotesSummary", () => {
  async function load() {
    await mountItems({ role: "admin" });
    return importView("views/notes.js");
  }

  it.each([
    ["no notes", {}],
    ["null", null],
    ["a non-object", "nope"],
  ])("%s renders the em-dash span", async (_name, notes) => {
    const { renderNotesSummary } = await load();
    expect(renderNotesSummary(notes)).toBe('<span class="empty">—</span>');
  });

  it("joins key: value pairs through formatNoteValue, escaping both", async () => {
    const { renderNotesSummary } = await load();
    expect(renderNotesSummary({ size: "10mm", count: 4, sealed: true, open: false }))
      .toBe("size: 10mm, count: 4, sealed: true, open: false");
    expect(renderNotesSummary({ "<b>k</b>": "<i>v</i>" }))
      .toBe("&lt;b&gt;k&lt;/b&gt;: &lt;i&gt;v&lt;/i&gt;");
  });

  it("is what the Notes cell of a loaded row shows", async () => {
    await loadedRow({ notes: { size: "10mm", sealed: true } });
    expect(rows()[0].querySelector(".notes-cell").textContent).toBe("size: 10mm, sealed: true");
  });
});

describe("opening the editor", () => {
  it("an item with no notes opens one blank string row", async () => {
    const ctx = await loadedRow({ notes: {} });
    await openNotes(ctx);
    expect(byId("notes-editor-selected").textContent).toBe("Editing notes for: Target");
    expect(noteRows()).toHaveLength(1);
    expect(keyIn(noteRows()[0]).value).toBe("");
    expect(typeIn(noteRows()[0]).value).toBe("string");
    expect(valueIn(noteRows()[0]).type).toBe("text");
    expect(valueIn(noteRows()[0]).value).toBe("");
  });

  it("a row per note, typed by detectNoteType, with the matching value control", async () => {
    const ctx = await loadedRow({ notes: { size: "10mm", count: 4, sealed: true } });
    await openNotes(ctx);
    const [first, second, third] = noteRows();
    expect(noteRows()).toHaveLength(3);
    expect([keyIn(first).value, keyIn(second).value, keyIn(third).value]).toEqual(["size", "count", "sealed"]);
    expect([typeIn(first).value, typeIn(second).value, typeIn(third).value])
      .toEqual(["string", "number", "boolean"]);
    expect(valueIn(first).value).toBe("10mm");
    expect(valueIn(second).type).toBe("number");
    expect(valueIn(second).step).toBe("any");
    expect(valueIn(second).value).toBe("4");
    expect(valueIn(third).tagName).toBe("SELECT");
    expect(valueIn(third).value).toBe("true");
  });

  it("the editing id follows open and close", async () => {
    const ctx = await loadedRow();
    const state = await importView("state.js");
    const notes = await importView("views/notes.js");
    await openNotes(ctx);
    expect(state.getEditingNotesItemId()).toBe(ctx.target.id);
    notes.closeNotesEditor();
    expect(state.getEditingNotesItemId()).toBeNull();
    expect(el.notesSection().hidden).toBe(true);
    expect(noteRows()).toHaveLength(0);
  });

  it("openNotesEditor for an id that is not in the loaded set does nothing", async () => {
    const ctx = await loadedRow();
    const notes = await importView("views/notes.js");
    notes.openNotesEditor("not-a-loaded-id", "Ghost");
    expect(el.notesSection().hidden).toBe(true);
  });
});

describe("the type ladder", () => {
  it.each([
    ["string", "5", "number", "5"],
    ["string", "true", "boolean", "true"],
    ["number", "5", "boolean", "false"],       // anything but true/"true" lands on false
    ["boolean", "true", "string", "true"],
  ])("%s %s -> %s keeps %s", async (fromType, raw, toType, expected) => {
    const ctx = await loadedRow({ notes: {} });
    await openNotes(ctx);
    const row = noteRows()[0];
    await ctx.user.selectOptions(typeIn(row), fromType);
    if (valueIn(row).tagName === "SELECT") await ctx.user.selectOptions(valueIn(row), raw);
    else { valueIn(row).value = raw; }
    await ctx.user.selectOptions(typeIn(row), toType);
    expect(valueIn(row).value).toBe(expected);
  });

  it("Add note appends a blank row and the × removes only its own", async () => {
    const ctx = await loadedRow({ notes: { a: "1", b: "2" } });
    await openNotes(ctx);
    await ctx.user.click(byId("notes-add-row-btn"));
    expect(noteRows()).toHaveLength(3);
    expect(keyIn(noteRows()[2]).value).toBe("");
    await ctx.user.click(noteRows()[0].querySelector(".note-remove-btn"));
    expect(noteRows().map((r) => keyIn(r).value)).toEqual(["b", ""]);
  });
});

describe("saving", () => {
  it("sends each row in its own type, skipping a blank key", async () => {
    const ctx = await loadedRow({ notes: { size: "10mm", count: 4, sealed: true } });
    await openNotes(ctx);
    await ctx.user.click(byId("notes-add-row-btn"));          // a blank row, never sent
    valueIn(noteRows()[3]).value = "orphan";
    server.use(http.patch(`/items/${ctx.target.id}/notes`, () => HttpResponse.json(ctx.target)));
    saveClick();
    await vi.waitFor(() => expect(requestFor(`/items/${ctx.target.id}/notes`, "PATCH")).not.toBeNull());
    expect(requestFor(`/items/${ctx.target.id}/notes`, "PATCH").body)
      .toEqual({ notes: { size: "10mm", count: 4, sealed: true } });
  });

  it("reports success, awaits onSaved, and closes a second later", async () => {
    const ctx = await loadedRow({ fake: true, notes: { size: "10mm" } });
    const notes = await importView("views/notes.js");
    const saved = vi.fn();
    notes.setOnSaved(saved);                                   // replaces items.js's refresh
    await openNotes(ctx);
    server.use(http.patch(`/items/${ctx.target.id}/notes`, () => HttpResponse.json(ctx.target)));
    saveClick();
    await vi.waitFor(() => expect(message().textContent).toBe("Notes saved."));
    expect(message().className).toBe("success");
    expect(saved).toHaveBeenCalledTimes(1);
    expect(el.notesSection().hidden).toBe(false);
    await vi.advanceTimersByTimeAsync(1000);
    expect(el.notesSection().hidden).toBe(true);
  });

  it.each([
    ["two rows share a name", { a: "1" }, (ctx) => {
      byId("notes-add-row-btn").click();
      keyIn(noteRows()[1]).value = "a";
    }, "Two notes share a name. Make each note name different."],
    ["a number row left blank", { count: 4 }, () => { valueIn(noteRows()[0]).value = ""; },
      'Value for "count" is required.'],
  ])("%s is refused: %s", async (_name, notes, mutate, expected) => {
    const ctx = await loadedRow({ notes });
    await openNotes(ctx);
    mutate(ctx);
    saveClick();
    await vi.waitFor(() => expect(message().className).toBe("error"));
    expect(message().textContent).toBe(expected);
    expect(requests()).toHaveLength(0);
  });

  // Characterization (N-P6-CHARACTERIZED): `Invalid number for "k".` is
  // unreachable from this editor. The number type always renders
  // `input[type=number]`, which drops any non-numeric text, so the raw value
  // is "" and the required-value branch answers first.
  it("a number field holding text is refused as invalid", async () => {
    const ctx = await loadedRow({ notes: { count: "abc" } });    // a string note...
    await openNotes(ctx);
    const row = noteRows()[0];
    expect(typeIn(row).value).toBe("string");
    await ctx.user.selectOptions(typeIn(row), "number");         // ...retyped as a number
    valueIn(row).value = "abc";                                  // which a number input drops
    expect(valueIn(row).value).toBe("");
    saveClick();
    await vi.waitFor(() => expect(message().textContent).toBe('Value for "count" is required.'));
    expect(requests()).toHaveLength(0);
  });

  it("a failure keeps the panel open with the detail", async () => {
    const ctx = await loadedRow({ notes: { size: "10mm" } });
    const state = await importView("state.js");
    await openNotes(ctx);
    server.use(http.patch(`/items/${ctx.target.id}/notes`,
      () => HttpResponse.json({ detail: "Notes are locked" }, { status: 500 })));
    saveClick();
    await vi.waitFor(() => expect(message().className).toBe("error"));
    expect(message().textContent).toBe("Notes are locked");
    expect(el.notesSection().hidden).toBe(false);
    expect(state.getEditingNotesItemId()).toBe(ctx.target.id);
  });

  it("Save with nothing open says so and sends nothing", async () => {
    await loadedRow();
    saveClick();
    await vi.waitFor(() => expect(message().textContent).toBe("No item selected."));
    expect(message().className).toBe("error");
    expect(requests()).toHaveLength(0);
  });

  it("Cancel closes the panel and clears it", async () => {
    const ctx = await loadedRow({ notes: { size: "10mm" } });
    const state = await importView("state.js");
    await openNotes(ctx);
    await ctx.user.click(byId("notes-cancel-btn"));
    expect(el.notesSection().hidden).toBe(true);
    expect(noteRows()).toHaveLength(0);
    expect(message().textContent).toBe("");
    expect(state.getEditingNotesItemId()).toBeNull();
  });
});
