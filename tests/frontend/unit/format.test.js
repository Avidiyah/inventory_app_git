import { describe, expect, it } from "vitest";
import {
  escapeHtml,
  formatHm,
  formatMoney,
  safeHttpUrl,
  formatUserName,
  formatError,
  RANK_CONTAINS, RANK_EXACT, RANK_PREFIX, RANK_TOKENS,
  detectNoteType, filterRanked, formatNoteValue, friendlyError,
  matchesSearch, searchRank, searchTokens,
} from "../../../backend/static/format.js";

describe("escapeHtml", () => {
  it.each([
    [null, ""],
    [undefined, ""],
    ["<script>", "&lt;script&gt;"],
    ["a & b", "a &amp; b"],
    ['say "hi"', "say &quot;hi&quot;"],
    ["it's", "it&#39;s"],
    [42, "42"],
  ])("escapes %p", (input, expected) => {
    expect(escapeHtml(input)).toBe(expected);
  });
});

describe("formatHm", () => {
  it.each([
    [0, "0 m"],
    [12, "12 m"],
    [59, "59 m"],
    [60, "1 h 0 m"],
    [192, "3 h 12 m"],
    [-5, "0 m"],
    [12.4, "12 m"],
  ])("formats %p minutes", (input, expected) => {
    expect(formatHm(input)).toBe(expected);
  });
});

describe("formatMoney", () => {
  it.each([null, undefined, "", "not-a-number"])("returns empty for %p", (input) => {
    expect(formatMoney(input)).toBe("");
  });

  it("formats a number and a Decimal string identically", () => {
    expect(formatMoney(12.5)).toBe(formatMoney("12.5"));
  });

  it("includes the value with two decimal places", () => {
    expect(formatMoney(1234.5)).toMatch(/1,234\.50/);
  });
});

describe("safeHttpUrl", () => {
  it.each([
    ["https://example.com/x", "https://example.com/x"],
    ["  http://example.com  ", "http://example.com"],
    ["javascript:alert(1)", ""],
    ["data:text/html,x", ""],
    ["/relative", ""],
    [null, ""],
  ])("maps %p", (input, expected) => {
    expect(safeHttpUrl(input)).toBe(expected);
  });
});

describe("formatUserName", () => {
  it("prefers full_name", () => {
    expect(formatUserName({ full_name: " Ada Lovelace ", first_name: "X" })).toBe("Ada Lovelace");
  });

  it("falls back to first + last", () => {
    expect(formatUserName({ first_name: "Ada", last_name: "Lovelace" })).toBe("Ada Lovelace");
  });

  it("never leaks a username", () => {
    expect(formatUserName({ username: "ada" })).toBe("Name unavailable");
    expect(formatUserName(null)).toBe("Name unavailable");
  });
});

describe("formatError", () => {
  it("collapses a FastAPI validation array", () => {
    expect(formatError([{ msg: "field required" }, { msg: "too long" }], "x"))
      .toBe("field required; too long");
  });

  it("passes a plain string detail through", () => {
    expect(formatError("Not allowed", "x")).toBe("Not allowed");
  });

  it("falls back when detail is empty", () => {
    expect(formatError("", "Something went wrong")).toBe("Something went wrong");
  });
});

describe("friendlyError", () => {
  it.each([
    [undefined, "Could not reach the app. Check your signal and try again."],
    [{}, "Could not reach the app. Check your signal and try again."],
    [{ status: 401 }, "You were signed out. Sign in again."],
    [{ status: 403 }, "Your account can't do that. Ask a supervisor if this seems wrong."],
    [{ status: 400, detail: "Insufficient stock to dispense." },
      "Not enough stock available. Check the count before taking more out."],
  ])("maps %o to crew-facing copy", (err, expected) => {
    expect(friendlyError(err, "fallback")).toBe(expected);
  });

  it("falls back to the backend detail for anything else", () => {
    expect(friendlyError({ status: 409, detail: "Barcode in use" }, "fallback")).toBe("Barcode in use");
  });

  it("collapses a validation array through formatError", () => {
    expect(friendlyError({ status: 422, detail: [{ msg: "too short" }, { msg: "required" }] }, "fallback"))
      .toBe("too short; required");
  });

  it("uses the fallback when the detail is empty", () => {
    expect(friendlyError({ status: 500, detail: "" }, "Save failed.")).toBe("Save failed.");
  });

  it("treats status 0 as a real status rather than a network failure", () => {
    // `err.status === undefined` is the network test, so 0 falls through to
    // formatError. Recorded, not endorsed.
    expect(friendlyError({ status: 0, detail: "odd" }, "fallback")).toBe("odd");
  });
});

