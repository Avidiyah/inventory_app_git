# Plan: Apply Field-Tested Scan Tuning to Production

Status: **Implemented (pending fleet re-verification).** PR A (frontend
decoder: manual crop loop, TRY_HARDER, 720p, 3-consecutive) and PR B
(upload decoder widened to all zbar symbologies) are done; PR C amended
the superseded decisions in [docs/plan-live-capture.md](plan-live-capture.md).
The decode behaviour was validated on the harness; the production
scanners still need an on-fleet check (see Verification).

This doc captures the production changes implied by the live-decoder
field test, and the decisions it amends in
[docs/plan-live-capture.md](plan-live-capture.md).

---

## Context

The live capture feature shipped per [docs/plan-live-capture.md](plan-live-capture.md).
The restored experiment harness at
[backend/static/scan-test.html](../backend/static/scan-test.html) was used
to A/B the reliability/speed levers on the actual iOS fleet and labels.
This plan ports the winning configuration into the real scanner.

The harness and production share the same decode engine (vendored ZXing)
but differ in entry point: the harness drives a manual
`requestAnimationFrame` + `decodeFromCanvas` loop (so it can crop and
measure per-frame success), while production uses ZXing's
`decodeFromStream` ([backend/static/scan/barcode-decoder.js](../backend/static/scan/barcode-decoder.js#L55)),
which owns its own canvas and only surfaces successful decodes.

---

## Field-tested winning configuration

| Lever | Winning value |
|---|---|
| Restrict to 5 formats | **OFF** — warehouse uses many symbologies |
| Crop to aim-box | **ON** |
| TRY_HARDER | **ON** |
| Capture resolution | **720p** |
| Debounce | **3 consecutive** identical decodes |

These cohere: crop ON is the keystone — it shrinks the decode region so
TRY_HARDER's heavier per-frame search stays affordable, and it strips
background labels so the 3-consecutive fast path can't build a false
streak. 720p is sufficient once the label fills the cropped box.

---

## Production change set

### 1. Crop to the aim-box — move `BarcodeDecoder` to a manual loop

**Why it's the biggest change:** production decodes the full frame via
`decodeFromStream`. Cropping requires owning the frame pump, so
`BarcodeDecoder` moves to the harness's model: a `requestAnimationFrame`
loop that draws the aim-box region of the `<video>` into a scratch
`<canvas>` and calls `reader.decodeFromCanvas(canvas)` (synchronous;
throws `NotFoundException` on a miss).

- **Where:** [backend/static/scan/barcode-decoder.js](../backend/static/scan/barcode-decoder.js).
  The class boundary was designed for exactly this swap (plan-live-capture
  decision #7). Keep the public API (`supports()`, `start(videoEl,
  stream, onDecode)`, `stop()`) so [backend/static/views/scan.js](../backend/static/views/scan.js#L284)
  and its `onDecode` callback are unchanged.
- **Covers both scanners for free:** the Transaction and Saved Items
  scanners both go through this shared class, so one change updates both.
- **Crop geometry ports 1:1 (verified):** the aim-box is `width: 80%;
  aspect-ratio: 3 / 1` ([backend/static/styles.css](../backend/static/styles.css#L769)),
  and `.scan-video` is `width: 100%` with auto height and no `object-fit`
  ([backend/static/styles.css](../backend/static/styles.css#L760)) — so
  the displayed frame is the full intrinsic frame scaled, and 80% of
  display width equals 80% of intrinsic width. The harness's
  `decodeRegion()` math (sw = 0.8·videoWidth, sh = sw/3, centred) applies
  directly. **Keep these constants in sync with the CSS** — a comment on
  both sides should cross-reference.
- **Risk:** owning the rAF loop means owning teardown (`cancelAnimationFrame`
  on `stop()`), Safari canvas rasterisation (`willReadFrequently`), and
  re-entrancy guarding. All proven in the harness.

### 2. TRY_HARDER — one hint

Add `DecodeHintType.TRY_HARDER` (enum value `3`) to the reader's hints
`Map`. Trivial once #1's manual loop builds the reader from hints.

- **Where:** the `buildReader()`-equivalent in
  [backend/static/scan/barcode-decoder.js](../backend/static/scan/barcode-decoder.js).

### 3. Resolution 720p — amends decision #8

Change the `getUserMedia` constraints from `width/height ideal 1920/1080`
to `1280/720`.

- **Where:** [backend/static/views/scan.js](../backend/static/views/scan.js#L232-L240).
- **Amends plan-live-capture decision #8** ("resolution uncapped … no
  max"). The original rationale was small/distant-label decode; the field
  test showed 720p + crop is faster with no reliability loss for handheld
  scans. Update decision #8's row and rationale, don't just edit the code.

### 4. Debounce 3-consecutive — amends decision #18

Replace the 5-of-10 sliding window with the harness's consecutive-streak
logic: accept when the same text decodes **3 times in a row**; a
*differing* successful decode resets the streak; misses (NotFound frames)
between identical hits do **not** break it (focus-flicker tolerance).

- **Where:** [backend/static/scan/frame-debouncer.js](../backend/static/scan/frame-debouncer.js).
  Either reconfigure the class or add a mode; the `pushAndCheck` / `reset`
  interface used by [backend/static/views/scan.js](../backend/static/views/scan.js#L286)
  stays the same.
- **Amends plan-live-capture decision #18** (5-of-10 window). Safe because
  crop (#1) removes the background noise that motivated the wider window.
  Note the traded-away property: a checksum-valid-but-wrong code that
  repeats 3× in a cropped, well-aimed view is now acceptable — field
  testing found this does not occur in practice.

### 5. Widen the upload decoder — the formats finding, server side

**Key insight:** "formats OFF" needs **no change to live decode** —
production already uses `new BrowserMultiFormatReader()` with no hints,
i.e. all-formats. Item `barcode` is an unvalidated unique text column
([backend/app/schemas/items.py](../backend/app/schemas/items.py#L30),
[backend/app/models.py](../backend/app/models.py#L58)), so storage and
lookup are already format-agnostic. The **only** place the 5-format wall
still stands is the upload fallback.

**Change:** drop the 5-symbol restriction in
[backend/app/services/barcodes.py](../backend/app/services/barcodes.py#L41-L47)
so `pyzbar`/`zbar` reads every 1D symbology it supports (Code 39, Code 93,
ITF, Codabar, etc.), not just the canonical five.

- Remove the `symbols=_SUPPORTED_SYMBOLS` argument (or widen the list) in
  `decode_image`.
- Rework `_FORMAT_MAP` ([backend/app/services/barcodes.py](../backend/app/services/barcodes.py#L30-L36)):
  either extend it to cover the new zbar type names, or pass through
  zbar's reported format normalised to a canonical string. Decide whether
  the API contract should still advertise a closed format vocabulary or
  an open one. Update [backend/tests/test_barcodes.py](../backend/tests/test_barcodes.py).
- **Accepted limitation (sharpens decision #3):** zbar cannot read 2D
  codes (DataMatrix, PDF417) that ZXing reads live. So upload will **not**
  reach format parity with live capture. This is accepted: live is the
  primary path; upload is the degraded fallback. Document it rather than
  chasing a server-side 2D decoder.

---

## Decision amendments to plan-live-capture.md

| # | Was | Becomes |
|---|---|---|
| 8 | Resolution uncapped (1080p, no max) | **720p** (`1280×720 ideal`). Faster decode + crop makes pixel count sufficient. |
| 15 | Aim-box is guidance only; **no frame cropping** | **Crop ON.** Decode region = aim-box (80% width, 3:1, centred). |
| 17/#7 | Main-thread `decodeFromStream` loop | **Manual rAF + `decodeFromCanvas` loop** (still main-thread, still behind `BarcodeDecoder`). |
| 18 | Accept on ≥5 of last 10 decodes | **3 consecutive** identical decodes (misses don't break streak). |
| 3 | Two decoders; live skips server verify | Unchanged, but **upload decoder widened** to all zbar 1D formats; 2D parity gap explicitly accepted. |

Also add a `TRY_HARDER` note (new) — not previously a decision.

---

## Phasing (suggested PRs)

1. **PR A — frontend decoder rewrite (#1–#4).** Manual loop + crop +
   TRY_HARDER + 720p + 3-consecutive, all in
   `scan/barcode-decoder.js`, `scan/frame-debouncer.js`, and the
   `getUserMedia` constraints in `views/scan.js`. Single coherent change;
   covers both scanners.
2. **PR B — backend upload widening (#5).** `services/barcodes.py` +
   `test_barcodes.py`, independent of PR A.
3. **PR C — doc sync.** Amend the decision table in
   [docs/plan-live-capture.md](plan-live-capture.md) per the table above.

PRs A and B are independent and can land in either order.

---

## Verification

- The harness validated the *configuration* on the fleet, but production
  uses a different entry point (`decodeFromStream` → manual loop). **Re-run
  the on-fleet check after PR A** using the real Transaction / Saved Items
  scanners, not the harness, to confirm the rewrite preserves the measured
  time-to-accept and success rate.
- PR B: unit tests for the widened format set (a Code 39 / ITF sample
  decodes; an unreadable image still 400s; duplicate collapse preserved).
- Regression: upload mode for the original five formats unchanged; live
  mode still resolves via `apiGetItemByBarcode` (no `/barcodes/decode`).

---

## Out of scope

- Web Worker offload (still deferred; revisit only if the manual loop
  janks the preview).
- Server-side 2D decoding for the upload path (accepted parity gap).
- Camera switching / tap-to-focus / Android focus work (fleet is iOS).
- Any change to live-mode format handling (already all-formats).
