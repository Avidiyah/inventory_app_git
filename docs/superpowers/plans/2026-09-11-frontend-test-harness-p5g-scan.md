# Frontend Test Harness — P5g (`views/scan.js` + the two pure scan units) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status: NOT STARTED. Do not begin until P5a–P5f are committed on `main` and the user gives an explicit go-ahead.**

**Goal:** Characterization coverage for `backend/static/scan/frame-debouncer.js` (49 lines), `backend/static/scan/barcode-decoder.js` (179 lines) and `backend/static/views/scan.js` (635 lines): the field-tested tuning the two units encode, and the `mountScanner` factory's upload, live, continuous, torch, haptics, and permission paths.

**Architecture:** Tests only. **Pure first**: the debouncer needs nothing; the decoder needs four browser-boundary stubs jsdom lacks — `canvas.getContext("2d")` (null without the `canvas` package), `requestAnimationFrame` (present but uncontrollable), `video.videoWidth/Height` (always 0), and `HTMLMediaElement.play()` (logs "not implemented"). Those four join P5a's `helpers/media.js` so `scan.js` can then be driven through a real decode: stub reader returns a result → real `BarcodeDecoder` fires `onDecode` → real `FrameDebouncer` accepts → real `resolveBarcode`. `scan.js` is mounted through `mountView("views/scan.js")` (it auto-mounts `txnScanner` at import, which needs the Transaction page markup); tests then call the exported `mountScanner()` against **test-owned elements** with spied callbacks — the factory contract, option by option, with no MSW for the lookup. Continuous mode's real commit path is exercised once through P5d's `inBatch()` so `canScan`/`onCommit` are the production wiring, not spies.

**Tech Stack:** Vitest, jsdom, @testing-library/dom, @testing-library/user-event, msw.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3
**Parent plan:** `docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md` (P5g bullets are the requirement set)
**Depends on:** P5a (`helpers/media.js`), P5c (`upload()` pattern, `answerDecode`), P5d (`helpers/transactions.js`, `helpers/requests.js`, `helpers/dialogs.js`).

## Global constraints

- Tests only. No edit under `backend/static/` or `backend/app/`.
- Characterization, not correction.
- No `vi.mock` of any app module. The camera is stubbed at `navigator.mediaDevices`, the decoder at `window.ZXingBrowser`, the frame loop at `requestAnimationFrame`, the canvas at `HTMLCanvasElement.prototype.getContext` — never at `scan/*.js`.
- `onUnhandledRequest: "error"` stays on; the only network in this chunk is `POST /barcodes/decode` on the upload path and P5d's commit endpoints.
- Fake timers for every `scan.js` test (`DWELL_MS`, `COOLDOWN_MS`, the 500 ms focus retry); `user-event` built with `advanceTimers`.
- No real camera, no real timers, no unhandled rejection: every `afterEach` restores stubs and asserts `vi.getTimerCount() === 0`.
- Commit messages end with the attribution lines the session provides.

## Entry gate — verify before Task 1

