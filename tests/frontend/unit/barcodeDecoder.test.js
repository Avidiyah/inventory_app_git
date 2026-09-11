// scan/barcode-decoder.js: the ZXing wrapper's support gates and its
// requestAnimationFrame crop-and-decode loop, driven frame by frame through
// the stubs in helpers/media.js. Pins the field-tested tuning by number:
// TRY_HARDER on, an 80 % wide 3:1 centred crop, one decode per frame.

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
