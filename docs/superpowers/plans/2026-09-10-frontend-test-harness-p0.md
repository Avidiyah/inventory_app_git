# Frontend Test Harness — P0 (Harness Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a working Vitest + jsdom + Testing Library + MSW harness with the real-shell fixture and a CI gate, proven by one exemplar test per layer — no app coverage yet.

**Architecture:** Root-level npm project (`package.json`, `vitest.config.js`) driving `tests/frontend/`. The fixture reads `SHELL_PARTS` out of `backend/app/main.py` at test time, concatenates the real fragments, strips both `<script>` tags, and replaces the jsdom document — so the app's import-time-singleton view modules wire against production markup. MSW intercepts `fetch`, so the real `api.js` runs under test.

**Tech Stack:** Vitest, jsdom, @testing-library/dom, @testing-library/user-event, msw, @vitest/coverage-v8, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md`
**Roadmap:** `docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md` (P0)

## Global Constraints

- **Tests only.** No changes to any file under `backend/static/` or `backend/app/`. If a test cannot be written without changing production code, stop and raise it.
- **Nothing at root ships.** `render.yaml` sets `rootDir: backend`; the Dockerfile copies only `app/ static/ alembic/ scripts/ entrypoint.sh`. Root `package.json` / `vitest.config.js` / `tests/` are the documented exception to `CLAUDE.md`'s "no working files at root".
- **`onUnhandledRequest: "error"`** — an un-mocked fetch fails the test loudly.
- **No `vi.mock("api.js")`.** The real `api.js` must execute; MSW intercepts at the `fetch` boundary.
- **The fixture never hardcodes the fragment list.** It parses `SHELL_PARTS` from `backend/app/main.py:341`. A hardcoded copy defeats the entire point.
- **Always mount the whole shell**, never one page's fragment. `views/workOrders.js` captures ids from `shell-head.html`, `pages/work-orders.html` *and* `pages/integrations.html` at import time.
- **Node floor:** CI's existing `static` job pins node 20. The `frontend` job must run on a version satisfying the installed vitest's `engines.node`; Task 6 reads it rather than assuming.
- Commit messages end with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `package.json` | devDependencies + `test` / `test:watch` / `test:ci` scripts |
| `vitest.config.js` | jsdom env, setup file, include glob, v8 coverage scope |
| `.gitignore` | append `node_modules/`, `coverage/` |
| `tests/frontend/setup.js` | per-test lifecycle: MSW server, module reset, storage clear |
| `tests/frontend/helpers/shell.js` | `SHELL_PARTS` parser, `mountShell()`, `mountView()` |
| `tests/frontend/helpers/handlers.js` | the shared MSW `server` instance |
| `tests/frontend/helpers/session.js` | `setTestUser()` — primes `state.js` in the current module generation |
| `tests/frontend/helpers/factories.js` | `user()` builder (grown per later phase) |
| `tests/frontend/unit/format.test.js` | unit-layer exemplar |
| `tests/frontend/unit/api.test.js` | MSW error-path exemplar |
| `tests/frontend/helpers/shell.test.js` | the fixture's own tests, incl. the drift guard |
| `tests/frontend/views/workOrders.test.js` | component-layer exemplar |
| `.github/workflows/ci.yml` | new `frontend` job; added to `deploy` `needs` |

---

### Task 1: npm scaffold and Vitest toolchain

**Files:**
- Create: `package.json`, `vitest.config.js`, `tests/frontend/setup.js`, `tests/frontend/toolchain.test.js`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: `npm test` runs `vitest run`; `tests/frontend/**/*.test.js` is the include glob; `tests/frontend/setup.js` is the setup file, exporting nothing (side effects only).

- [ ] **Step 1: Write the failing test**

`tests/frontend/toolchain.test.js` — a throwaway smoke file, deleted in Step 8. It proves the jsdom environment and the setup file are wired, not that any app code works.

```js
import { describe, expect, it } from "vitest";

