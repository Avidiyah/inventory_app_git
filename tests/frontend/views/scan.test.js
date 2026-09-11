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
