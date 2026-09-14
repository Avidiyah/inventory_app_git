// The scan-harness document fixture.
//
// `scan-test.js` is not part of the SPA: its own page (`scan-test.html`) is
// served unauthenticated, the module captures its element ids at import, and
// it exports nothing. So this fixture builds THAT document the way `shell.js`
// builds the shell (scripts stripped -- the vendor UMD and the module tag must
// not run), installs every browser global the module reaches for, and imports
// through `importView` so v8 sees the file and the import-time `document`
// listener is dropped at the next mount (`mountDocument`, P7e).
//
// Order is load-bearing: `stubCanvas` before the import (the module calls
// `getContext` at import); `vi.useFakeTimers()` before `stubRaf` (Vitest 5's
// fake timers own rAF and `performance.now`, and `define` must land on top --
// the same order `helpers/scanner.js` uses); `stubVideo` after the import, on
// the element the module captured. The fake clock IS the harness's clock:
// `vi.advanceTimersByTime(ms)` moves `performance.now`, so latency, attempts
// per second and time-to-accept are all measurable and exact.
//
// Everything the module records is a DOM read, a log line or a spy call --
// there is no export to inspect.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { expect, vi } from "vitest";
import { importView, mountDocument } from "./shell.js";
import {
  decodeResult, fakeTrack, restoreMediaStubs, stubCanvas, stubClipboard, stubPermissions,
  stubRaf, stubUserMedia, stubVideo, stubZXing,
} from "./media.js";

const HELPERS_DIR = dirname(fileURLToPath(import.meta.url));
const HTML_PATH = join(HELPERS_DIR, "..", "..", "..", "backend", "static", "scan-test.html");

let html = null;
function scanTestHtml() {
  if (html === null) {
    html = readFileSync(HTML_PATH, "utf8").replace(/<script\b[\s\S]*?<\/script>/gi, "");
  }
  return html;
}

// ZXing's `BarcodeFormat` enum values for the five formats the module
// allow-lists. `stubZXing` alone carries no `BarcodeFormat`, and the module
// reads five members of it at import.
export const BARCODE_FORMAT = { UPC_A: 14, UPC_E: 15, EAN_13: 7, EAN_8: 6, CODE_128: 4 };
export const SUPPORTED_FORMAT_VALUES = [14, 15, 7, 6, 4];

export const DEFAULT_SETTINGS = Object.freeze({
  width: 1280, height: 720, facingMode: "environment", focusMode: "continuous",
});

// A track with `getSettings`, which the module calls unconditionally on start
// and `media.js::fakeTrack` lacks (production's decoder never calls it).
// `settings` is returned by reference so a test can move `focusMode` after the
// retry. `getCapabilities: null` removes the method (a browser without it); a
// function replaces it (one that throws, say).
export function scanTrack({ settings = { ...DEFAULT_SETTINGS }, capabilities = {}, getCapabilities } = {}) {
  const track = fakeTrack({ capabilities });
  track.getSettings = vi.fn(() => settings);
  if (getCapabilities === null) delete track.getCapabilities;
  else if (getCapabilities) track.getCapabilities = getCapabilities;
  return track;
}

// The module's own element table, by the ids scan-test.html carries.
const IDS = {
  video: "scan-test-video", canvas: "scan-test-canvas", aimbox: "scan-test-aimbox",
  startBtn: "scan-test-start-btn", stopBtn: "scan-test-stop-btn", resetBtn: "scan-test-reset-window-btn",
  torchBtn: "scan-test-torch-btn", copyBtn: "scan-test-copy-logs-btn",
  phone: "scan-test-phone", conditions: "scan-test-conditions", log: "scan-test-log",
  expFormats: "experiment-formats", expCrop: "experiment-crop", expTryHarder: "experiment-tryharder",
  state: "diag-state", config: "diag-config", resolution: "diag-resolution", facing: "diag-facing",
  torch: "diag-torch", focus: "diag-focus", region: "diag-region", attempts: "diag-attempts",
  success: "diag-success", latency: "diag-latency", latest: "diag-latest", window: "diag-window",
  accepted: "diag-accepted", tta: "diag-tta",
};

function elements() {
  const els = Object.fromEntries(Object.entries(IDS).map(([key, id]) => [key, document.getElementById(id)]));
  els.debounce = (mode) => document.querySelector(`input[name="experiment-debounce"][value="${mode}"]`);
  els.res = (value) => document.querySelector(`input[name="experiment-res"][value="${value}"]`);
  return els;
}

// `zxing: false` leaves the UMD global out, and the import REJECTS -- the
// caller asserts on the rejection; the stubs installed before it are still
// restored by `restoreScanTest`.
//
// `media`: `reject` (true → NotAllowedError, an Error → that error) and
// `tracks` (a full list) pass through to `stubUserMedia`; anything else
// (`settings`, `capabilities`, `getCapabilities`) shapes the one default track.
export async function mountScanTest({
  zxing = true, permission = "prompt", media = {}, clipboard = {}, video = {},
} = {}) {
  vi.useFakeTimers();
  mountDocument(scanTestHtml());
  const canvas = stubCanvas();
  const raf = stubRaf();
  const { reject = null, tracks = null, ...trackOpts } = media;
  const track = tracks ? tracks[0] : scanTrack(trackOpts);
  const mediaStub = stubUserMedia({ tracks: tracks ?? [track], reject });
  stubPermissions(permission);
  const clip = stubClipboard(clipboard);
  const zx = zxing ? stubZXing({ ZXingBrowser: { BarcodeFormat: BARCODE_FORMAT } }) : null;
  const els = elements();
  await importView("scan-test.js");
  stubVideo(els.video, video);
  await settle();
  return { els, raf, canvas, media: mediaStub, track, zxing: zx, clipboard: clip };
}

// Drain the microtask chain a click starts (`start()` awaits `getUserMedia`
// and `play()`; the boot awaits `permissions.query`). Timers are fake and
// untouched, so the 500 ms focus retry only fires when a test advances to it.
export async function settle(ticks = 25) {
  for (let i = 0; i < ticks; i += 1) await Promise.resolve();
}

// The log, one entry per line, timestamps stripped: `[level] message`.
export const logLines = (els) =>
  els.log.textContent.split("\n").map((line) => line.replace(/^\[\d\d:\d\d:\d\d\.\d{3}\] /, ""));

export async function click(el) {
  el.click();
  await settle();
}

export async function startStreaming(m) {
  await click(m.els.startBtn);
  expect(m.els.state.textContent).toBe("streaming");
}

// Make every following frame decode `text`, or miss again (`null`). The
// reader is the one `stubZXing` handed the module's `buildReader`.
export function decodeNext(m, text, format = BARCODE_FORMAT.CODE_128) {
  const impl = text === null
    ? () => { throw new Error("NotFoundException"); }
    : () => decodeResult(text, format);
  m.zxing.reader.decodeFromCanvas.mockImplementation(impl);
}

// `document.hidden` is a prototype getter jsdom reports as false under
// `pretendToBeVisual`; an own property on the instance shadows it and is
// deleted on restore.
export function setDocumentHidden(hidden) {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
}

export function restoreScanTest() {
  delete document.hidden;
  restoreMediaStubs();
  vi.useRealTimers();
}
