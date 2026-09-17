import { beforeEach, describe, expect, it } from "vitest";

// Imported per test: setup.js clears localStorage between tests, but the
// module itself is also reset (vi.resetModules in setup.js), so a fresh
// import per test matches how every other foundation-module suite does this.
let drafts;
beforeEach(async () => {
  drafts = await import("../../../backend/static/workOrderDrafts.js");
});

describe("saveDraft / readDraft / clearDraft", () => {
  it("round-trips a draft, stamped with when it was saved", () => {
    drafts.saveDraft("wo1", "labor", { number: "4242", action: "add-labor", payload: { minutes: 60 } });
    const draft = drafts.readDraft("wo1", "labor");
    expect(draft).toMatchObject({ number: "4242", action: "add-labor", targetId: null, payload: { minutes: 60 } });
    expect(typeof draft.savedAt).toBe("number");
  });

  it("reads back null when nothing was saved", () => {
    expect(drafts.readDraft("wo1", "labor")).toBeNull();
  });

  it("keeps drafts for different sections of the same work order apart", () => {
    drafts.saveDraft("wo1", "labor", { number: "4242", action: "add-labor", payload: { minutes: 60 } });
    drafts.saveDraft("wo1", "notes", { number: "4242", action: "save-notes", payload: { notes: "hi" } });
    expect(drafts.readDraft("wo1", "labor").action).toBe("add-labor");
    expect(drafts.readDraft("wo1", "notes").action).toBe("save-notes");
  });

  it("a later save for the same work order + section overwrites the earlier one", () => {
    drafts.saveDraft("wo1", "labor", { number: "4242", action: "add-labor", payload: { minutes: 30 } });
    drafts.saveDraft("wo1", "labor", { number: "4242", action: "add-labor", payload: { minutes: 90 } });
    expect(drafts.readDraft("wo1", "labor").payload).toEqual({ minutes: 90 });
  });

  it("clearDraft removes it and is a no-op on an already-empty slot", () => {
    drafts.saveDraft("wo1", "labor", { number: "4242", action: "add-labor", payload: { minutes: 60 } });
    drafts.clearDraft("wo1", "labor");
    expect(drafts.readDraft("wo1", "labor")).toBeNull();
    expect(() => drafts.clearDraft("wo1", "labor")).not.toThrow();
  });
});

describe("markDraftError", () => {
  it("attaches the rejection to an existing draft without dropping its payload", () => {
    drafts.saveDraft("wo1", "labor", { number: "4242", action: "add-labor", payload: { minutes: 60 } });
    drafts.markDraftError("wo1", "labor", { status: 400, detail: "No longer assigned." });
    const draft = drafts.readDraft("wo1", "labor");
    expect(draft.payload).toEqual({ minutes: 60 });
    expect(draft.lastError).toEqual({ status: 400, detail: "No longer assigned." });
  });

  it("is a no-op when there is no draft to attach the error to", () => {
    expect(() => drafts.markDraftError("wo1", "labor", { status: 400 })).not.toThrow();
    expect(drafts.readDraft("wo1", "labor")).toBeNull();
  });
});

describe("allDrafts", () => {
  it("is empty with nothing saved", () => {
    expect(drafts.allDrafts()).toEqual([]);
  });

  it("lists every draft across work orders and sections", () => {
    drafts.saveDraft("wo1", "labor", { number: "4242", action: "add-labor", payload: { minutes: 60 } });
    drafts.saveDraft("wo2", "notes", { number: "7", action: "save-notes", payload: { notes: "hi" } });
    const all = drafts.allDrafts();
    expect(all).toHaveLength(2);
    expect(all.map((d) => `${d.workOrderId}:${d.section}`).sort()).toEqual(["wo1:labor", "wo2:notes"]);
  });

  it("does not surface an unrelated key (the resume marker) as a draft", () => {
    drafts.setPendingResume({ workOrderId: "wo1", number: "4242", section: "labor" });
    expect(drafts.allDrafts()).toEqual([]);
  });
});

describe("pending resume", () => {
  it("peek reads without consuming", () => {
    drafts.setPendingResume({ workOrderId: "wo1", number: "4242", section: "labor" });
    expect(drafts.peekPendingResumeNumber()).toBe("4242");
    expect(drafts.peekPendingResumeNumber()).toBe("4242");
  });

  it("peek is null with nothing pending", () => {
    expect(drafts.peekPendingResumeNumber()).toBeNull();
  });

  it("take consumes the one-shot", () => {
    drafts.setPendingResume({ workOrderId: "wo1", number: "4242", section: "labor" });
    expect(drafts.takePendingResume()).toEqual({ workOrderId: "wo1", number: "4242", section: "labor" });
    expect(drafts.takePendingResume()).toBeNull();
    expect(drafts.peekPendingResumeNumber()).toBeNull();
  });
});

describe("storage failure resilience", () => {
  it("readDraft/allDrafts degrade to empty rather than throw when storage is unavailable", () => {
    const originalGetItem = Storage.prototype.getItem;
    Storage.prototype.getItem = () => { throw new DOMException("blocked"); };
    try {
      expect(drafts.readDraft("wo1", "labor")).toBeNull();
      expect(drafts.allDrafts()).toEqual([]);
    } finally {
      Storage.prototype.getItem = originalGetItem;
    }
  });

  it("saveDraft does not throw when storage rejects the write", () => {
    const originalSetItem = Storage.prototype.setItem;
    Storage.prototype.setItem = () => { throw new DOMException("quota"); };
    try {
      expect(() =>
        drafts.saveDraft("wo1", "labor", { number: "4242", action: "add-labor", payload: {} })
      ).not.toThrow();
    } finally {
      Storage.prototype.setItem = originalSetItem;
    }
  });
});