- [ ] P5a–P5f on `main`; `helpers/media.js` exports `stubUserMedia`, `stubPermissions`, `stubVibrate`, `stubAudioContext`, `stubZXing`, `stubMediaEnvironment`, `restoreMediaStubs`, `fakeTrack`, `fakeStream` (verified against P5a's working tree 2026-09-11).
- [ ] `ls node_modules/canvas` is empty — confirms the canvas stub is needed, not optional.
- [ ] `npm test` green to completion; record count and wall-clock.

## Field-tested tuning this chunk pins (from `docs/current-state.md` and the modules)

| Setting | Where | Value |
| --- | --- | --- |
| Consecutive-streak threshold | `FrameDebouncer` | 3 |
| Aim-box crop | `BarcodeDecoder._tick` | 80 % width, 3:1 aspect, centred |
| TRY_HARDER hint | `BarcodeDecoder.start` | `Map { 3 → true }` |
| Camera request | `scan.js startLive` | 720p ideal, `facingMode: environment`, `audio: false` |
| Post-commit dwell / same-code cooldown | `scan.js` | 1200 ms / 3000 ms |

---

### Task 1: `FrameDebouncer` unit tests

**Files:** Create `tests/frontend/unit/frameDebouncer.test.js`.

- [ ] **Step 1: Write the tests**

```js
// tests/frontend/unit/frameDebouncer.test.js
import { describe, expect, it } from "vitest";
import { FrameDebouncer } from "../../../backend/static/scan/frame-debouncer.js";

describe("FrameDebouncer", () => {
  it("accepts on the third consecutive identical decode by default", () => {
    const d = new FrameDebouncer();
    expect(d.pushAndCheck("A")).toBeNull();
    expect(d.pushAndCheck("A")).toBeNull();
    expect(d.pushAndCheck("A")).toBe("A");
  });

  it("a differing decode resets the streak to one", () => {
    const d = new FrameDebouncer();
    d.pushAndCheck("A"); d.pushAndCheck("A");
    expect(d.pushAndCheck("B")).toBeNull();
    expect(d.pushAndCheck("B")).toBeNull();
    expect(d.pushAndCheck("B")).toBe("B");
  });

  it("once accepted, every later push returns the accepted text regardless of input", () => {
    const d = new FrameDebouncer();
    d.pushAndCheck("A"); d.pushAndCheck("A"); d.pushAndCheck("A");
    expect(d.pushAndCheck("B")).toBe("A");
    expect(d.pushAndCheck("C")).toBe("A");
  });

  it("reset clears the streak and the accepted text", () => {
    const d = new FrameDebouncer();
    d.pushAndCheck("A"); d.pushAndCheck("A"); d.pushAndCheck("A");
    d.reset();
    expect(d.pushAndCheck("A")).toBeNull();
    expect(d.pushAndCheck("B")).toBeNull();
  });

  it.each([[1, 1], [2, 2], [5, 5]])("threshold %i accepts on push %i", (threshold, n) => {
    const d = new FrameDebouncer(threshold);
    for (let i = 1; i < n; i += 1) expect(d.pushAndCheck("X")).toBeNull();
    expect(d.pushAndCheck("X")).toBe("X");
  });

  it("misses never reach it, so an interleaved identical read is not needed to keep a streak", () => {
    // The contract: the caller only pushes successful decodes. Two pushes of
    // "A" separated by silence still count as consecutive.
    const d = new FrameDebouncer();
    d.pushAndCheck("A");
    d.pushAndCheck("A");
    expect(d.pushAndCheck("A")).toBe("A");
  });

  it("distinguishes empty string from null and treats it as a real text", () => {
    const d = new FrameDebouncer(2);
    expect(d.pushAndCheck("")).toBeNull();
    expect(d.pushAndCheck("")).toBe("");
  });
});
```

- [ ] **Step 2: Run** → `npx vitest run tests/frontend/unit/frameDebouncer.test.js` → PASS (no failing-first step: the unit exists; these pin it).
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/unit/frameDebouncer.test.js
git commit -m "test(p5g): FrameDebouncer consecutive-streak contract"
```

---

### Task 2: Decoder stubs in `helpers/media.js`, then `BarcodeDecoder` unit tests

**Files:** Modify `tests/frontend/helpers/media.js` (append); create `tests/frontend/unit/barcodeDecoder.test.js`.

**Interfaces (produced, used by Task 3+):**
- `stubCanvas()` → `{ ctx }` where `ctx.drawImage` is a spy; installs `HTMLCanvasElement.prototype.getContext` returning `ctx` and records the `willReadFrequently` option.
- `stubRaf()` → `{ flush(n = 1), pending() }` — replaces `requestAnimationFrame`/`cancelAnimationFrame` with a queue; `flush()` runs the queued callbacks once (a "frame").
- `stubVideo(videoEl, { width = 1280, height = 720 } = {})` — defines `videoWidth`/`videoHeight` on the element and replaces `play()` with a resolved spy; returns `{ play }`.
- `decodeResult(text, format = "CODE_128")` → `{ getText: () => text, getBarcodeFormat: () => format }`, the shape ZXing's result exposes.

- [ ] **Step 1: Append to `helpers/media.js`**

```js
// --- Decoder frame loop ------------------------------------------------------
//
// `BarcodeDecoder._tick` draws the aim-box crop into an offscreen canvas and
// hands it to ZXing once per animation frame. jsdom has no canvas backend
// (getContext returns null), never sets a video's intrinsic size, and its
// requestAnimationFrame cannot be stepped -- so the loop never reaches a
// decode. These three stubs make a frame a thing a test can advance.

export function stubCanvas() {
  const ctx = { drawImage: vi.fn() };
  const getContext = vi.fn(function getContext(kind, options) {
    getContext.lastOptions = options;
    return kind === "2d" ? ctx : null;
  });
  define(HTMLCanvasElement.prototype, "getContext", getContext);
  return { ctx, getContext };
}

export function stubRaf() {
  let queue = [];
  let nextId = 1;
  const raf = vi.fn((cb) => { const id = nextId++; queue.push({ id, cb }); return id; });
  const caf = vi.fn((id) => { queue = queue.filter((entry) => entry.id !== id); });
  define(window, "requestAnimationFrame", raf);
  define(window, "cancelAnimationFrame", caf);
  return {
    raf, caf,
    pending: () => queue.length,
    // Run everything queued at call time as one frame; callbacks that
    // re-queue land in the NEXT frame, not this one.
    flush(frames = 1) {
      for (let i = 0; i < frames; i += 1) {
        const batch = queue; queue = [];
        batch.forEach(({ cb }) => cb(performance.now()));
      }
    },
  };
}

export function stubVideo(videoEl, { width = 1280, height = 720 } = {}) {
  Object.defineProperty(videoEl, "videoWidth", { configurable: true, get: () => width });
  Object.defineProperty(videoEl, "videoHeight", { configurable: true, get: () => height });
  const play = vi.fn(async () => {});
  Object.defineProperty(videoEl, "play", { configurable: true, value: play });
  return { play };
}

export function decodeResult(text, format = "CODE_128") {
  return { getText: () => text, getBarcodeFormat: () => format };
}
```

`define()` already exists in the file and pushes onto the shared restorer list, so `restoreMediaStubs()` undoes all three. `stubVideo` targets an element the test owns, which is discarded with the DOM.

- [ ] **Step 2: Write the decoder tests**

```js
// tests/frontend/unit/barcodeDecoder.test.js
import { afterEach, describe, expect, it, vi } from "vitest";
import { BarcodeDecoder } from "../../../backend/static/scan/barcode-decoder.js";
import {
  decodeResult, fakeStream, fakeTrack, restoreMediaStubs, stubCanvas, stubPermissions, stubRaf,
  stubUserMedia, stubVideo, stubZXing,
} from "../helpers/media.js";

afterEach(() => restoreMediaStubs());

describe("supports()", () => {
  it.each([
    ["no mediaDevices", { media: false, zxing: true, permission: "prompt" }, false],
    ["no ZXing global", { media: true, zxing: false, permission: "prompt" }, false],
    ["permission denied", { media: true, zxing: true, permission: "denied" }, false],
    ["permission prompt", { media: true, zxing: true, permission: "prompt" }, true],
    ["permission granted", { media: true, zxing: true, permission: "granted" }, true],
    ["no Permissions API", { media: true, zxing: true, permission: null }, true],
    ["Permissions API throws", { media: true, zxing: true, permission: "throws" }, true],
  ])("%s → %s", async (_label, { media, zxing, permission }, expected) => {
    if (media) stubUserMedia();
    if (zxing) stubZXing();
    stubPermissions(permission);
    await expect(BarcodeDecoder.supports()).resolves.toBe(expected);
  });

  it("never calls getUserMedia", async () => {
    const { getUserMedia } = stubUserMedia(); stubZXing(); stubPermissions("granted");
    await BarcodeDecoder.supports();
    expect(getUserMedia).not.toHaveBeenCalled();
  });
});

describe("permissionGranted()", () => {
  it.each([
    ["granted", true], ["prompt", false], ["denied", false], [null, false], ["throws", false],
  ])("%s → %s", async (state, expected) => {
    stubPermissions(state);
    await expect(BarcodeDecoder.permissionGranted()).resolves.toBe(expected);
  });
});

describe("start / tick / stop", () => {
  function setup({ width = 1280, height = 720 } = {}) {
    const zx = stubZXing();
    const canvas = stubCanvas();
    const raf = stubRaf();
    const video = document.createElement("video");
    const { play } = stubVideo(video, { width, height });
    const stream = fakeStream([fakeTrack()]);
    const onDecode = vi.fn();
    return { zx, canvas, raf, video, play, stream, onDecode, decoder: new BarcodeDecoder() };
  }

  it("throws without the ZXing global", async () => {
    const video = document.createElement("video");
    await expect(new BarcodeDecoder().start(video, fakeStream([]), vi.fn())).rejects.toThrow("ZXingBrowser global missing");
  });

  it("builds the reader with TRY_HARDER, attaches the stream, plays, and queues one frame", async () => {
    const s = setup();
    await s.decoder.start(s.video, s.stream, s.onDecode);
    const hints = s.zx.ZXingBrowser.BrowserMultiFormatReader.mock.calls[0][0];
    expect(hints).toBeInstanceOf(Map);
    expect([...hints.entries()]).toEqual([[3, true]]);
    expect(s.video.srcObject).toBe(s.stream);
    expect(s.play).toHaveBeenCalledTimes(1);
    expect(s.canvas.getContext.lastOptions).toEqual({ willReadFrequently: true });
    expect(s.raf.pending()).toBe(1);
  });

  it("a rejected play() is non-fatal", async () => {
    const s = setup();
    s.play.mockRejectedValueOnce(new Error("autoplay"));
    await expect(s.decoder.start(s.video, s.stream, s.onDecode)).resolves.toBeUndefined();
    expect(s.raf.pending()).toBe(1);
  });

  it("waits for intrinsic dimensions before drawing", async () => {
    const s = setup({ width: 0, height: 0 });
    await s.decoder.start(s.video, s.stream, s.onDecode);
    s.raf.flush(3);
    expect(s.canvas.ctx.drawImage).not.toHaveBeenCalled();
    expect(s.raf.pending()).toBe(1);
  });

  it("crops the aim-box region: 80% width, 3:1, centred", async () => {
    const s = setup({ width: 1280, height: 720 });
    await s.decoder.start(s.video, s.stream, s.onDecode);
    s.raf.flush();
    // sw = 1024, sh = 341, sx = 128, sy = 190
    expect(s.canvas.ctx.drawImage).toHaveBeenCalledWith(s.video, 128, 190, 1024, 341, 0, 0, 1024, 341);
    expect(s.zx.reader.decodeFromCanvas).toHaveBeenCalledTimes(1);
    expect(s.onDecode).not.toHaveBeenCalled(); // NotFoundException swallowed
    expect(s.raf.pending()).toBe(1);           // loop continues
  });

  it("a successful decode fires onDecode(text, format) and keeps looping", async () => {
    const s = setup();
    s.zx.reader.decodeFromCanvas.mockReturnValueOnce(decodeResult("ABC", "QR_CODE"));
    await s.decoder.start(s.video, s.stream, s.onDecode);
    s.raf.flush();
    expect(s.onDecode).toHaveBeenCalledWith("ABC", "QR_CODE");
    expect(s.raf.pending()).toBe(1);
  });

  it("stop() inside onDecode halts the loop without re-queueing", async () => {
    const s = setup();
    s.zx.reader.decodeFromCanvas.mockReturnValue(decodeResult("ABC"));
    s.onDecode.mockImplementation(() => s.decoder.stop());
    await s.decoder.start(s.video, s.stream, s.onDecode);
    s.raf.flush();
    expect(s.onDecode).toHaveBeenCalledTimes(1);
    expect(s.raf.pending()).toBe(0);
  });

  it("stop() cancels the pending frame and clears state; the stream is untouched", async () => {
    const s = setup();
    await s.decoder.start(s.video, s.stream, s.onDecode);
    s.decoder.stop();
    expect(s.raf.caf).toHaveBeenCalledTimes(1);
    expect(s.raf.pending()).toBe(0);
    expect(s.video.srcObject).toBe(s.stream);   // caller owns the stream
    expect(s.stream.getTracks()[0].stop).not.toHaveBeenCalled();
    s.raf.flush();                               // nothing left to run
    expect(s.canvas.ctx.drawImage).not.toHaveBeenCalled();
  });

  it("start() while running stops the previous loop first (one frame pending, not two)", async () => {
    const s = setup();
    await s.decoder.start(s.video, s.stream, s.onDecode);
    await s.decoder.start(s.video, s.stream, s.onDecode);
    expect(s.raf.caf).toHaveBeenCalledTimes(1);
    expect(s.raf.pending()).toBe(1);
    expect(s.zx.ZXingBrowser.BrowserMultiFormatReader).toHaveBeenCalledTimes(2);
  });

  it("stop() from a never-started decoder is safe", () => {
    expect(() => new BarcodeDecoder().stop()).not.toThrow();
  });
});
```

- [ ] **Step 3: Run** → PASS. If the `willReadFrequently` assertion fails because jsdom's own `getContext` was invoked before the stub, check `define()` targeted `HTMLCanvasElement.prototype` (not the window).
- [ ] **Step 4: Commit**

```bash
git add tests/frontend/helpers/media.js tests/frontend/unit/barcodeDecoder.test.js
git commit -m "test(p5g): decoder frame-loop stubs and BarcodeDecoder contract"
```

---

### Task 3: The scanner fixture and `mountScanner` as a factory

**Files:** Create `tests/frontend/helpers/scanner.js`; create `tests/frontend/views/scan.test.js` (smoke).

**Interfaces:**
- `mountScanModule({ env = {} })` → `{ mod }`: installs `stubMediaEnvironment(env)` + `stubCanvas()` + `stubRaf()`, fake timers, then `mountView("views/scan.js")`. Returns the module (which has already auto-mounted `txnScanner`).
- `buildScanner(mod, { live = true, ...options })` → `{ widget, els, lookupFn, onItemFound, onNotFound, onCreateShortcut, onAddBarcode, onCommit, canScan }`: creates a detached-but-attached `<section>` with the same element set the pages carry (file input, message `<p>`, chooser `<div>`, and when `live` a video / scan / upload / torch / aimbox), spies for every callback, and calls `mod.mountScanner({...})`. `lookupFn` defaults to a spy that resolves `item()`.
- `liveStart(s)` → clicks Scan, awaits the camera, returns the `raf`/`reader` from the environment for frame driving.
- `frameDecode(text, times = 3)` → sets the reader to return `decodeResult(text)` and flushes `times` frames.
- `uploadTo(inputEl)` — same one-byte PNG upload as P5c.
- `restoreScan()` — `restoreMediaStubs()`, `stopRecording()`, real timers.

- [ ] **Step 1: Write the smoke test**

```js
// tests/frontend/views/scan.test.js
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { requestFor, requests, clearRequests } from "../helpers/requests.js";
import { answerConfirmQuantity, confirmOverlay } from "../helpers/dialogs.js";
import {
  buildScanner, frameDecode, liveStart, mountScanModule, restoreScan, uploadTo,
} from "../helpers/scanner.js";
import {
  decodeResult, stubAudioContext, stubCanvas, stubPermissions, stubRaf, stubUserMedia, stubVibrate, stubVideo, stubZXing,
} from "../helpers/media.js";
import { item as itemFactory, transaction as txnFactory } from "../helpers/factories.js";

afterEach(async () => {
  // The dwell (1200 ms) and focus-retry (500 ms) timers are legitimate and
  // self-clearing; run them out, then anything still armed is a leak.
  if (vi.isFakeTimers()) {
    await vi.runOnlyPendingTimersAsync();
    expect(vi.getTimerCount()).toBe(0);
  }
  restoreScan();
});
const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

describe("mountScanner is a factory", () => {
  it("two instances share no state: one running does not make the other running", async () => {
    const { mod } = await mountScanModule();
    const a = buildScanner(mod);
    const b = buildScanner(mod);
    await liveStart(a);
    expect(a.els.aimbox.hidden).toBe(false);
    expect(b.els.aimbox.hidden).toBe(true);
    expect(b.els.upload.disabled).toBe(false);
    b.widget.stopLive();                // no-op on the idle instance
    expect(a.els.aimbox.hidden).toBe(false);
    a.widget.stopLive();
    expect(a.els.aimbox.hidden).toBe(true);
  });

  it("an upload-only mount exposes no-op live methods", async () => {
    const { mod } = await mountScanModule();
    const s = buildScanner(mod, { live: false });
    expect(() => { s.widget.stopLive(); s.widget.startLive(); s.widget.refreshPermissionState(); s.widget.autoStartIfPermitted(); }).not.toThrow();
    expect(Object.keys(s.widget).sort()).toEqual(["autoStartIfPermitted", "refreshPermissionState", "reset", "startLive", "stopLive"]);
  });
});
```

- [ ] **Step 2: Run to verify it fails** — missing helper.
- [ ] **Step 3: Write `helpers/scanner.js`**

```js
// tests/frontend/helpers/scanner.js
//
// The scanner fixture. views/scan.js exports `mountScanner`, the factory
// both pages call; testing the factory against elements the TEST owns, with
// spied callbacks, pins the option contract directly and leaves the two
// page instances (itemsScanner, txnScanner) to their own chunks. The module
// still has to be mounted through the shell: it auto-mounts txnScanner at
// import against the Transaction page's ids.

import { expect, vi } from "vitest";
import { userEvent } from "@testing-library/user-event";
import { mountView } from "./shell.js";
import { setTestUser } from "./session.js";
import { startRecording, stopRecording, clearRequests } from "./requests.js";
import {
  decodeResult, restoreMediaStubs, stubCanvas, stubMediaEnvironment, stubRaf, stubVideo,
} from "./media.js";
import { item as itemFactory } from "./factories.js";

let env = null;

export async function mountScanModule({ role = "technician", env: envOpts = {} } = {}) {
  vi.useFakeTimers();
  env = { ...stubMediaEnvironment(envOpts), canvas: stubCanvas(), raf: stubRaf() };
  await setTestUser({ role });
  startRecording();
  const mod = await mountView("views/scan.js");
  clearRequests();
  return { mod, env };
}

let seq = 0;
export function buildScanner(mod, { live = true, ...options } = {}) {
  seq += 1;
  const root = document.createElement("section");
  root.innerHTML = `
    <input type="file" id="t${seq}-input" accept="image/*">
    ${live ? `<video id="t${seq}-video"></video><div id="t${seq}-aimbox" hidden></div>
    <button id="t${seq}-scan" type="button">Scan</button>
    <button id="t${seq}-upload" type="button">Upload</button>
    <button id="t${seq}-torch" type="button" hidden>Torch</button>` : ""}
    <div id="t${seq}-chooser" hidden></div>
    <p id="t${seq}-message"></p>`;
  document.body.appendChild(root);
  const q = (suffix) => root.querySelector(`#t${seq}-${suffix}`);
  const els = { input: q("input"), message: q("message"), chooser: q("chooser"),
    video: q("video"), scan: q("scan"), upload: q("upload"), torch: q("torch"), aimbox: q("aimbox") };
  if (live) stubVideo(els.video);
  const spies = {
    lookupFn: vi.fn(async () => itemFactory({ name: "Found" })),
    onItemFound: vi.fn(), onNotFound: vi.fn(), onCreateShortcut: vi.fn(), onAddBarcode: vi.fn(),
    onCommit: vi.fn(async () => ({ committed: true })), canScan: vi.fn(() => true),
  };
  const { onCommit, canScan, ...rest } = { ...spies, ...options };
  const widget = mod.mountScanner({
    inputEl: els.input, messageEl: els.message, chooserEl: els.chooser,
    ...rest,
    ...(options.continuous ? { onCommit, canScan } : {}),
    ...(live ? { liveEls: { videoEl: els.video, scanBtn: els.scan, uploadBtn: els.upload, torchBtn: els.torch, aimboxEl: els.aimbox } } : {}),
  });
  return { widget, els, root, ...spies, ...options };
}

export async function liveStart(s) {
  await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(s.els.scan);
  await vi.waitFor(() => expect(s.els.message.textContent).toBe("Aim at a barcode…"));
  return env;
}

// Make the next `times` frames decode `text` (a streak), then flush them.
export function frameDecode(text, times = 3, format = "CODE_128") {
  env.zxing.reader.decodeFromCanvas.mockImplementation(() => decodeResult(text, format));
  env.raf.flush(times);
}

export async function uploadTo(inputEl, name = "label.png") {
  const file = new File([new Uint8Array([0x89])], name, { type: "image/png" });
  await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).upload(inputEl, file);
}

