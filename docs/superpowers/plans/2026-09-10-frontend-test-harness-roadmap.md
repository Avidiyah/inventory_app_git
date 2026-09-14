# Frontend test harness — roadmap

Phased delivery of `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md`.

P0–P4 are one bounded session each, ordered by dependency, and must run in
sequence. P5–P7 are churn-ordered, may be re-prioritised as the app changes,
and are **chunked**: one module (or one tightly coupled group) per
session-sized chunk, each independently committable and independently green.
A phase — or a chunk — lands green and committed before the next begins.

**Standing rules for every phase**

- Tests only. No production JS changes except where a phase says otherwise (only P4 does).
- A phase is done when `npm test` is green, CI is green, and the phase's own success check passes.
- If a test cannot be written without changing production code, stop and raise it — do not quietly refactor to suit the test.

**Status — 2026-09-14**

| Phase | State |
| --- | --- |
| P0–P3 | Landed. `npm test`: 819 tests / 27 files, ~50 s, green. `pytest -m e2e` green. |
| P4 | Landed 2026-09-11 in nine commits. `workOrders.js` is a 24-line barrel over eight modules, largest 752 lines; no behaviour test was edited to accommodate a move. |
| P5 | Landed 2026-09-11 in eight chunks (P5a–P5h), `2026-09-10-frontend-test-harness-p5.md`. Suite: 1286 tests / 40 files, ~135 s locally (`maxWorkers: 4`, shell memoised), green. Findings under N-P5-CHARACTERIZED in `docs/open-work.md`. Coverage gate still advisory (`thresholds: undefined`); `npm run test:ci` statements at close: 70.91% statements / 72.45% lines (5431/7659, 4922/6793). |
| P6 | Landed 2026-09-14 in seven chunks (P6a–P6g), `2026-09-11-frontend-test-harness-p6.md`. Suite: 1738 tests / 62 files, ~165–220 s locally, green. Findings under N-P6-CHARACTERIZED in `docs/open-work.md`. Coverage gate still advisory (`thresholds: undefined`); `npm run test:ci` at close: 82.56% statements / 84.16% lines (6324/7659, 5721/6797). |
| P7 | Not started — the only uncovered phase. |

P0–P6f went through CI when `main` was pushed 2026-09-13 (green at
`daf451e` after four test-only fixes); P6g's commits are local until the next
push. Pushing `main` deploys production — an owner decision.

## Ordering rationale

The net comes before the thing it protects. `workOrders.js` coverage (P2) and
the E2E smoke layer (P3) both land before the split (P4), because a refactor
verified by clicking is the exact failure this whole effort exists to prevent.

Coverage order after that follows **git churn**, not file size — the files
edited most are the files where a regression is most likely and a test pays
back soonest.

| File | Commits | Phase |
| --- | --- | --- |
| `views/workOrders.js` | 73 | P2 |
| `api.js` | 56 | P1 |
| `views/nav.js` | 23 | P5 |
| `views/items.js` | 23 | P5 |
| `main.js` | 20 | P5 |
| `views/transactions.js` | 19 | P5 |
| `views/history.js` | 17 | P5 |
| `views/userHub.js` | 16 | P5 |
| `views/scan.js` | 16 | P5 |
| `views/auth.js` | 14 | P5 |
| `views/massStage.js` | 12 | P5 |
| `dom.js` `state.js` `format.js` `tips.js` | 7–9 | P1 (foundation) |
| `views/hub*.js` `users` `tools` `itemEditor` `addBarcode` | 4–11 | P6 |
| everything remaining | ≤4 | P7 |

---

## P0 — Harness foundation

**Goal.** A working Vitest + jsdom + Testing Library + MSW setup, the shell
fixture, and a CI job — proven by one exemplar test per layer. No app coverage yet.

**Files.** `package.json`, `vitest.config.js`, `tests/frontend/setup.js`,
`tests/frontend/helpers/{shell,handlers,factories,session}.js`,
`.github/workflows/ci.yml`, `.gitignore`.

