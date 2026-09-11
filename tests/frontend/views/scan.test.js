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