export function restoreScan() {
  stopRecording();
  restoreMediaStubs();
  vi.useRealTimers();
  env = null;
}
```

`buildScanner` spreads `options` after the spies so a test can pass `allowCreate: false`, `continuous: true`, `notFoundLabel: "tool"`, or its own `lookupFn`. `onCommit`/`canScan` are only passed in continuous mode because the module ignores them otherwise and passing them would hide that.

- [ ] **Step 4: Run the smoke test** → PASS.
- [ ] **Step 5: Commit**

```bash
git add tests/frontend/helpers/scanner.js tests/frontend/views/scan.test.js
git commit -m "test(p5g): scanner fixture; mountScanner factory isolation"
```

---

### Task 4: Upload path and the 404 chooser

**Files:** Modify `tests/frontend/views/scan.test.js`.

- [ ] **Step 1: Write the tests**

```js
const answerDecode = (barcodes) => server.use(http.post("/barcodes/decode", () =>
  HttpResponse.json({ barcodes: barcodes.map((text) => ({ text, format: "CODE_128" })) })));

describe("upload path", () => {
  it("one barcode: decode → lookupFn → onItemFound with the matched copy", async () => {
    const { mod } = await mountScanModule();
    const found = itemFactory({ name: "Bulb" });
    const s = buildScanner(mod, { lookupFn: vi.fn(async () => found) });
    answerDecode(["B1"]);
    await uploadTo(s.els.input);
    await vi.waitFor(() => expect(s.onItemFound).toHaveBeenCalledWith(found));
    expect(s.lookupFn).toHaveBeenCalledWith("B1");
    expect(s.els.message.textContent).toBe("Matched Bulb (B1).");
    expect(s.els.message.className).toBe("success");
    expect(requestFor("/barcodes/decode", "POST")).not.toBeNull();
  });

  it("shows Decoding… while the request is in flight", async () => {
    const { mod } = await mountScanModule();
    const s = buildScanner(mod);
    server.use(http.post("/barcodes/decode", () => new Promise(() => {})));
    await uploadTo(s.els.input);
    expect(s.els.message.textContent).toBe("Decoding…");
  });

  it("zero barcodes: the hold-steady copy, no lookup", async () => {
    const { mod } = await mountScanModule();
    const s = buildScanner(mod);
    answerDecode([]);
    await uploadTo(s.els.input);
    await vi.waitFor(() => expect(s.els.message.className).toBe("error"));
    expect(s.els.message.textContent).toBe("Could not read that barcode. Move closer, hold steady, and try again.");
    expect(s.lookupFn).not.toHaveBeenCalled();
  });

  it("a failed decode request shows friendlyError with the image fallback", async () => {
    const { mod } = await mountScanModule();
    const s = buildScanner(mod);
    server.use(http.post("/barcodes/decode", () => HttpResponse.json({ detail: "" }, { status: 500 })));
    await uploadTo(s.els.input);
    await vi.waitFor(() => expect(s.els.message.className).toBe("error"));
    expect(s.els.message.textContent).not.toBe("");
  });

  it("many barcodes: chooser lists text · format; picking one resolves it and clears the chooser", async () => {
    const { mod } = await mountScanModule();
    const s = buildScanner(mod);
    answerDecode(["A1", "A2"]);
    await uploadTo(s.els.input);
    await vi.waitFor(() => expect(s.els.chooser.querySelectorAll(".scan-choice-btn")).toHaveLength(2));
    expect(s.els.message.textContent).toBe("Multiple barcodes found — choose one:");
    expect(s.els.chooser.querySelector(".scan-choice-btn").textContent).toBe("A1  ·  CODE_128");
    await user().click(s.els.chooser.querySelectorAll(".scan-choice-btn")[1]);
    await vi.waitFor(() => expect(s.lookupFn).toHaveBeenCalledWith("A2"));
    expect(s.els.chooser.hidden).toBe(true);
  });

  it("a lookup error other than 404 shows the lookup fallback and fires nothing", async () => {
    const { mod } = await mountScanModule();
    const s = buildScanner(mod, { lookupFn: vi.fn(async () => { throw { status: 500, detail: "x" }; }) });
    answerDecode(["B1"]);
    await uploadTo(s.els.input);
    await vi.waitFor(() => expect(s.els.message.className).toBe("error"));
    expect(s.onNotFound).not.toHaveBeenCalled();
    expect(s.onItemFound).not.toHaveBeenCalled();
  });
});

