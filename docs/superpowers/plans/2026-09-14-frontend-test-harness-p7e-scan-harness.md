# Frontend Test Harness — P7e (The scan harness and the service worker) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Steps use checkbox (`- [x]`) syntax for tracking.
>
> **Status: LANDED 2026-09-15. Suite 2076 tests / 77 files, 173 s (`npm run test:ci`), 96.30 % statements / 86.68 % branches / 98.54 % functions / 98.29 % lines. Findings filed under `N-P7-CHARACTERIZED`. Not pushed — P7f, the gate, is the last chunk.**

**Goal:** Characterization coverage for `scan-test.js` (667 lines: the boot, the five knobs, the reader hints, the six-state camera machine, the rAF decode loop with its crop, the two debounce modes, the diagnostics table, torch, copy-logs, the two lifecycle listeners) and `service-worker.js` (82 lines: install, activate, push, notificationclick). The two files at 0 % in today's report; the last of the nine.

**Architecture:** Tests only, on the P0 harness. `scan-test.js` gets the phase's one new document fixture, `helpers/scanTest.js`: it parses `backend/static/scan-test.html` the way `shell.js` parses the shell (scripts stripped, `documentElement` replaced) and imports the module through `importView`, so v8 sees the file and the import-time `document` listener is dropped at the next mount. Every seam is a browser global already stubbed in `helpers/media.js` (P5g): `getUserMedia`, `permissions`, `ZXingBrowser`, the canvas context, `requestAnimationFrame`, the video's intrinsic size — plus one new `stubClipboard`. Fake timers throughout (the module has a 500 ms focus-retry timer), and under Vitest 5 they also own `performance.now`, so `vi.advanceTimersByTime` is the harness's clock for latency, attempts-per-second and time-to-accept. The module exports nothing; every assertion is a DOM read, a log line or a spy call. `service-worker.js` mounts against a `self` stub (`vi.stubGlobal`) and is imported the same way (parent deviation 3).

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3
**Parent plan:** `docs/superpowers/plans/2026-09-14-frontend-test-harness-p7.md` (the P7e bullets are the requirement set; deviations 2 and 3 apply)
**Depends on:** P5g (`helpers/media.js`: `stubUserMedia`, `stubPermissions`, `stubZXing`, `stubCanvas`, `stubRaf`, `stubVideo`, `decodeResult`).

## Global constraints

- Tests only. No edit under `backend/static/` or `backend/app/`.
- Characterization, not correction. Findings → `docs/open-work.md` → `N-P7-CHARACTERIZED`.
- No `vi.mock` of any app module. Seams: browser globals only (no fetch, no socket in either file).
- Fake timers in every `scanTest` test; `afterEach` runs out pending timers then asserts `vi.getTimerCount()` is 0, as `scan.test.js` does.
- Commit messages end with the attribution lines the session provides.

## Already pinned — do not re-cover

- P5g `barcodeDecoder.test.js` / `frameDebouncer.test.js`: the production decoder and debouncer. The harness has its own copies of both ideas; this chunk pins the harness's, not production's.
- P5b `push.test.js`: the page side of push (`navigator.serviceWorker.register`, the subscription ladder). This chunk pins only the worker.

## Deviations from the parent's P7e text, decided here