**Steps.**
1. `package.json` at root: `vitest`, `jsdom`, `@testing-library/dom`, `@testing-library/user-event`, `msw`, `@vitest/coverage-v8`. Scripts: `test`, `test:watch`, `test:ci`.
2. `vitest.config.js`: `environment: "jsdom"`, `setupFiles`, `include: ["tests/frontend/**/*.test.js"]`, v8 coverage over `backend/static/**` excluding `vendor/`.
3. `setup.js`: Testing Library cleanup, MSW `setupServer` lifecycle with `onUnhandledRequest: "error"`, `localStorage` clear, `vi.resetModules()` per test.
4. `helpers/shell.js`: parse `SHELL_PARTS` out of `backend/app/main.py`, read those files, strip both `<script>` tags in `shell-tail.html` (ZXing UMD + `main.js` module), write to document. Export `mountShell()` and `mountView(modulePath)`.
5. `helpers/session.js`, `helpers/factories.js`, `helpers/handlers.js` — minimal, grown per phase.
6. Exemplars: one unit test (`format.js`), one component test (mount the shell, import `views/workOrders.js`, assert the status filter renders its options), one MSW error-path test (`api.js` throws `{status, detail}` on a 422).
7. CI: `frontend` job per spec §5, added to `deploy` `needs`. Coverage advisory.
8. `node_modules/`, `coverage/` to `.gitignore`.

**Test.** `npm test` green on a clean checkout with no database. CI `frontend` job green.

**Success check.** Rename `work-orders-status-filter` in `pages/work-orders.html`, confirm the component exemplar goes red, revert.

---

## P1 — Foundation-layer coverage

**Goal.** Cover the layer everything else imports. `api.js` first — a wrong
factory shape produces green tests over a broken app, and `api.js` is where the
real contract lives.

**Files (tests only).** `tests/frontend/unit/` for `api.js`, `format.js`,
`roles.js`, `state.js`, `dom.js`, `pricingText.js`, `skeleton.js`, `tips.js`,
`tooltip.js`, `realtime.js`, `itemSave.js`, `adminReviewReceipt.js`.

**Steps.**
1. `api.js` (841 lines, 56 commits): per-endpoint tests via MSW — success shape, 204 → `null`, non-2xx → `{status, detail}`, 401 → `unauthorizedHandler` fires. Cross-check paths against `docs/endpoint-map.md`; any mismatch found is a real bug, report it rather than matching the test to the code.
2. `format.js`, `roles.js`, `pricingText.js` — pure, table-driven tests including boundaries and malformed input.
3. `state.js` — accessor round-trips, reset semantics, no cross-test leakage.
4. `dom.js` — `setMessage`, `confirmDialog`, `messageDialog` against a mounted shell; assert focus handling and that dialogs resolve.
5. `tooltip.js` / `tips.js` — every `data-tip` key in the HTML resolves to copy in `tips.js`. A missing key is a silent empty tooltip today.
6. `realtime.js` — envelope validation (the three-key check), reconnect backoff with fake timers, `subscribe`/dispatch routing. No real socket.
7. Promote factories in `helpers/factories.js` to match the verified `api.js` shapes.

**Test.** Foundation files at high line coverage; the exact number is recorded, not gated.

**Success check.** The `data-tip` audit either passes or produces a list of missing keys filed to `docs/open-work.md`.

---

## P2 — `workOrders.js` characterization coverage

**Goal.** Pin current behaviour of the 2,842-line file precisely enough that the
P4 split can be verified by the suite. These are *characterization* tests: they
record what the code does today, bugs included. A suspected bug gets filed, not
fixed — fixing and refactoring in the same window is how silent breakage hides.

**Files.** `tests/frontend/views/workOrders/{render,actions,filters,solo,integrations}.test.js`.

**Steps.**
1. **Render** — card summary and body for each status, priority bucket and urgent-fire class, `placeMeta` composition, labor section, materials lines and totals, `workOrderCardClass` (also consumed by `adminReview.js` and `transactions.js`), skeleton → loaded transition.
2. **Actions** — all 26 delegated `data-action` branches: `start-tracking-wo`, `stop-tracking-wo`, `notify-supervisor-wo`, `send-back-wo`, `hold-assigned-wo`, `resume-assigned-wo`, `complete-wo`, `review-wo`, `reopen-wo`, `archive-wo`, `cancel-edit`, `save-details`, `save-notes`, `add-labor`, `edit-labor`, `remove-labor`, `add-item`, `edit-item`, `remove-item`, `pick-item`, `pick-technician`, `remove-technician`, `toggle-combo`, `pick-combo-option`, `back-to-work-orders`, `open-netfacilities-wo`. Each: correct request issued, correct DOM result, correct error surfaced on failure.
3. **Role gating** — every action re-run across technician / supervisor / admin / owner. `canEditLabor`, `canCurrentUserSendToReview`, `isAssignedToCurrentUser`, `isSupervisorPlus`, `isAdminPlus`.
4. **Filters, sort, search** — each filter control triggers a reload with the right params; `resetFilterControls`; debounced location/task search with fake timers; sort persistence through `localStorage`; the archived-number restore prompt; the `RECENT_LIMIT` / show-all cap.
5. **Solo card** — `soloNumberFromPath`, enter/exit solo, `history.pushState` payload, popstate both directions, scroll stamp/restore, `renderSoloError`.
6. **Realtime** — matching card refreshes, unknown id ignored, held card defers and catches up on toggle, reconnect triggers a list refetch. Driven through the real dispatch path (`installFakeWebSocket()` → `connectRealtime()` → push a frame), not a mocked emitter: `realtime.js` exports no `__emit` hook and adding one would be a production change. This also exercises `parseEnvelope` and the generation guards.
7. **Integrations block** — import summary, export scopes, NetFacilities poll states, cloud sign-in control states. Owns the Integrations page too; the full-shell mount already provides it.