describe("404 handling", () => {
  const notFound = () => vi.fn(async () => { throw { status: 404, detail: "Item not found" }; });

  it.each([["technician", false], ["supervisor", false], ["techfm_oa", true], ["admin", true], ["owner", true]])(
    "%s: shortcuts offered = %s", async (role, offered) => {
      const { mod } = await mountScanModule({ role });
      const s = buildScanner(mod, { lookupFn: notFound() });
      answerDecode(["N0"]);
      await uploadTo(s.els.input);
      await vi.waitFor(() => expect(s.els.message.textContent).toBe("No item matches that barcode."));
      expect(s.onNotFound).toHaveBeenCalledWith("N0");
      expect(s.els.chooser.hidden).toBe(!offered);
      if (offered) {
        expect(s.els.chooser.querySelector(".scan-create-btn").textContent).toBe("Create a new item for N0");
        expect(s.els.chooser.querySelector(".scan-addbarcode-btn").textContent).toBe("Add N0 to an existing item");
      }
    });

  it("notFoundLabel changes the noun", async () => {
    const { mod } = await mountScanModule();
    const s = buildScanner(mod, { lookupFn: notFound(), notFoundLabel: "tool" });
    answerDecode(["N0"]);
    await uploadTo(s.els.input);
    await vi.waitFor(() => expect(s.els.message.textContent).toBe("No tool matches that barcode."));
  });

  it("allowCreate:false drops the Create button; no onAddBarcode drops the Add button; neither → chooser stays hidden", async () => {
    const { mod } = await mountScanModule({ role: "admin" });
    const a = buildScanner(mod, { lookupFn: notFound(), allowCreate: false });
    answerDecode(["N0"]);
    await uploadTo(a.els.input);
    await vi.waitFor(() => expect(a.onNotFound).toHaveBeenCalled());
    expect(a.els.chooser.querySelector(".scan-create-btn")).toBeNull();
    expect(a.els.chooser.querySelector(".scan-addbarcode-btn")).not.toBeNull();
    const b = buildScanner(mod, { lookupFn: notFound(), allowCreate: false, onAddBarcode: undefined });
    await uploadTo(b.els.input);
    await vi.waitFor(() => expect(b.onNotFound).toHaveBeenCalled());
    expect(b.els.chooser.hidden).toBe(true);
  });

  it("Create and Add-barcode shortcuts fire their callback with the code, then reset()", async () => {
    const { mod } = await mountScanModule({ role: "admin" });
    const s = buildScanner(mod, { lookupFn: notFound() });
    answerDecode(["N0"]);
    await uploadTo(s.els.input);
    await vi.waitFor(() => expect(s.els.chooser.hidden).toBe(false));
    await user().click(s.els.chooser.querySelector(".scan-create-btn"));
    expect(s.onCreateShortcut).toHaveBeenCalledWith("N0");
    expect(s.els.chooser.hidden).toBe(true);
    expect(s.els.message.textContent).toBe("");
    expect(s.els.input.value).toBe("");
    await uploadTo(s.els.input);
    await vi.waitFor(() => expect(s.els.chooser.hidden).toBe(false));
    await user().click(s.els.chooser.querySelector(".scan-addbarcode-btn"));
    expect(s.onAddBarcode).toHaveBeenCalledWith("N0");
  });
});
```

`onAddBarcode: undefined` in `buildScanner` options overrides the spy because the options spread last; that is the intended way to test "option absent".

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/scan.test.js
git commit -m "test(p5g): upload path, chooser, 404 shortcuts by role and option"
```