| # | Deviation | Why |
| --- | --- | --- |
| D1 | `helpers/shell.js` gains `mountDocument(html)` — drop the captured `document` listeners, parse, replace `documentElement` — and `mountShell` becomes `mountDocument(assembleShell())`. `scanTest.js` calls `mountDocument` with the parsed harness page. | The listener drop (P7d's D5) is a private function; `scan-test.js` registers `visibilitychange` on `document` at import, and without the drop every earlier test's handler would stop the current test's camera. Exporting the drop alone would leave two copies of the parse-and-replace. |
| D2 | The fixture's tracks come from a local `scanTrack({settings, capabilities, getCapabilities})`, wrapping `media.js::fakeTrack` and adding `getSettings`. | `scan-test.js` calls `track.getSettings()` unconditionally on start; `fakeTrack` has no `getSettings` (production's decoder never calls it), so the shared factory cannot be handed to this module as-is. `settings` is returned by reference so a test can move `focusMode` after the retry. |
| D3 | No `performance.now` spy. Vitest 5's fake timers fake `performance` (probed 2026-09-14), so `vi.advanceTimersByTime(ms)` is the clock; a reader mock that advances the clock inside `decodeFromCanvas` yields a measurable latency. `stubRaf` is installed after `vi.useFakeTimers()` so its `define` wins over the fake-timer rAF, as `helpers/scanner.js` already does. | One clock, not two. |
| D4 | Clicks are `el.click()` plus a microtask flush (`settle()`), not `userEvent`. | The harness has no text entry that matters (the phone / conditions fields are read once, on copy); `userEvent` under fake timers costs more than it pins. |
| D5 | "Stopping" is pinned through the log ("camera state -> stopping" then "-> idle"), not the pill. | `stop()` moves through it synchronously; the pill never shows it. |
| D6 | The log's `scrollTop` is pinned by defining `scrollHeight` on the `<pre>` (jsdom reports 0) and reading `scrollTop` back after a log line. | jsdom stores the assigned `scrollTop` (probed) but has no layout, so the two are otherwise both zero and the assertion would be vacuous. |
| D7 | `stop()`'s `srcObject = null` warn branch is pinned by giving the video a throwing `srcObject` setter after streaming. | The branch exists for Safari; cheap to reach, nothing else covers it. |

---

### Task 1: the helpers

- [x] `helpers/media.js`: `stubClipboard({reject = null})` → `define(navigator, "clipboard", {writeText})`, `writeText` a `vi.fn` that throws `reject` when set; returns `{writeText}`. Restored by `restoreMediaStubs`.
- [x] `helpers/shell.js`: `mountDocument(html)` (D1); `mountShell` delegates.
- [x] `helpers/scanTest.js`: `SCAN_TEST_HTML` read once from `backend/static/scan-test.html`, scripts stripped; `scanTrack` (D2); `mountScanTest({zxing = true, permission = "prompt", media = {}, clipboard = {}, video = {}})` — `vi.useFakeTimers()`, `mountDocument`, `stubCanvas`, `stubRaf`, `stubUserMedia({tracks: [track], reject})`, `stubPermissions`, `stubClipboard`, `stubZXing({ZXingBrowser: {BarcodeFormat: …}})` when `zxing`, `importView("scan-test.js")`, `stubVideo(els.video, video)`, `settle()`. Returns `{els, raf, canvas, media, track, zxing, clipboard}` with `els` keyed as the module's own table plus `debounce(mode)` / `res(value)` radio getters. Also `settle()`, `logLines()` (timestamps stripped → `[level] msg`), `startStreaming(m)` (click Start, settle, assert streaming), `hit(m, text, format)` (mock the reader for the next frames), `restoreScanTest()` = `restoreMediaStubs()` + `vi.useRealTimers()`.

### Task 2: `views/scanTest.test.js`

- [x] Boot: no global → the `<p>` in `body` and the import rejects "ZXingBrowser global missing"; with it → the two boot lines (`harness loaded -- ZXingBrowser keys: BrowserMultiFormatReader,BarcodeFormat`, `userAgent: …`); `permissionsPrecheck` — `null` → the unsupported line, `denied` → "blocked" + the err line, `throws` → the warn line, `granted` → the query line only; every diag cell `—` except config, window `(empty)`, state `idle`.
- [x] Config and reader: `configSummary` from every knob (default `formats:5  crop:on  tryHarder:off  res:1080p  debounce:5-of-10`; each toggle and both radios); `buildReader` hints on Start (key 2 the five formats, key 3 absent / present), rebuilt on the formats / TRY_HARDER change while streaming and not while idle; crop change logs and repaints; debounce change logs and resets; resolution change logs the warn.
- [x] State machine: the pill text / class and the two buttons over idle, requesting (a hand-resolved `getUserMedia`), streaming, error, blocked; stopping through the log (D5).
- [x] Start: the lock (two clicks, one `getUserMedia`); the constraints object for 1080 and 720; `NotAllowedError` → blocked, another → error, both logged; torch capability four ways; the focus fallback (`focusMode: "manual"` granted, `["manual", "continuous"]` capable → the 500 ms retry → `applyConstraints({advanced: [{focusMode: "continuous"}]})`, the after-retry line reading the moved setting, and the throw branch); no `getCapabilities` → `{}` → "no"; `play()` rejecting → warn; aimbox unhidden, streaming, one frame queued, "streaming started".
- [x] Stop / reset / torch / copy / lifecycle: stop while idle → nothing logged; otherwise `cancelAnimationFrame` with the queued id, every track stopped (a throwing `stop` → warn), `srcObject` null (D7), the torch label reset, aimbox hidden, idle; `resetWindow` → accepted / tta `—`, "window reset", and `startTimestamp` kept while streaming (a later accept still reports a time) vs nulled when idle (pinned through the log only — see the finding); `toggleTorch` — hidden button while idle does nothing; `applyConstraints({advanced: [{torch: true}]})` → "Torch: on", again → off; a throw → the err line; `copyLogs` → `JSON.parse` the written text: every key, `phone` / `conditions` `(unset)` vs the typed values, `logTail` the ring; a rejecting `writeText` → the warn line then the dump; `visibilitychange` with `document.hidden` while streaming → stop, while idle → nothing; `beforeunload` → tracks stopped, a throw swallowed; the ring capped at 200 with `scrollTop` at `scrollHeight` (D6).
- [x] The finding: Stop is enabled during `requesting`, and `start()` never re-checks the state after `getUserMedia` resolves — a Stop click mid-request goes idle, then the resolved stream starts streaming anyway. Pin it.

