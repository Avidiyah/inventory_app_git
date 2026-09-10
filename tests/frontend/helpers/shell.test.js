import { describe, expect, it } from "vitest";
import { assembleShell, mountShell, shellParts } from "./shell.js";

describe("shellParts", () => {
  it("parses SHELL_PARTS out of main.py", () => {
    const parts = shellParts();
    expect(parts[0]).toBe("shell-head.html");
    expect(parts.at(-1)).toBe("shell-tail.html");
    expect(parts).toContain("pages/work-orders.html");
    expect(parts).toContain("pages/integrations.html");
    // A floor, not an exact count -- adding a page must not go red.
    expect(parts.length).toBeGreaterThanOrEqual(16);
  });

  it("keeps no copy of its own, so it cannot drift", async () => {
    const { readFileSync } = await import("node:fs");
    const source = readFileSync("tests/frontend/helpers/shell.js", "utf8");
    expect(source).not.toMatch(/pages\/work-orders\.html/);
  });
});

describe("assembleShell", () => {
  it("strips every script tag so nothing auto-boots", () => {
    expect(assembleShell()).not.toMatch(/<script/i);
  });

  it("contains markup from head, a page, and tail", () => {
    const html = assembleShell();
    expect(html).toContain("work-orders-status-filter");
    expect(html).toContain("integrations-import-section");
  });
});

describe("mountShell", () => {
  it("puts the real markup into the document", () => {
    mountShell();
    const select = document.getElementById("work-orders-status-filter");
    expect(select).not.toBeNull();
    expect(select.tagName).toBe("SELECT");
    expect(document.getElementById("integrations-import-section")).not.toBeNull();
  });

  it("is idempotent within a test", () => {
    mountShell();
    mountShell();
    expect(document.querySelectorAll("#work-orders-status-filter")).toHaveLength(1);
  });

  it("leaves no executable script in the document", () => {
    mountShell();
    expect(document.querySelectorAll("script")).toHaveLength(0);
  });
});