---

### Task 5: Live path — start, stop, torch, aimbox, permission state, autostart

**Files:** Modify `tests/frontend/views/scan.test.js`.

- [ ] **Step 1: Write the tests**

```js
describe("live path", () => {
  it("Scan → 720p environment request, aimbox on, upload disabled, then a streak of 3 stops the camera and looks up", async () => {
    const { mod, env } = await mountScanModule();
    const s = buildScanner(mod);
    await liveStart(s);
    expect(env.getUserMedia).toHaveBeenCalledWith({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 }, focusMode: { ideal: "continuous" } },
      audio: false,
    });
    expect(s.els.aimbox.hidden).toBe(false);
    expect(s.els.upload.disabled).toBe(true);
    expect(s.els.video.srcObject).toBe(env.stream);
    frameDecode("L1", 2);
    expect(s.lookupFn).not.toHaveBeenCalled();
    frameDecode("L1", 1);
    await vi.waitFor(() => expect(s.lookupFn).toHaveBeenCalledWith("L1"));
    expect(env.track.stop).toHaveBeenCalledTimes(1);       // camera released on accept
    expect(s.els.aimbox.hidden).toBe(true);
    expect(s.els.upload.disabled).toBe(false);
    expect(s.els.video.srcObject).toBeNull();
    await vi.waitFor(() => expect(s.onItemFound).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(500);               // the focus retry timer, if still armed, must not fire
  });

  it("a differing frame inside the streak resets it", async () => {
    const { mod } = await mountScanModule();
    const s = buildScanner(mod);
    await liveStart(s);
    frameDecode("L1", 2); frameDecode("L2", 1); frameDecode("L1", 2);
    expect(s.lookupFn).not.toHaveBeenCalled();
    frameDecode("L1", 1);
    await vi.waitFor(() => expect(s.lookupFn).toHaveBeenCalledWith("L1"));
  });

  it("Scan again while running stops the camera and clears the message", async () => {
    const { mod, env } = await mountScanModule();
    const s = buildScanner(mod);
    await liveStart(s);
    await user().click(s.els.scan);
    expect(env.track.stop).toHaveBeenCalledTimes(1);
    expect(s.els.message.textContent).toBe("");
    expect(env.raf.pending()).toBe(0);
  });

  it("Upload while live stops the camera first, then opens the picker", async () => {
    const { mod, env } = await mountScanModule();
    const s = buildScanner(mod);
    await liveStart(s);
    const click = vi.spyOn(s.els.input, "click").mockImplementation(() => {});
    await user().click(s.els.upload);
    expect(env.track.stop).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
  });

  it("the 500 ms focus retry applies continuous focusMode only while still live", async () => {
    const { mod, env } = await mountScanModule();
    const s = buildScanner(mod);
    await liveStart(s);
    await vi.advanceTimersByTimeAsync(500);
    expect(env.track.applyConstraints).toHaveBeenCalledWith({ advanced: [{ focusMode: "continuous" }] });
    s.widget.stopLive();
    const t = buildScanner(mod);
    await liveStart(t);
    t.widget.stopLive();
    env.track.applyConstraints.mockClear();
    await vi.advanceTimersByTimeAsync(500);
    expect(env.track.applyConstraints).not.toHaveBeenCalled();
  });

  it("unsupported browser: the not-available copy and no getUserMedia", async () => {
    const { mod, env } = await mountScanModule({ env: { zxing: false } });
    const s = buildScanner(mod);
    await user().click(s.els.scan);
    await vi.waitFor(() => expect(s.els.message.textContent).toBe("Live camera is not available in this browser."));
    expect(env.getUserMedia).not.toHaveBeenCalled();
  });

  it.each([
    ["NotAllowedError", "Camera permission denied. Use Upload instead, or allow camera access in your browser settings."],
    ["SecurityError", "Camera permission denied. Use Upload instead, or allow camera access in your browser settings."],
    ["NotReadableError", "Could not open the camera. Try Upload instead."],
  ])("getUserMedia %s → %s", async (name, copy) => {
    const { mod } = await mountScanModule();
    const err = Object.assign(new Error(name), { name });
    stubUserMedia({ reject: err });   // replaces the environment's default camera
    const s = buildScanner(mod);
    await user().click(s.els.scan);
    await vi.waitFor(() => expect(s.els.message.textContent).toBe(copy));
    expect(s.els.aimbox.hidden).toBe(true);
  });

  it("a decoder start failure stops the camera and reports the message", async () => {
    const { mod, env } = await mountScanModule();
    env.zxing.ZXingBrowser.BrowserMultiFormatReader.mockImplementation(() => { throw new Error("boom"); });
    const s = buildScanner(mod);
    await user().click(s.els.scan);
    await vi.waitFor(() => expect(s.els.message.textContent).toBe("Could not start the decoder: boom."));
    expect(env.track.stop).toHaveBeenCalledTimes(1);
  });
});

describe("torch", () => {
  it("hidden without the capability; shown with it; toggles via applyConstraints; a failing toggle disables the button", async () => {
    const { mod } = await mountScanModule();
    const a = buildScanner(mod);
    await liveStart(a);
    expect(a.els.torch.hidden).toBe(true);
    a.widget.stopLive();
    const cam = stubUserMedia({ torch: true });
    const b = buildScanner(mod);
    await liveStart(b);
    expect(b.els.torch.hidden).toBe(false);
    await user().click(b.els.torch);
    expect(cam.track.applyConstraints).toHaveBeenCalledWith({ advanced: [{ torch: true }] });
    await user().click(b.els.torch);
    expect(cam.track.applyConstraints).toHaveBeenLastCalledWith({ advanced: [{ torch: false }] });
    cam.track.applyConstraints.mockRejectedValueOnce(new Error("no torch"));
    await user().click(b.els.torch);
    await vi.waitFor(() => expect(b.els.torch.disabled).toBe(true));
    b.widget.stopLive();
    expect(b.els.torch.hidden).toBe(true);
    expect(b.els.torch.disabled).toBe(false);
  });
});

describe("refreshPermissionState / autoStartIfPermitted", () => {
  it("denied: Scan button hidden and the blocked copy; supported: button shown, message untouched", async () => {
    const { mod } = await mountScanModule({ env: { permission: "denied" } });
    const s = buildScanner(mod);
    await s.widget.refreshPermissionState();
    expect(s.els.scan.hidden).toBe(true);
    expect(s.els.message.textContent).toBe("Camera blocked. Re-enable it via the lock icon in your browser, or use Upload.");
    stubPermissions("prompt");
    s.els.message.textContent = "untouched";
    await s.widget.refreshPermissionState();
    expect(s.els.scan.hidden).toBe(false);
    expect(s.els.message.textContent).toBe("untouched");
  });

  it.each([["granted", 1], ["prompt", 0], ["denied", 0], [null, 0], ["throws", 0]])(
    "autoStartIfPermitted with permission %s calls getUserMedia %i times and never prompts", async (state, calls) => {
      const { mod, env } = await mountScanModule({ env: { permission: state } });
      const s = buildScanner(mod);
      await s.widget.autoStartIfPermitted();
      expect(env.getUserMedia).toHaveBeenCalledTimes(calls);
      if (calls) { await vi.waitFor(() => expect(s.els.aimbox.hidden).toBe(false)); s.widget.stopLive(); }
    });

  it("autoStart is a no-op while already running", async () => {
    const { mod, env } = await mountScanModule({ env: { permission: "granted" } });
    const s = buildScanner(mod);
    await liveStart(s);
    await s.widget.autoStartIfPermitted();
    expect(env.getUserMedia).toHaveBeenCalledTimes(1);
    s.widget.stopLive();
  });
});

describe("reset()", () => {
  it("clears input, chooser, message and stops live", async () => {
    const { mod, env } = await mountScanModule();
    const s = buildScanner(mod);
    await liveStart(s);
    s.els.chooser.innerHTML = "<button class='scan-choice-btn'>x</button>"; s.els.chooser.hidden = false;
    s.widget.reset();
    expect(s.els.chooser.innerHTML).toBe("");
    expect(s.els.chooser.hidden).toBe(true);
    expect(s.els.message.textContent).toBe("");
    expect(env.track.stop).toHaveBeenCalledTimes(1);
  });
});
```

