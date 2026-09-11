// Characterization coverage for views/scan.js: `mountScanner` as a factory,
// option by option -- the upload path and the 404 chooser, the live camera
// path on a stubbed getUserMedia driven through the REAL BarcodeDecoder and
// FrameDebouncer, continuous-mode dwell / cooldown / haptics, and the
// Transaction-page instance through P5d's batch fixture.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { requestFor } from "../helpers/requests.js";
import { answerConfirmQuantity } from "../helpers/dialogs.js";
import {
  buildScanner, frameDecode, liveStart, mountScanModule, restoreScan, uploadTo,
} from "../helpers/scanner.js";
import {
  decodeResult, stubAudioContext, stubCanvas, stubPermissions, stubRaf, stubUserMedia, stubVibrate, stubVideo, stubZXing,
} from "../helpers/media.js";
import { item as itemFactory, transaction as txnFactory } from "../helpers/factories.js";
// Static, not `await import()` inside the test: the per-test module reset
// would hand a dynamic import a fresh helpers/handlers.js -- a second MSW
// server that is never listening -- so the batch fixture's handlers would
// register on the wrong instance.
import { answerTransaction, el as txEl, inBatch, restoreTransactions } from "../helpers/transactions.js";

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
    expect(env.track.applyConstraints).not.toHaveBeenCalled();
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

  it("Upload is disabled while live, so its stop-the-camera-first branch is unreachable by click", async () => {
    // The module comment promises "clicking Upload tears the camera down
    // first", but startLive disables the Upload button, so a user can never
    // click it while live; the `if (liveRunning) stopLive()` guard is dead
    // from the UI. Characterization -- see open-work.md N-P5-CHARACTERIZED.
    const { mod, env } = await mountScanModule();
    const s = buildScanner(mod);
    await liveStart(s);
    const click = vi.spyOn(s.els.input, "click").mockImplementation(() => {});
    expect(s.els.upload.disabled).toBe(true);
    await user().click(s.els.upload);
    expect(env.track.stop).not.toHaveBeenCalled();
    expect(click).not.toHaveBeenCalled();
    s.widget.stopLive();
    expect(s.els.upload.disabled).toBe(false);
    await user().click(s.els.upload);
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
    env.zxing.ZXingBrowser.BrowserMultiFormatReader.mockImplementation(function () { throw new Error("boom"); });
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
    // Disabled but never re-hidden while live: stopLive is what resets it.
    expect(b.els.torch.hidden).toBe(false);
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
    await vi.waitFor(() => expect(env.vibrate).toHaveBeenCalledWith(60));
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
    await vi.advanceTimersByTimeAsync(1200);
    expect(env.vibrate).not.toHaveBeenCalled();
    frameDecode("C1", 3);
    await vi.advanceTimersByTimeAsync(10);
    expect(s.onCommit).toHaveBeenCalledTimes(1);
  });

  it("a failed commit ({committed:false}) buzzes the error pattern and does NOT start a cooldown", async () => {
    const { s, env } = await running({ onCommit: vi.fn(async () => ({ committed: false })) });
    frameDecode("C1", 3);
    await vi.waitFor(() => expect(s.onCommit).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(env.vibrate).toHaveBeenCalledWith([40, 40, 40]));
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
    const { mod, env } = await mountScanModule({ role: "admin" });
    const s = buildScanner(mod, { continuous: true, lookupFn: vi.fn(async () => { throw { status: 404 }; }) });
    await liveStart(s);
    frameDecode("N0", 3);
    await vi.waitFor(() => expect(s.els.message.textContent).toBe("No item matches that barcode."));
    expect(s.els.chooser.hidden).toBe(true);
    expect(s.onCommit).not.toHaveBeenCalled();
    expect(env.vibrate).toHaveBeenCalledWith([40, 40, 40]);
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
    await vi.waitFor(() => expect(env.audio.created[0].createOscillator).toHaveBeenCalledTimes(1));
    const osc = env.audio.created[0].createOscillator.mock.results[0].value;
    expect(osc.frequency.value).toBe(880);
    expect(osc.type).toBe("square");
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
    // Real timers until the batch is open: the P5d fixture drives user-event
    // without `advanceTimers`, which never resolves under fake timers.
    const zx = stubZXing(); stubCanvas(); const raf = stubRaf();
    const bulb = itemFactory({ name: "Bulb", barcode: "B1", quantity: "10" });
    const { mod } = await inBatch({ role: "technician", items: [bulb],
      handlers: [http.get("/items/B1", () => HttpResponse.json(bulb))] });
    vi.useFakeTimers();
    const scan = await import("../../../backend/static/views/scan.js");
    stubVideo(document.getElementById("txn-scan-video"));
    answerTransaction(txnFactory({ item_quantity: "9" }));
    await user().click(document.getElementById("txn-scan-scan-btn"));
    await vi.waitFor(() => expect(document.getElementById("txn-scan-message").textContent).toBe("Aim at a barcode…"));
    zx.reader.decodeFromCanvas.mockImplementation(() => decodeResult("B1"));
    raf.flush(3);
    await answerConfirmQuantity();
    await vi.waitFor(() => expect(requestFor("/transactions/", "POST")).not.toBeNull());
    expect(requestFor("/transactions/", "POST").body).toMatchObject({ item_id: bulb.id, quantity: 1 });
    await vi.waitFor(() => expect(txEl.log().querySelector(".scango-log-ok")).not.toBeNull());
    expect(document.getElementById("txn-scan-aimbox").hidden).toBe(false); // still live
    scan.resetScan();
    expect(document.getElementById("txn-scan-aimbox").hidden).toBe(true);
    expect(mod.scanGoArmed()).toBe(true);
    await vi.runOnlyPendingTimersAsync();
    restoreTransactions();
  });

  it("autoStartTxnScan starts the camera only with permission granted", async () => {
    stubZXing(); stubCanvas(); stubRaf();
    await inBatch({ role: "technician" });
    vi.useFakeTimers();
    stubVideo(document.getElementById("txn-scan-video"));
    const scan = await import("../../../backend/static/views/scan.js");
    stubPermissions("prompt");
    scan.autoStartTxnScan();
    await vi.advanceTimersByTimeAsync(10);
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    stubPermissions("granted");
    scan.autoStartTxnScan();
    await vi.waitFor(() => expect(document.getElementById("txn-scan-aimbox").hidden).toBe(false));
    scan.resetScan();
    await vi.runOnlyPendingTimersAsync();
    restoreTransactions();
  });
});