**Test.** Every `data-action` string in the file appears in at least one test. Assert this mechanically: a meta-test greps the actions out of the source and fails on any without coverage.

**Success check.** The meta-test passes, so P4 cannot delete or mistype an action without going red.

---

## P3 — E2E smoke layer

**Goal.** A thin real-browser layer over the real app and a real database.
Catches what jsdom structurally cannot: CSP (which silently drops inline
styles here), service worker, real fetch, real rendering.

**Files.** `backend/tests/e2e/{conftest.py,_availability.py,_seed.py,test_availability.py,test_smoke.py,test_work_orders.py}`, `backend/pytest.ini`, `backend/requirements-dev.txt`, `.github/workflows/ci.yml`. The availability guard and the seed carry real logic; folding them into `conftest.py` would leave both untested.

**Steps.**
1. Add `pytest-playwright` to `requirements-dev.txt`. Chromium already installs via the Dockerfile path; CI installs it explicitly.
2. `e2e/conftest.py`: session-scoped uvicorn on a free port against the CI Postgres, seeded through existing service functions; a `page` fixture logged in per role. Reuse `tests/conftest.py`'s transaction pattern where it fits; a browser needs committed data, so seeding is per-session with explicit teardown.
3. `test_smoke.py`: login, then each page in `main.py`'s `SHELL_PARTS` — navigate, assert its primary list renders, assert no console errors. That last assertion is what makes CSP violations visible.
4. `test_work_orders.py`: two journeys end to end — open a card page by URL and see it render; change a status and see the badge and list update.
5. CI: `e2e` job with the Postgres service; add to `deploy` `needs`.

**Test.** E2E green in CI. Runtime under ~3 minutes; if it exceeds that, cut journeys rather than accept a slow gate.

**Success check.** Deliberately break CSP (add an inline `style=`), confirm the console-error assertion catches it, revert.

---

## P4 — Split `views/workOrders.js`

**Goal.** The original task, executed under the net. This is the one phase that
changes production code.

**Files.** `backend/static/views/workOrders.js` plus new siblings; `main.js` if
side-effect import order changes.

**Split** (seams confirmed by churn clustering — each is a group that gets edited together):

| New module | From | Roughly |
| --- | --- | --- |
| `workOrderIntegrations.js` | NetFacilities import/export/cloud auth | ~380 lines |
| `workOrderCardHtml.js` | HTML string builders — `renderBody`, `laborSectionHtml`, `detailsEditorHtml`, `technicianPickerHtml`, `comboHtml` | ~500 lines |
| `workOrderActions.js` | The 26-branch click delegator | ~390 lines |
| `workOrderRouting.js` | Solo-card URL routing, scroll stamp/restore, popstate | ~200 lines |
| `workOrders.js` | List load, filters, sort, card assembly, realtime | remainder |

**Steps.**
1. One module per commit, in the order above — least-coupled first. `workOrderIntegrations.js` is genuinely separable (it serves the Integrations page) and is the safest first move.
2. **Mechanical motion only.** Move code verbatim; change nothing but imports and exports. No renames, no signature changes, no cleanups. `git diff` should read as the same lines leaving one file and entering another.
3. Run the full suite after each move. Green before the next.
4. Preserve all eleven public exports — `soloNumberFromPath`, `focusWorkOrder`, `focusWorkOrderNumber`, `workOrderCardClass`, `comboHtml`, `loadWorkOrders`, `loadIntegrationsPage`, `mountWorkOrderList`, `openWorkOrdersByNumberSearch`, `openWorkOrdersFilteredByStatus`, `openWorkOrdersFilteredByDistribution` — from `workOrders.js` by re-export, so the nine importing modules never change. Consumers move in a later, separate pass if at all.
5. Watch for import cycles: `nav.js` already imports `workOrders.js`, and `workOrders.js` imports `workOrderRequests.js`.

