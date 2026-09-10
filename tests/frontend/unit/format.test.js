import { describe, expect, it } from "vitest";
import {
  escapeHtml,
  formatHm,
  formatMoney,
  safeHttpUrl,
  formatUserName,
  formatError,
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
