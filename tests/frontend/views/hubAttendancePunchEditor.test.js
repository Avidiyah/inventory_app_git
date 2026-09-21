// The inline punch editor: what it sends, what it withholds, and the two
// house rules (no nested buttons, no inline styles).
//
// dom.js is mocked so promptTime() is a plain resolved value -- the picker
// itself is P1's and is tested there.

import { beforeEach, describe, expect, it, vi } from "vitest";

const promptTime = vi.fn();
vi.mock("../../../backend/static/dom.js", () => ({ promptTime }));

const { mountPunchEditor } = await import(
  "../../../backend/static/views/hubAttendancePunchEditor.js");

const PUNCH = {
  id: "22222222-2222-4222-8222-222222222222",
  started_at: "2026-09-21T13:00:00.000Z",
  ended_at: "2026-09-21T21:00:00.000Z",
  needs_review: false, minutes: 480, carried: false, open: false,
};

describe("the inline punch editor", () => {
  let host;
  beforeEach(() => {
    document.body.innerHTML = "";
    host = document.createElement("div");
    document.body.appendChild(host);
    promptTime.mockReset();
  });

  it("saves the picked start with the untouched end and the reason", async () => {
    promptTime.mockResolvedValue(new Date("2026-09-21T14:00:00.000Z"));
    const onSave = vi.fn().mockResolvedValue(undefined);
    mountPunchEditor(host, { punch: PUNCH, date: "2026-09-21", onSave });

    host.querySelector(".punch-editor-start").click();
    await Promise.resolve();
    await Promise.resolve();
    host.querySelector(".punch-editor-reason").value = "clocked in late";
    host.querySelector(".punch-editor-save").click();
    await Promise.resolve();

    expect(onSave).toHaveBeenCalledWith({
      startedAt: "2026-09-21T14:00:00.000Z",
      endedAt: "2026-09-21T21:00:00.000Z",
      reason: "clocked in late",
    });
  });

  it("offers no delete when adding, and needs both times before saving", () => {
    const onSave = vi.fn();
    mountPunchEditor(host, { punch: null, date: "2026-09-21", onSave });
    expect(host.querySelector(".punch-editor-delete")).toBeNull();
    host.querySelector(".punch-editor-save").click();
    expect(onSave).not.toHaveBeenCalled();
    expect(host.querySelector(".punch-editor-message").textContent)
      .toMatch(/both a start and an end/i);
  });

  it("emits no nested buttons and no inline styles", () => {
    mountPunchEditor(host, { punch: PUNCH, date: "2026-09-21", onSave: vi.fn() });
    expect(host.querySelector("button button")).toBeNull();
    expect(host.innerHTML).not.toMatch(/\sstyle="/);
  });
});
