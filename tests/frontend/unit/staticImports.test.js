// Every named import across backend/static resolves to a real export.
//
// A browser refuses to link a module graph when one named import has no
// matching export, and the symptom is a blank page with no console error
// visible to the operator. Vite's interop turns that same miss into
// `undefined`, so no behavioural test here can see it. This is the guard:
// static, exhaustive, and cheap.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const STATIC = resolve(HERE, "..", "..", "..", "backend", "static");

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (name.endsWith(".js")) out.push(path);
  }
  return out;
}

const IMPORT_RE = /^import\s+(?:(\w+)\s*,\s*)?(?:\{([^}]*)\}|\*\s+as\s+\w+|(\w+))?\s*(?:from\s*)?["']([^"']+)["']/gm;
const EXPORT_RE = /^export\s+(?:async\s+)?(?:function\*?|const|let|var|class)\s+(\w+)/gm;
const EXPORT_LIST_RE = /^export\s*\{([^}]*)\}/gm;
const EXPORT_DEFAULT_RE = /^export\s+default\b/m;

function exportsOf(path, seen = new Set()) {
  if (seen.has(path)) return new Set();
  seen.add(path);
  const text = readFileSync(path, "utf8");
  const names = new Set();
  for (const m of text.matchAll(EXPORT_RE)) names.add(m[1]);
  for (const m of text.matchAll(EXPORT_LIST_RE)) {
    for (const part of m[1].split(",")) {
      const alias = part.trim().split(/\s+as\s+/);
      if (alias[0]) names.add((alias[1] || alias[0]).trim());
    }
  }
  if (EXPORT_DEFAULT_RE.test(text)) names.add("default");
  // `export { a, b } from "./x.js"` re-exports are matched by EXPORT_LIST_RE
  // by their local names, which is what importers see.
  return names;
}

function namedImports(text) {
  const out = [];
  for (const m of text.matchAll(IMPORT_RE)) {
    const [, defaultName, braces, , spec] = m;
    if (!spec.startsWith(".")) continue;
    const names = [];
    if (defaultName) names.push("default");
    if (braces) {
      for (const part of braces.split(",")) {
        const name = part.trim().split(/\s+as\s+/)[0].trim();
        if (name) names.push(name);
      }
    }
    out.push({ spec, names });
  }
  return out;
}

describe("backend/static named imports", () => {
  it("every named import resolves to an export of the module it names", () => {
    const misses = [];
    for (const file of walk(STATIC)) {
      const text = readFileSync(file, "utf8");
      for (const { spec, names } of namedImports(text)) {
        const target = resolve(dirname(file), spec);
        let available;
        try {
          available = exportsOf(target);
        } catch {
          misses.push(`${file} -> ${spec} (module not found)`);
          continue;
        }
        for (const name of names) {
          if (!available.has(name)) misses.push(`${file}: '${name}' is not exported by ${spec}`);
        }
      }
    }
    expect(misses).toEqual([]);
  });
});