**Test.** P2 and P3 suites unchanged and green after every commit. Not one test edited to accommodate a move — an edit needed here means the move was not mechanical.

**Success check.** No file over 900 lines; each new module's purpose statable in one sentence.

---

## P5 — High-churn views

**Goal.** Component coverage for the nine most-edited view modules.

**Files.** `views/nav.js`, `views/items.js`, `main.js`, `views/transactions.js`,
`views/history.js`, `views/userHub.js`, `views/scan.js`, `views/auth.js`,
`views/massStage.js`.

The P4 offspring get **no new coverage here**. P2's suite already exercises all
of them through the barrel and `actionCoverage.test.js` guards the module
boundary; re-covering them at the new file granularity would freeze the
internal seams the split exists to keep free.

**Steps.** One module per session-sized chunk, highest churn first, per
`docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md` — eight chunks,
with `nav.js` / `main.js` / `auth.js` covered together as one boot path ahead of
churn order, because a `bootApp()` fixture is the phase's first dependency.
For each: render, primary interactions, role gating, error paths, and any
cross-module callback wiring `main.js` injects. `scan.js` is stubbed at the
*browser* boundary (`navigator.mediaDevices`, `AudioContext`, `vibrate`), not
the module boundary — `scan/barcode-decoder.js` and `scan/frame-debouncer.js`
come forward from P7 and get real unit tests instead. `auth.js` covers the 401 →
login-gate path end to end against real `api.js`.

**Test.** Each module's exported surface exercised; delegated actions covered by the same meta-test pattern P2 established.

---

## P6 — Medium-churn views

**Files.** `views/hubTechnician.js`, `views/hubAdmin.js`, `views/hubClock.js`,
`views/hubSupervisor.js`, `views/hubGraphs.js`, `views/hubPriorities.js`,
`views/hubReport.js`, `views/hubTimesheets.js`, `views/users.js`,
`views/tools.js`, `views/toolCheckout.js`, `views/toolReturn.js`,
`views/toolCorrection.js`, `views/itemEditor.js`, `views/addBarcode.js`,
`views/notes.js`, `views/push.js`, `views/correction.js`,
`views/correctionPanel.js`, `views/subnav.js`. (`views/billingEditor.js` was
listed here; P5e drove it for real through History and it must not be
re-covered.)

**Steps.** Seven chunks per
`docs/superpowers/plans/2026-09-11-frontend-test-harness-p6.md`. Same pattern.
The hub modules share a dashboard shell: mount through
`tests/frontend/helpers/hub.js` (`openHub({role, crew, admin, timesheets, graphs})`),
built in P5f, rather than repeating the setup. Delegated-action views
(`tools.js`, `users.js`, and P7's `userRequests.js`) get their own
`auditActions()` file over `tests/frontend/helpers/actionAudit.js` (P5h) —
`massStageActionCoverage.test.js` is the template; `users.js` delegates on
class names, not `data-action`, so its audit passes custom patterns. `push.js`
mounts directly with `helpers/media.js::stubPush()` (P5b), which already stubs
`Notification`, `PushManager` and the service-worker registration.

---

## P7 — Remainder, then close the gate

**Files.** `views/userRequests.js`, `views/userRequestCards.js`,
`views/workOrderRequests.js`, `views/lowStock.js`, `views/lowStockCard.js`,
`views/adminReview.js`, `views/catalogueRequest.js`, `scan-test.js`,
`service-worker.js`.

**Steps.**
1. Cover the remainder. `scan/barcode-decoder.js` and `scan/frame-debouncer.js`
   moved to P5: they are pure, they belong in the unit layer, and the `scan.js`
   camera stub is only honest if the decode logic they hold is real.
2. `service-worker.js` needs a service-worker global stub; if that proves
   disproportionate, cover it in E2E instead and record the decision.
3. **Turn the coverage threshold blocking** at the level then achieved, minus a
   small margin. Same ratchet as `pip-audit`. Still advisory at P5 close
   (`thresholds: undefined` in `vitest.config.js`); the P5 status row above
   carries the number to ratchet from.
4. Fold the harness into `docs/current-state.md` and remove the "no frontend
   tests" line from `docs/open-work.md`.

**Success check.** CI fails on a coverage regression. A new frontend file
without a test is visible in the coverage report rather than invisible.