`stubPermissions("prompt")` mid-test after `denied`: `define()` on `navigator.permissions` replaces the previous stub and pushes a second restorer — both are undone by `restoreMediaStubs()`.

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/scan.test.js
git commit -m "test(p5g): live camera path, torch, permission state, autostart, reset"
```

---

### Task 6: Continuous mode — dwell, cooldown, canScan, haptics, and the real commit path

**Files:** Modify `tests/frontend/views/scan.test.js`.

- [ ] **Step 1: Write the tests**

```js
describe("continuous mode (spied)", () => {
  async function running(overrides = {}) {
    const { mod, env } = await mountScanModule();
    const s = buildScanner(mod, { continuous: true, ...overrides });
    await liveStart(s);
    return { s, env };
  }

  it("a streak commits via onCommit and keeps the camera live", async () => {
    const { s, env } = await running();
    frameDecode("C1", 3);
    await vi.waitFor(() => expect(s.onCommit).toHaveBeenCalledTimes(1));
    expect(s.lookupFn).toHaveBeenCalledWith("C1");
    expect(env.track.stop).not.toHaveBeenCalled();
    expect(env.raf.pending()).toBe(1);
    expect(env.vibrate).toHaveBeenCalledWith(60);
  });

  it("DWELL: every decode inside 1200 ms after a commit is ignored, even a different code", async () => {
    const { s } = await running();
    frameDecode("C1", 3);
    await vi.waitFor(() => expect(s.onCommit).toHaveBeenCalledTimes(1));
    frameDecode("C2", 3);
    await vi.advanceTimersByTimeAsync(1199);
    expect(s.onCommit).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    frameDecode("C2", 3);
    await vi.waitFor(() => expect(s.onCommit).toHaveBeenCalledTimes(2));
  });

  it("COOLDOWN: the same code is suppressed until 3000 ms after its commit, then commits again", async () => {
    const { s } = await running();
    frameDecode("C1", 3);
    await vi.waitFor(() => expect(s.onCommit).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(1200);          // dwell over; cooldown has 1800 ms left
    frameDecode("C1", 3);
    await vi.advanceTimersByTimeAsync(10);
    expect(s.onCommit).toHaveBeenCalledTimes(1);      // suppressed, and no dwell was started
    await vi.advanceTimersByTimeAsync(1790);          // t = 3000 since the commit
    frameDecode("C1", 3);
    await vi.waitFor(() => expect(s.onCommit).toHaveBeenCalledTimes(2));
  });

  it("COOLDOWN applies only to the just-committed code: a different code commits at once", async () => {
    const { s } = await running();
    frameDecode("C1", 3);
    await vi.waitFor(() => expect(s.onCommit).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(1200);
    frameDecode("C2", 3);
    await vi.waitFor(() => expect(s.onCommit).toHaveBeenCalledTimes(2));
    expect(s.onCommit.mock.calls[1][0].name).toBe("Found"); // lookupFn's default item
    expect(s.lookupFn).toHaveBeenLastCalledWith("C2");
  });

  it("a declined commit also starts the cooldown, and buzzes nothing", async () => {
    const { s, env } = await running({ onCommit: vi.fn(async () => ({ committed: false, declined: true })) });
    frameDecode("C1", 3);
    await vi.waitFor(() => expect(s.onCommit).toHaveBeenCalledTimes(1));
    expect(env.vibrate).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1200);
    frameDecode("C1", 3);
    await vi.advanceTimersByTimeAsync(10);
    expect(s.onCommit).toHaveBeenCalledTimes(1);
  });

  it("a failed commit ({committed:false}) buzzes the error pattern and does NOT start a cooldown", async () => {
    const { s, env } = await running({ onCommit: vi.fn(async () => ({ committed: false })) });
    frameDecode("C1", 3);
    await vi.waitFor(() => expect(s.onCommit).toHaveBeenCalledTimes(1));
    expect(env.vibrate).toHaveBeenCalledWith([40, 40, 40]);
    await vi.advanceTimersByTimeAsync(1200);
    frameDecode("C1", 3);
    await vi.waitFor(() => expect(s.onCommit).toHaveBeenCalledTimes(2));
  });

  it("canScan false: the quantity prompt, error buzz, no lookup", async () => {
    const { s, env } = await running({ canScan: vi.fn(() => false) });
    frameDecode("C1", 3);
    await vi.waitFor(() => expect(s.els.message.textContent).toBe("Enter a quantity first, then scan."));
    expect(s.lookupFn).not.toHaveBeenCalled();
    expect(env.vibrate).toHaveBeenCalledWith([40, 40, 40]);
  });

  it("404 in continuous mode: no shortcut chooser, the not-found copy, error buzz", async () => {
    const { mod } = await mountScanModule({ role: "admin" });
    const s = buildScanner(mod, { continuous: true, lookupFn: vi.fn(async () => { throw { status: 404 }; }) });
    await liveStart(s);
    frameDecode("N0", 3);
    await vi.waitFor(() => expect(s.els.message.textContent).toBe("No item matches that barcode."));
    expect(s.els.chooser.hidden).toBe(true);
    expect(s.onCommit).not.toHaveBeenCalled();
  });

  it("the upload path also commits in continuous mode", async () => {
    const { mod } = await mountScanModule();
    const s = buildScanner(mod, { continuous: true });
    server.use(http.post("/barcodes/decode", () => HttpResponse.json({ barcodes: [{ text: "U1", format: "CODE_128" }] })));
    await uploadTo(s.els.input);
    await vi.waitFor(() => expect(s.onCommit).toHaveBeenCalledTimes(1));
  });
});

describe("haptics and audio degrade silently", () => {
  it("no vibrate, no AudioContext: a commit still resolves", async () => {
    const { mod } = await mountScanModule();
    stubVibrate({ supported: false }); stubAudioContext({ supported: false });
    const s = buildScanner(mod, { continuous: true });
    await liveStart(s);
    frameDecode("C1", 3);
    await vi.waitFor(() => expect(s.onCommit).toHaveBeenCalledTimes(1));
    expect(s.els.message.className).not.toBe("error");
  });

  it("Scan tap primes the audio context and resumes it; a commit then plays one square blip", async () => {
    const { mod, env } = await mountScanModule();
    const s = buildScanner(mod, { continuous: true });
    await liveStart(s);
    expect(env.audio.created).toHaveLength(1);
    expect(env.audio.created[0].resume).toHaveBeenCalled();
    frameDecode("C1", 3);
    await vi.waitFor(() => expect(s.onCommit).toHaveBeenCalledTimes(1));
    expect(env.audio.created[0].createOscillator).toHaveBeenCalledTimes(1);
    const osc = env.audio.created[0].createOscillator.mock.results[0].value;
    expect(osc.frequency.value).toBe(880);
  });

  it("a failure plays two low blips", async () => {
    const { mod, env } = await mountScanModule();
    const s = buildScanner(mod, { continuous: true, canScan: vi.fn(() => false) });
    await liveStart(s);
    frameDecode("C1", 3);
    await vi.waitFor(() => expect(env.audio.created[0].createOscillator).toHaveBeenCalledTimes(2));
    expect(env.audio.created[0].createOscillator.mock.results.map((r) => r.value.frequency.value)).toEqual([300, 300]);
  });

  it("a throwing vibrate is swallowed", async () => {
    const { mod, env } = await mountScanModule();
    env.vibrate.mockImplementation(() => { throw new Error("not focused"); });
    const s = buildScanner(mod, { continuous: true });
    await liveStart(s);
    frameDecode("C1", 3);
    await vi.waitFor(() => expect(s.onCommit).toHaveBeenCalledTimes(1));
  });
});

describe("txnScanner through the real batch (P5d fixture)", () => {
  it("a live streak on the Transaction page commits through commitScannedItem with the confirm stepper", async () => {
    // The module instance under test is the one nav.js -> scan.js mounted
    // when transactions.js was imported; import() inside the test returns it.
    const { inBatch, el: txEl, answerTransaction, restoreTransactions } = await import("../helpers/transactions.js");
    vi.useFakeTimers();
    const zx = stubZXing(); stubCanvas(); const raf = stubRaf();
    const bulb = itemFactory({ name: "Bulb", barcode: "B1", quantity: "10" });
    const { mod } = await inBatch({ role: "technician", items: [bulb],
      handlers: [http.get("/items/B1", () => HttpResponse.json(bulb))] });
    const scan = await import("../../backend/static/views/scan.js");
    stubVideo(document.getElementById("txn-scan-video"));
    answerTransaction(txnFactory({ item_quantity: "9" }));
    await user().click(document.getElementById("txn-scan-scan-btn"));
    await vi.waitFor(() => expect(document.getElementById("txn-scan-message").textContent).toBe("Aim at a barcode…"));
    zx.reader.decodeFromCanvas.mockImplementation(() => decodeResult("B1"));
    raf.flush(3);
    await answerConfirmQuantity();
    await vi.waitFor(() => expect(requestFor("/transactions/", "POST")).not.toBeNull());
    expect(requestFor("/transactions/", "POST").body).toMatchObject({ item_id: bulb.id, quantity: 1 });
    expect(txEl.log().querySelector(".scango-log-ok")).not.toBeNull();
    expect(document.getElementById("txn-scan-aimbox").hidden).toBe(false); // still live
    scan.resetScan();
    expect(document.getElementById("txn-scan-aimbox").hidden).toBe(true);
    expect(mod.scanGoArmed()).toBe(true);
    restoreTransactions();
  });

  it("autoStartTxnScan starts the camera only with permission granted", async () => {
    const { inBatch, restoreTransactions } = await import("../helpers/transactions.js");
    vi.useFakeTimers();
    stubZXing(); stubCanvas(); stubRaf();
    await inBatch({ role: "technician" });
    stubVideo(document.getElementById("txn-scan-video"));
    const scan = await import("../../backend/static/views/scan.js");
    stubPermissions("prompt");
    scan.autoStartTxnScan();
    await vi.advanceTimersByTimeAsync(10);
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    stubPermissions("granted");
    scan.autoStartTxnScan();
    await vi.waitFor(() => expect(document.getElementById("txn-scan-aimbox").hidden).toBe(false));
    scan.resetScan();
    restoreTransactions();
  });
});
```

The two P5d-fixture tests call `restoreTransactions()` themselves and skip `mountScanModule`; the file's `afterEach` `restoreScan()` is harmless on top, and its timer check is skipped because `restoreTransactions()` already switched to real timers. `helpers/transactions.js` is imported inside the test rather than at the top because importing it registers nothing at module scope — either works; inline keeps the dependency visible next to the two tests that use it. `inBatch` installs `stubUserMedia`/`stubPermissions("prompt")` already (P5d fixture), which is why only the decoder stubs are added here.

- [ ] **Step 2: Run the file, then `npm test`**; record count and wall-clock.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/scan.test.js
git commit -m "test(p5g): continuous mode dwell/cooldown, haptics, real batch commit"
```

---

### Task 7: Findings, docs, close-out

**Files:** Modify `docs/open-work.md`, `docs/current-state.md`, `docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md`, `docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md`.

- [ ] **Step 1: Findings.** Append to `### N-P5-CHARACTERIZED` only rows the tests confirmed. Candidates:

| Defect | Pinned by |
| --- | --- |
| A failed continuous commit (`{committed:false}` without `declined`) starts no cooldown, so a label still in frame re-attempts every 1200 ms until it succeeds or the operator moves — by design for transient errors, but the same holds for a permanent 404. | `scan.test.js` → "a failed commit … does NOT start a cooldown" |
| `startLive` arms a 500 ms `setTimeout` for the focus retry that is not cleared by `stopLive`; it checks `liveRunning` when it fires, so it is safe, but it is the one timer a test must let expire. | → "the 500 ms focus retry" |
| `FrameDebouncer` treats `""` as a real barcode; ZXing never returns it, so unreachable. | `frameDebouncer.test.js` → "distinguishes empty string" |
| `toggleTorch` disables the button on a failed `applyConstraints` but never re-hides it; `stopLive` re-enables it — so a lying capability is re-offered on the next start. | → "torch" |

- [ ] **Step 2: `docs/current-state.md`.** Scan / camera task-area row gains the three test files; update the Vitest count/time bullet; the "field-tested settings" paragraph gains one line: *pinned by `unit/barcodeDecoder.test.js` and `unit/frameDebouncer.test.js`.*
- [ ] **Step 3: Parent plan + roadmap.** Tick P5g bullets; roadmap status `P5a–P5g landed`; roadmap P7 file list drops the two `scan/` units (they were pulled forward — the P5 plan already says so; make the P7 list match).
- [ ] **Step 4: Verify and commit** — `npm test` green.

```bash
git add docs/open-work.md docs/current-state.md docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md
git commit -m "docs: record P5g scan coverage and the decoder frame-loop stubs"
```

---

## Done when

- [ ] `npm test` green at every commit; count and wall-clock in the Task 6 and Task 7 commit bodies.
- [ ] Every `mountScanner` option has a test that changes behaviour by flipping it: `allowCreate`, `onCreateShortcut`, `onAddBarcode`, `onNotFound`, `continuous`, `onCommit`, `canScan`, `lookupFn`, `notFoundLabel`, `liveEls` present/absent.
- [ ] The five tuning values in the table above are each asserted by number.
- [ ] `vi.getTimerCount()` is 0 after every test; no real camera, no real timers, no unhandled rejection in the run output.
- [ ] No file under `backend/` touched.

## Deliberately not in P5g

- `itemsScanner` / `itemScanWidget` option wiring (P5c) and `toolsScanner` / `toolScanWidget` (P6) — the factory contract here is what they compose.
- `nav.js`'s page-swap `reset()` / `refreshPermissionState()` / `visibilitychange` `stopLive()` calls (P5a Task 2).
- The `scan-test.html` tuning harness and the vendor ZXing bundle.
- Fixing anything above.