describe("note value helpers", () => {
  it.each([[true, "true"], [false, "false"], [0, 0], ["", ""], [null, null]])(
    "formatNoteValue(%o)", (input, expected) => expect(formatNoteValue(input)).toBe(expected));

  it.each([[true, "boolean"], [3, "number"], ["x", "string"], [null, "string"], [undefined, "string"]])(
    "detectNoteType(%o)", (input, expected) => expect(detectNoteType(input)).toBe(expected));
});

describe("searchTokens", () => {
  it.each([["", []], ['"""', []], ["---", []], ["  ", []], ["PL-C 26W", ["pl", "c", "26w"]]])(
    "tokenises %o", (query, expected) => expect(searchTokens(query)).toEqual(expected));
});

describe("matchesSearch", () => {
  it("matches an empty query against everything", () => {
    expect(matchesSearch(["anything"], "")).toBe(true);
  });

  it("matches across fields, not within one", () => {
    expect(matchesSearch(["Bulb", "Aisle 3"], "bulb aisle")).toBe(true);
  });

  it("finds a squashed form through punctuation", () => {
    expect(matchesSearch(["PL-C 26W Compact Fluorescent"], "plc")).toBe(true);
  });

  it("closes up an inch mark", () => {
    expect(matchesSearch(['2"x4" stud'], "2x4")).toBe(true);
  });

  it("skips null and undefined fields instead of throwing", () => {
    expect(matchesSearch(["Bulb", null, undefined], "bulb")).toBe(true);
  });

  it("requires every token", () => {
    expect(matchesSearch(["Bulb"], "bulb missing")).toBe(false);
  });
});

describe("searchRank", () => {
  it.each([
    [["Gel-Coat"], "gel coat", RANK_EXACT],
    [["Gel-Coat"], "gelcoat", RANK_EXACT],
    [["Gel-Coat Resin"], "gel", RANK_PREFIX],
    [["Marine Gel-Coat Resin"], "gel coat", RANK_CONTAINS],
    [["Marine Resin", "Gel-Coat"], "resin gel", RANK_TOKENS],
  ])("ranks %o against %o", (fields, query, expected) => {
    expect(searchRank(fields, query)).toBe(expected);
  });

  it("ranks a blank query as exact so an unfiltered list keeps its order", () => {
    expect(searchRank(["anything"], "")).toBe(RANK_EXACT);
  });
});

describe("filterRanked", () => {
  const rows = [
    { name: "Marine Gel-Coat Resin" },
    { name: "Gel-Coat" },
    { name: "Gel-Coat Hardener" },
    { name: "Paint Thinner" },
  ];
  const fieldsOf = (row) => [row.name];

  it("floats the exact match above prefix and contains matches", () => {
    expect(filterRanked(rows, fieldsOf, "gelcoat").map((r) => r.name))
      .toEqual(["Gel-Coat", "Gel-Coat Hardener", "Marine Gel-Coat Resin"]);
  });

  it("keeps original order within a rank tier", () => {
    const tied = [{ name: "Zeta Bulb" }, { name: "Alpha Bulb" }];
    expect(filterRanked(tied, fieldsOf, "bulb").map((r) => r.name)).toEqual(["Zeta Bulb", "Alpha Bulb"]);
  });

  it("applies the tiebreak within a tier only", () => {
    const tied = [{ name: "Zeta Bulb" }, { name: "Alpha Bulb" }];
    const byName = (a, b) => a.name.localeCompare(b.name);
    expect(filterRanked(tied, fieldsOf, "bulb", byName).map((r) => r.name)).toEqual(["Alpha Bulb", "Zeta Bulb"]);
  });

  it("returns the whole list unfiltered for a blank query", () => {
    expect(filterRanked(rows, fieldsOf, "")).toHaveLength(4);
  });

  it("returns an empty array when nothing matches", () => {
    expect(filterRanked(rows, fieldsOf, "zzz")).toEqual([]);
  });
});
