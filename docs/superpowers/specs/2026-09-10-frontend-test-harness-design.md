# Frontend test harness — design

The frontend has 54 non-vendor JS files and 16,897 lines under `backend/static`,
and zero automated tests. The backend has a 520-test pytest suite gating every
deploy; the frontend has `node --check`, which proves only that the files parse.

This spec defines a permanent, professional-grade test harness for that
frontend: a fast unit + component inner loop (Vitest + jsdom + Testing Library
+ MSW) and a thin real-browser smoke layer (Python Playwright, reusing the
Playwright already in `requirements.txt`), both wired into the existing CI
deploy gate.

Immediate motivation: `views/workOrders.js` is 2,842 lines and needs to be
split. Splitting it without a net risks silent breakage in wiring that nobody
exercises for weeks. The harness is the net. It outlives that job — every
module gets covered eventually, in phases.

## 1. Decisions

Settled in brainstorming 2026-09-10; recorded so they are not re-argued.

| Question | Decision |
| --- | --- |
| Runner | **Vitest**. ESM-native, runs the app's plain ES modules with no bundler and no build step. Jest would require a transform pipeline this repo does not have and must not grow. |
| DOM | **jsdom**, via Vitest's `environment: "jsdom"`. |
| Queries + events | **@testing-library/dom + @testing-library/user-event**. Query by accessible role/label; dispatch real event sequences. `el.click()` passes on markup a human cannot operate; Testing Library's queries do not. |
| Network | **MSW (`msw/node`)**, intercepting at the `fetch` boundary. The real `api.js` runs under test — content-type handling, the 204 short-circuit, the `{status, detail}` throw shape, the 401 handler. `vi.mock("api.js")` would skip all of it and test a fiction. |
| Unhandled requests | **`onUnhandledRequest: "error"`.** An un-mocked fetch fails the test loudly rather than returning undefined. |
| E2E | **Python Playwright + pytest.** `playwright==1.62.0` is already a runtime dependency and `backend/tests/conftest.py` already stands up app and database. Node Playwright has better DX but means a second browser toolchain, a second CI job, and duplicated DB fixtures. |
| Production code changes | **None.** View modules stay import-time singletons. The harness adapts (§3.2); the app does not get an `init()` retrofit across 54 files. |
| Coverage | **v8 provider**, reported every run. Advisory first, blocking later — the same ratchet this repo used for `pip-audit` (see `.github/workflows/ci.yml`, B4). |
| Location | Repo root (`package.json`, `vitest.config.js`) + `tests/frontend/`. Nothing at root ships: `render.yaml` sets `rootDir: backend` and the Dockerfile copies only `app/ static/ alembic/ scripts/ entrypoint.sh`. |
| Sequencing | Net first, then smoke, then the `workOrders.js` split, then the remaining modules in churn order. The split never lands before its coverage does. |

## 2. Layers

| Layer | Runs | Covers | Speed |
| --- | --- | --- | --- |
| Unit | Vitest, no DOM | Pure functions: `format.js`, `roles.js`, `pricingText.js`, envelope validation in `realtime.js`, `priorityBucket`, `effectiveBillable`, `formatMinutes` | ms |
| Component | Vitest + jsdom | Real page HTML + real view module: rendering, delegated-click branches, filter wiring, error paths | tens of ms |
| E2E smoke | pytest + Playwright + Postgres | Login, navigation, one critical journey per page, CSP, service worker, real fetch | seconds |

The component layer is the load-bearing one. Refactor breakage lives in wiring
— a `data-action` string that no longer matches, a module-level
`getElementById` that now runs before its markup exists, an import cycle — and
that is precisely what the component layer catches and the unit layer does not.

## 3. Harness architecture

### 3.1 The page-shell fixture

`mountShell()` composes the **real** document the server serves, injects it into
a fresh jsdom document, and returns. The view module is imported afterwards, so
its import-time `getElementById` calls and `addEventListener` registrations run
against real markup.

The whole shell is mounted every time, never one page's fragment. The app serves
a single document containing every page (`_assemble_index()`), and modules depend
on that: `views/workOrders.js` captures ids from `shell-head.html`,
`pages/work-orders.html` and `pages/integrations.html` at import time, so a
per-page mount would hand it nulls. The full shell is 82 KB — a few ms of
jsdom parse — so production parity is bought cheaply and no helper has to know
which fragments a module touches.