### Task 3: `views/scanTestDecode.test.js`

- [x] Frame loop: no intrinsic size → re-queued, no draw; crop on → `{sx, sy, sw, sh}` for 1280×720 (`1024×341` at `128, 190`) and for an odd size that exercises `Math.round`; off → the full frame; the canvas resized on the first frame only (a setter spy); `drawImage(video, sx, sy, sw, sh, 0, 0, sw, sh)`; a miss → an attempt, no hit, success `0%  (1/1)`-style; a hit → latest, the log line.
- [x] `renderDiag`: resolution `w x h` (`?` for a missing side), facing `(not reported)`, focus `granted / capable` with `(not exposed)` and `unknown` on a throwing `getCapabilities`; region `1024 x 341  (38% of frame)`; attempts per second from two frames 100 ms apart; success `p%  (h/t)`; mean latency from a reader that advances the clock; the window `2× a  |  1× b`; each rolling list capped at 30 (31 misses then a hit → `3%  (1/30)`).
- [x] Hits and acceptance: `[supported]` for the five, `[UNSUPPORTED]` for `QR_CODE`, `UNKNOWN(99)`; the window capped at 10; the streak reset by a different text, kept across misses; window mode → `count=5/10` at the fifth, sticky through later hits; consecutive mode → `consecutive=3`; the accept log line and `N ms` time-to-accept; after `resetWindow` a second accept is possible.
- [x] The unreachable `"n/a"`: a hit needs `streaming`, which sets `startTimestamp`; `resetWindow` nulls it only when not streaming, and no hit can follow. Pin with a comment and file it.

### Task 4: `unit/serviceWorker.test.js`

- [x] `mountServiceWorker()` — `fakeSelf` with `addEventListener` capturing by type, `skipWaiting`, `clients: {claim, matchAll, openWindow}`, `registration: {showNotification}`; `vi.stubGlobal("self", fakeSelf)`; `importView("service-worker.js")`; `fire(type, event)`; `afterEach` → `vi.unstubAllGlobals()`.
- [x] Install → `skipWaiting`; activate → `waitUntil(clients.claim())`; push — no `data` → the fallback title / body; `{title, body}` → shown with `icon`, `badge`, `tag`; a missing field → its fallback; `json()` throwing → the fallback; `notificationclick` — `close()`, `matchAll({type: "window", includeUncontrolled: true})`, the first client with `focus` focused, one without skipped, none → `openWindow("/")`, no `openWindow` → `undefined`; every `waitUntil` promise awaited.

### Task 5: the run, the findings, the commit

- [x] Success check: `AIMBOX_WIDTH_FRAC` → `0.5`; the crop test names the rect. Revert.
- [x] Findings → `N-P7-CHARACTERIZED`: the unreachable `"n/a"`; Stop during `requesting`.
- [x] `npm test` green; timers 0; wall-clock in the parent's table; this file's boxes; committed. No push.
