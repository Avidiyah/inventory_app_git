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