describe("toolchain", () => {
  it("runs in a jsdom environment", () => {
    expect(typeof document).toBe("object");
    expect(document.createElement("div")).toBeInstanceOf(HTMLElement);
  });

  it("has localStorage", () => {
    localStorage.setItem("k", "v");
    expect(localStorage.getItem("k")).toBe("v");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test`
Expected: FAIL — `npm error Missing script: "test"` (no `package.json` yet).

- [ ] **Step 3: Create `package.json` and install**

```bash
npm init -y
npm pkg set private=true
npm pkg set type=module
npm pkg delete main
npm pkg set scripts.test="vitest run"
npm pkg set scripts.test:watch="vitest"
npm pkg set scripts.test:ci="vitest run --coverage"
npm install -D vitest jsdom @testing-library/dom @testing-library/user-event msw @vitest/coverage-v8
```

`private: true` keeps it unpublishable. `type: module` lets the config and test files use `import` without a `.mjs` extension.

- [ ] **Step 4: Write `vitest.config.js`**

```js
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: false,
    include: ["tests/frontend/**/*.test.js"],
    setupFiles: ["tests/frontend/setup.js"],
    // The app's modules are import-time singletons that capture DOM nodes.
    // A module registry shared across files would leak a dead DOM into the
    // next file, so each test file gets its own worker.
    isolate: true,
    coverage: {
      provider: "v8",
      include: ["backend/static/**/*.js"],
      exclude: ["backend/static/vendor/**"],
      reporter: ["text-summary", "lcov"],
      // Advisory in P0. Turned blocking in P7 at the level then achieved.
      thresholds: undefined,
    },
  },
});
```

- [ ] **Step 5: Write `tests/frontend/setup.js`** (minimal; extended in Task 4)

```js
import { afterEach, beforeEach, vi } from "vitest";

beforeEach(() => {
  // View modules wire themselves on import and Vitest caches modules per
  // process. Without this, the second test in a file re-uses the first
  // test's instance, still bound to the first test's (discarded) DOM.
  vi.resetModules();
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
});
```

- [ ] **Step 6: Run test to verify it passes**

Run: `npm test`
Expected: PASS — 2 tests in `tests/frontend/toolchain.test.js`.

- [ ] **Step 7: Append to `.gitignore`**

```
# Frontend test harness (root-level npm project; nothing here ships)
node_modules/
coverage/
```

- [ ] **Step 8: Delete the throwaway file and confirm the runner is not vacuous**

```bash
rm tests/frontend/toolchain.test.js
npm test
```
Expected: FAIL — "No test files found". That is the point: it proves the include glob is real. Task 2 supplies the first keeper test.

- [ ] **Step 9: Commit**

```bash
git add package.json package-lock.json vitest.config.js tests/frontend/setup.js .gitignore
git commit -m "add the Vitest + jsdom toolchain for frontend tests"
```

---

### Task 2: Unit-layer exemplar — `format.js`

Proves the app's plain ES modules import and run under Vitest with no bundler and no transform.

**Files:**
- Create: `tests/frontend/unit/format.test.js`

**Interfaces:**
- Consumes: Task 1's runner.
- Produces: the precedent that app modules are imported by relative path from the test file — `../../../backend/static/<path>.js`.

- [ ] **Step 1: Write the failing test**

Signatures read from `backend/static/format.js`. `formatMoney` uses `toLocaleString` with `style: "currency"`, so assert on the numeric core rather than a hardcoded glyph — ICU output varies by node build.

```js
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
```

- [ ] **Step 2: Run and verify**

Run: `npm test`
Expected: PASS.

If any case fails, the assertion is wrong about production behaviour — **fix the test, not `format.js`.** These are characterization tests; a genuine bug found here gets filed to `docs/open-work.md`, not fixed in this phase.

- [ ] **Step 3: Commit**

```bash
git add tests/frontend/unit/format.test.js
git commit -m "cover format.js as the unit-layer exemplar"
```

---

### Task 3: The shell fixture

The load-bearing piece. This is what makes HTML/JS drift go red.

**Files:**
- Create: `tests/frontend/helpers/shell.js`, `tests/frontend/helpers/shell.test.js`

**Interfaces:**
- Consumes: Task 1's runner.
- Produces:
  - `shellParts(): string[]` — fragment paths parsed from `backend/app/main.py`. Throws if the tuple is missing.
  - `assembleShell(): string` — the concatenated HTML, scripts stripped.
  - `mountShell(): void` — replaces `document.documentElement` with the assembled shell.
  - `async mountView(modulePath: string): Promise<Module>` — `mountShell()` then `await import(...)`, in that order. `modulePath` is relative to `backend/static/`, e.g. `"views/workOrders.js"`.

- [ ] **Step 1: Write the failing test**

```js
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/frontend/helpers/shell.test.js`
Expected: FAIL — cannot resolve `./shell.js`.

- [ ] **Step 3: Write `tests/frontend/helpers/shell.js`**

```js
// The page-shell fixture.
//
// Composes the REAL document the server serves and injects it into jsdom, so
// view modules -- which capture element ids at import time -- wire against
// production markup. Rename an id in a fragment and the tests that use it go
// red, instead of a control silently going dead in production.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const REPO_ROOT = fileURLToPath(new URL("../../../", import.meta.url));
const STATIC_DIR = join(REPO_ROOT, "backend", "static");
const MAIN_PY = join(REPO_ROOT, "backend", "app", "main.py");

// Source of truth is main.py, read at test time. A hardcoded copy of the
// fragment order here would drift from what production assembles, which is
// exactly the failure this fixture exists to prevent.
export function shellParts() {
  const source = readFileSync(MAIN_PY, "utf8");
  const match = source.match(/^SHELL_PARTS\s*=\s*\(([\s\S]*?)^\)/m);
  if (!match) {
    throw new Error(
      `SHELL_PARTS tuple not found in ${MAIN_PY}. If it was renamed or ` +
      `reformatted, update this parser -- do not hardcode the list.`,
    );
  }
  const parts = [...match[1].matchAll(/"([^"]+\.html)"/g)].map((m) => m[1]);
  if (!parts.length) throw new Error("SHELL_PARTS matched but yielded no fragments");
  return parts;
}

export function assembleShell() {
  const html = shellParts()
    .map((part) => readFileSync(join(STATIC_DIR, part), "utf8"))
    .join("");
  // shell-tail.html carries two: the ZXing UMD vendor tag and the main.js
  // module tag. Neither may run -- main.js boots every view against a DOM
  // the test has not arranged yet.
  return html.replace(/<script\b[\s\S]*?<\/script>/gi, "");
}

export function mountShell() {
  const parsed = new DOMParser().parseFromString(assembleShell(), "text/html");
  document.replaceChild(
    document.importNode(parsed.documentElement, true),
    document.documentElement,
  );
}

// The only supported way to load a view module.
//
// Order is not optional: the module's top-level getElementById calls run at
// import time, so importing before mounting captures nulls and every
// assertion afterwards is testing a corpse.
export async function mountView(modulePath) {
  mountShell();
  return import(/* @vite-ignore */ join(STATIC_DIR, modulePath));
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run tests/frontend/helpers/shell.test.js`
Expected: PASS — 7 tests.

If `mountView`'s dynamic import of an absolute Windows path fails to resolve, convert it with `pathToFileURL(...).href` from `node:url` before importing, and note why in a comment.

- [ ] **Step 5: Prove the drift guard actually guards**

```bash
sed -i 's/^SHELL_PARTS = (/SHELL_PARTSX = (/' backend/app/main.py
npx vitest run tests/frontend/helpers/shell.test.js
```
Expected: FAIL with the "SHELL_PARTS tuple not found" message — not a null-reference crash.

```bash
git checkout backend/app/main.py
npx vitest run tests/frontend/helpers/shell.test.js
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/frontend/helpers/shell.js tests/frontend/helpers/shell.test.js
git commit -m "add the real-shell jsdom fixture parsed from SHELL_PARTS"
```

---

### Task 4: MSW lifecycle and the `api.js` error-path exemplar

**Files:**
- Create: `tests/frontend/helpers/handlers.js`, `tests/frontend/unit/api.test.js`
- Modify: `tests/frontend/setup.js`

**Interfaces:**
- Consumes: Task 1's setup file.
- Produces: `server` (an `msw/node` `SetupServerApi`) and `defaultHandlers` (array) exported from `helpers/handlers.js`. Tests add per-case handlers with `server.use(...)`; `setup.js` resets them after each test.

- [ ] **Step 1: Write the failing test**

`apiGetWorkOrder` is `backend/static/api.js:534` — `GET /work-orders/{id}`, straight through `parseResponse`. It exercises the whole error contract in one small surface.

```js
import { beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";

// Imported fresh per test: api.js holds `unauthorizedHandler` in module scope,
// and setup.js resets the module registry between tests.
let api;
beforeEach(async () => {
  api = await import("../../../backend/static/api.js");
});

describe("apiGetWorkOrder", () => {
  it("returns the parsed body on 200", async () => {
    server.use(http.get("/work-orders/:id", () => HttpResponse.json({ id: 7, number: "WO-7" })));
    await expect(api.apiGetWorkOrder(7)).resolves.toEqual({ id: 7, number: "WO-7" });
  });

  it("throws {status, detail} on a 422 validation error", async () => {
    server.use(http.get("/work-orders/:id", () =>
      HttpResponse.json({ detail: [{ msg: "value is not a valid integer" }] }, { status: 422 })));
    await expect(api.apiGetWorkOrder("abc")).rejects.toEqual({
      status: 422,
      detail: [{ msg: "value is not a valid integer" }],
    });
  });

  it("throws the string detail on a 403", async () => {
    server.use(http.get("/work-orders/:id", () =>
      HttpResponse.json({ detail: "Not allowed" }, { status: 403 })));
    await expect(api.apiGetWorkOrder(7)).rejects.toEqual({ status: 403, detail: "Not allowed" });
  });

  it("fires the unauthorized handler on a 401, and still throws", async () => {
    const onUnauthorized = vi.fn();
    api.setUnauthorizedHandler(onUnauthorized);
    server.use(http.get("/work-orders/:id", () =>
      HttpResponse.json({ detail: "Not authenticated" }, { status: 401 })));
    await expect(api.apiGetWorkOrder(7)).rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("short-circuits a 204 to null", async () => {
    server.use(http.get("/work-orders/:id", () => new HttpResponse(null, { status: 204 })));
    await expect(api.apiGetWorkOrder(7)).resolves.toBeNull();
  });

  it("falls back to the raw text when the body is not JSON", async () => {
    server.use(http.get("/work-orders/:id", () =>
      new HttpResponse("upstream exploded", { status: 502 })));
    await expect(api.apiGetWorkOrder(7)).rejects.toEqual({
      status: 502,
      detail: "upstream exploded",
    });
  });
});

describe("unhandled requests", () => {
  it("fail loudly rather than resolving to undefined", async () => {
    // No handler registered for this path.
    await expect(api.apiGetHub()).rejects.toBeDefined();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/frontend/unit/api.test.js`
Expected: FAIL — cannot resolve `../helpers/handlers.js`.

- [ ] **Step 3: Write `tests/frontend/helpers/handlers.js`**

```js
// MSW intercepts at the `fetch` boundary so the REAL api.js executes --
// content-type handling, the 204 short-circuit, the {status, detail} throw
// shape, the 401 hook. Mocking api.js itself would test a fiction.

import { setupServer } from "msw/node";

// Deliberately empty. A default that quietly answers every request turns an
// un-stubbed endpoint into a silent pass; tests declare what they need with
// server.use(). Shared defaults get added here per phase as they earn it.
export const defaultHandlers = [];

export const server = setupServer(...defaultHandlers);
```

- [ ] **Step 4: Replace `tests/frontend/setup.js`**

```js
import { afterAll, afterEach, beforeAll, beforeEach, vi } from "vitest";
import { server } from "./helpers/handlers.js";

beforeAll(() => {
  // An un-mocked fetch must fail the test, not resolve to undefined and
  // leave a green test standing over a broken call.
  server.listen({ onUnhandledRequest: "error" });
});

beforeEach(() => {
  // View modules wire themselves on import and Vitest caches modules per
  // process. Without this, the second test in a file re-uses the first
  // test's instance, still bound to the first test's (discarded) DOM.
  vi.resetModules();
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  server.resetHandlers();
  vi.useRealTimers();
});

afterAll(() => {
  server.close();
});
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `npx vitest run tests/frontend/unit/api.test.js`
Expected: PASS — 7 tests.

If MSW does not match the relative path `/work-orders/:id`, set `environmentOptions: { jsdom: { url: "http://localhost:3000" } }` in `vitest.config.js` and use absolute handler URLs (`http://localhost:3000/work-orders/:id`). Record which form worked in a comment in `handlers.js` so later phases do not rediscover it.

- [ ] **Step 6: Commit**

```bash
git add tests/frontend/helpers/handlers.js tests/frontend/setup.js tests/frontend/unit/api.test.js
git commit -m "wire MSW and cover the api.js error contract"
```

---

### Task 5: Session helper, factories, and the component-layer exemplar

**Files:**
- Create: `tests/frontend/helpers/session.js`, `tests/frontend/helpers/factories.js`, `tests/frontend/views/workOrders.test.js`

**Interfaces:**
- Consumes: `mountShell` / `mountView` (Task 3), `server` (Task 4).
- Produces:
  - `user(overrides = {}) -> {id, username, full_name, first_name, last_name, role}` — defaults to `role: "technician"`.
  - `async setTestUser(overrides = {}) -> user` — dynamically imports `state.js` and calls its `setCurrentUser`.

**Why `setTestUser` is async:** `state.js` is a module singleton too. `setup.js` calls `vi.resetModules()` per test, so the helper must import `state.js` *inside* the test's module generation — a top-level static import would prime a different copy than the view module reads.

- [ ] **Step 1: Write the failing test**

```js
import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { mountShell, mountView } from "../helpers/shell.js";
import { server } from "../helpers/handlers.js";
import { setTestUser } from "../helpers/session.js";
import { user } from "../helpers/factories.js";

describe("the shell markup the module binds to", () => {
  it("renders the status filter with its seven statuses plus 'All'", () => {
    mountShell();
    const select = document.getElementById("work-orders-status-filter");
    const values = [...select.options].map((o) => o.value);
    expect(values).toEqual([
      "", "created", "assigned", "in_progress",
      "on_hold", "ready_to_complete", "completed", "review",
    ]);
    expect(select.options[0].textContent).toBe("All statuses");
  });

  it("has a label bound to the filter", () => {
    mountShell();
    const label = document.querySelector('label[for="work-orders-status-filter"]');
    expect(label).not.toBeNull();
    expect(label.textContent).toContain("Status");
  });
});

describe("views/workOrders.js", () => {
  it("imports against the real shell and exposes its public surface", async () => {
    await setTestUser({ role: "admin" });
    const mod = await mountView("views/workOrders.js");
    // The eleven exports P4 must preserve start here. Spot-check the ones
    // other modules import today.
    for (const name of [
      "soloNumberFromPath", "focusWorkOrder", "workOrderCardClass",
      "loadWorkOrders", "loadIntegrationsPage", "mountWorkOrderList",
    ]) {
      expect(typeof mod[name], name).toBe("function");
    }
  });

  it("captured live nodes, not nulls", async () => {
    await setTestUser({ role: "admin" });
    const mod = await mountView("views/workOrders.js");
    server.use(http.get("/work-orders", () => HttpResponse.json([])));
    server.use(http.get("/work-orders/filter-options", () => HttpResponse.json({})));
    // If the module had captured nulls, this throws on a property access
    // rather than rendering an empty list.
    await mod.loadWorkOrders();
    expect(document.getElementById("work-orders-list")).not.toBeNull();
  });
});

describe("setTestUser", () => {
  it("primes state.js in the module generation the view sees", async () => {
    await setTestUser({ role: "supervisor" });
    const state = await import("../../../backend/static/state.js");
    expect(state.getRole()).toBe("supervisor");
  });

  it("defaults to a technician", () => {
    expect(user().role).toBe("technician");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run tests/frontend/views/workOrders.test.js`
Expected: FAIL — cannot resolve `../helpers/session.js`.

- [ ] **Step 3: Write `tests/frontend/helpers/factories.js`**

```js
// Factories, not fixture files: every field gets a sane default and the test
// overrides only what it is asserting on. Adding a field to the API shape is
// then one edit here, not one per test.

let seq = 0;

export function user(overrides = {}) {
  seq += 1;
  return {
    id: seq,
    username: `user${seq}`,
    full_name: `Test User ${seq}`,
    first_name: "Test",
    last_name: `User ${seq}`,
    role: "technician",
    ...overrides,
  };
}
```

- [ ] **Step 4: Write `tests/frontend/helpers/session.js`**

```js
// Role gating is a first-class test dimension here, so priming the session is
// a one-liner rather than boilerplate in every test.

import { user } from "./factories.js";

// state.js is a module singleton and setup.js resets the module registry per
// test, so state.js MUST be imported inside the test's generation -- a static
// import at the top of this file would prime a different copy of the module
// than the view under test reads from.
export async function setTestUser(overrides = {}) {
  const state = await import("../../../backend/static/state.js");
  const current = user(overrides);
  state.setCurrentUser(current);
  return current;
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `npx vitest run tests/frontend/views/workOrders.test.js`
Expected: PASS — 6 tests.

The `loadWorkOrders()` case may reveal further fetches the module makes on load. Each un-stubbed one fails loudly by design: read the error, add the matching `server.use(...)`, re-run. **Do not relax `onUnhandledRequest`.**

- [ ] **Step 6: Run the whole suite**

Run: `npm test`
Expected: PASS — every file green, no database running.

- [ ] **Step 7: Commit**

```bash
git add tests/frontend/helpers/session.js tests/frontend/helpers/factories.js tests/frontend/views/workOrders.test.js
git commit -m "add the session and factory helpers with a component-layer exemplar"
```

---

### Task 6: CI gate and the P0 success check

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `npm ci` + `npm run test:ci` from Task 1.
- Produces: a `frontend` job that the `deploy` job requires.

- [ ] **Step 1: Determine the node version the toolchain needs**

```bash
node -p "require('./node_modules/vitest/package.json').engines.node"
```
Use `"20"` if that range admits it (matching the existing `static` job). If it does not, use the lowest LTS it does admit and add a one-line comment in the workflow naming the dependency that forced it.

- [ ] **Step 2: Add the `frontend` job**

Insert after the `static` job, before `deploy`, in `.github/workflows/ci.yml`:

```yaml
  frontend:
    name: Frontend tests
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm

      - name: Install
        run: npm ci

      # Coverage is ADVISORY here. It goes blocking in P7 at the level then
      # achieved, minus a margin -- the same ratchet pip-audit used in B4.
      - name: Vitest
        run: npm run test:ci
```

The existing `node --check` step in `static` stays: it covers the files that have no tests yet, which for a long while is most of them.

- [ ] **Step 3: Add `frontend` to the deploy gate**

In the `deploy` job, change:

```yaml
    needs: [backend, static]
```

to:

```yaml
    needs: [backend, static, frontend]
```

Update the surrounding comment's wording to "a red backend, static, or frontend job means this never starts". The `e2e` job joins `needs` in P3, not now.

- [ ] **Step 4: Verify the workflow parses**

```bash
python -c "import yaml; d=yaml.safe_load(open('.github/workflows/ci.yml')); print(sorted(d['jobs'])); print(d['jobs']['deploy']['needs'])"
```
Expected: the job list includes `frontend`; `needs` prints `['backend', 'static', 'frontend']`.

- [ ] **Step 5: Run the P0 success check — a real break must go red**

```bash
sed -i 's/work-orders-status-filter/work-orders-status-filterX/g' backend/static/pages/work-orders.html
npm test
```
Expected: **FAIL** in `tests/frontend/views/workOrders.test.js` — the status-filter assertions can no longer find the element.

```bash
git checkout backend/static/pages/work-orders.html
npm test
```
Expected: PASS.

This is the criterion the whole phase exists to satisfy: HTML and JS drifting apart turns a test red. If the suite stayed green through the rename, P0 is **not done** — the fixture is not binding to real markup.

- [ ] **Step 6: Confirm a tests-only push does not deploy**

Read the deploy job's allowlist step. It ships only `backend/`, so root-level test changes fall outside it with no change needed. Confirm by reading — do not push to test this.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "gate deploys on the frontend test suite"
```

- [ ] **Step 8: Push and confirm CI is green**

**Ask the user before pushing.** Merging to `main` deploys to production, and this repo's CI gate has previously failed to stop a deploy. After the push, confirm the `frontend` job is green in Actions.

```bash
git push origin main
```

---

## Done when

1. `npm test` is green on a clean checkout with no database running.
2. Renaming `work-orders-status-filter` in `pages/work-orders.html` turns a test red; reverting turns it green (Task 6, Step 5).
3. Renaming `SHELL_PARTS` in `main.py` fails with the parser's own error message, not a crash (Task 3, Step 5).
4. The `frontend` job is in `deploy`'s `needs` and green in Actions.
5. Adding a test for a new module requires only a new file — no harness change.

## Deliberately not in P0

- Coverage of app modules beyond the three exemplars. That is P1 and P2.
- A coverage threshold. Advisory until P7.
- The E2E layer and its `e2e` CI job. That is P3.
- Any change to a file under `backend/static/`.

## A note on Testing Library

`@testing-library/dom` and `@testing-library/user-event` are installed in Task 1
but deliberately unused by the P0 exemplars — those assert on shell markup and
module wiring, where `getElementById` is the honest query. From P1 onward,
interaction tests query by accessible role/label and dispatch through
`user-event`: `el.click()` passes on markup a human cannot operate, and
Testing Library's queries do not.
