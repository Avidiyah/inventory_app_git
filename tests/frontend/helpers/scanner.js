// The scanner fixture.
//
// views/scan.js exports `mountScanner`, the factory both pages call; testing
// the factory against elements the TEST owns, with spied callbacks, pins the
// option contract directly and leaves the two page instances (itemsScanner,
// txnScanner) to their own chunks.
//
// Mount order: scan.js cannot be the entry point. Its import graph is cyclic
// (scan -> transactions -> nav -> tools -> scan) and `tools.js` calls
// `mountScanner` at import, before scan.js has reached its own
// `BarcodeDecoder` import -- a TDZ error. Production enters at nav.js first
// (main.js), so this fixture does the same and then imports scan.js against
// the one shell (the same shape as helpers/items.js).

import { expect, vi } from "vitest";
import { userEvent } from "@testing-library/user-event";
import { importView, mountView } from "./shell.js";
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
  await mountView("views/nav.js");
  const mod = await importView("views/scan.js");
  clearRequests();
  return { mod, env };
}

let seq = 0;
// A test-owned section with the same element set the pages carry. `options`
// spread AFTER the spies, so a test can pass `allowCreate: false`,
// `continuous: true`, `notFoundLabel: "tool"`, its own `lookupFn`, or
// `onAddBarcode: undefined` to test "option absent". `onCommit`/`canScan` are
// only passed in continuous mode because the module ignores them otherwise.
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