Source of truth is `backend/app/main.py`'s `SHELL_PARTS` tuple, **read and parsed
at test time**. The helper does not keep its own copy of the part order, so it
cannot drift from what production assembles. Parts are concatenated, both
`<script>` tags in `shell-tail.html` are stripped — the ZXing UMD vendor tag and
the `main.js` module tag, so nothing auto-boots — and the result is written to
the document.

This is what makes the harness worth building: **tests go red when the HTML and
the JS drift apart.** Rename `work-orders-status-filter` in
`pages/work-orders.html` and a test fails, instead of a filter silently going
dead in production.

### 3.2 Module isolation

View modules are stateful singletons that wire themselves on import, and
Vitest caches modules per process. Each test therefore:

1. `vi.resetModules()`
2. `await mountShell()` — DOM must exist first
3. `await import(".../views/workOrders.js")` — fresh instance, wires to the fresh DOM

Order is not optional; importing before mounting captures nulls. The harness
enforces it by exposing a single `mountView(modulePath)` that does all three,
and tests use that rather than composing the steps by hand.

### 3.3 Seams

| Seam | Handling |
| --- | --- |
| `fetch` | MSW handlers. Default handlers return empty-but-valid payloads; tests override per case. |
| Session / role | `setCurrentUser({role})` helper priming `state.js`. Role gating (`isSupervisorPlus`, `isAdminPlus`) is a first-class test dimension, not an afterthought. |
| `realtime.js` | No socket opens at import (`connectRealtime()` is explicit), so it imports safely. Component tests that need a server event mock the module with an `__emit(type, envelope)` helper; `realtime.js` itself gets direct unit tests for envelope validation and reconnect scheduling. |
| `localStorage` | Provided by jsdom; cleared between tests. |
| Timers | `vi.useFakeTimers()` for debounced search and poll loops. |

### 3.4 Layout

```
package.json            # root: npm requires it here; does not ship
vitest.config.js        # root: toolchain manifest, same class as package.json
tests/frontend/
  setup.js              # matchers, MSW lifecycle, per-test cleanup
  helpers/
    shell.js            # mountShell / mountView, SHELL_PARTS parser
    handlers.js         # default MSW handlers
    factories.js        # workOrder(), item(), user() builders
    session.js          # setCurrentUser
  unit/                 # mirrors backend/static/ paths
  views/                # mirrors backend/static/views/ paths
backend/tests/e2e/      # Python Playwright, alongside the existing suite
```

`tests/` at repo root is one of the directories `CLAUDE.md` permits. The two
root config files are the documented exception: npm resolves `package.json`
from the working directory only.

## 4. Test data

Factories, not fixtures files. `workOrder({status: "review"})` returns a
complete valid object with the field under test overridden; every other field
gets a sane default. Tests assert on what they set and stay readable when the
API shape grows a field.

Payload shapes are taken from `docs/endpoint-map.md` and the FastAPI response
models. A factory that drifts from its endpoint produces green tests over a
broken app, so P1 (§ roadmap) covers `api.js` against the real route contracts
first.

## 5. CI

A new `frontend` job in `.github/workflows/ci.yml`:

- `actions/setup-node@v4`, node 20 (matching the existing `static` job), npm cache
- `npm ci`
- `npm run test:ci` → `vitest run --coverage`
- Coverage summary printed; no threshold at first

Added to the `deploy` job's `needs: [backend, static]` → `needs: [backend, static, frontend, e2e]`. The E2E job lands in its own phase and joins `needs` then, not before.

The existing `node --check` step stays: it covers files that have no tests yet,
which for a long while is most of them.

A tests-only push does not deploy — the deploy allowlist already ships only
`backend/`, so root-level test changes fall outside it with no change needed.

## 6. What this does not do

- **No production code refactor.** Not part of this work. Modules become
  testable as they are.
- **No visual regression testing.** Screenshot diffing is a separate decision
  with its own maintenance cost; out of scope.
- **No coverage threshold on day one.** Advisory until the covered surface is
  large enough that a threshold means something, then blocking.
- **No test-writing for all 54 modules up front.** Phased, churn-ordered, one
  bounded scope per session.

## 7. Success criteria

1. `npm test` runs green locally on a clean checkout with no database.
2. A deliberate break — renaming a `data-action` value, or a page-fragment id —
   turns a test red.
3. CI blocks a deploy on a red frontend suite.
4. `views/workOrders.js` reaches coverage sufficient that its split can be
   executed as mechanical motion and verified by the suite, not by clicking.
5. Adding a test for a new module requires no harness changes — only a new file.
