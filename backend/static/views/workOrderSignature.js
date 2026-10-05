// Work Orders: the witness Signature section and its guided sign-off flow
// (spec 2026-09-30, reworked into a step-by-step pop-up 2026-10-05).
//
// Layer: HTML builders, the four-step pop-up, and the drawing pad. The card's
// two actions (`capture-signature`, `clear-signature`) are dispatched in
// workOrderActions.js, which also owns the save: the flow hands it a payload
// through `onSave` and handles only its own `data-sig` buttons.
// Imports only format.js and workOrderPresenters.js.

import { escapeHtml, friendlyError } from "../format.js";
import { isSupervisorPlus } from "./workOrderPresenters.js";

// Mirror of the domain rule (S7): strip non-digits, drop one leading `1`
// from eleven, require exactly ten. `null` means "not a phone yet".
export function normalizePhone(raw) {
  let digits = String(raw ?? "").replace(/\D/g, "");
  if (digits.length === 11 && digits.startsWith("1")) digits = digits.slice(1);
  return digits.length === 10 ? digits : null;
}

// The same rule as the witness types. Punctuation appears only once a digit
// follows it, so Backspace never lands on a character that grows back.
export function formatPhone(raw) {
  let d = String(raw ?? "").replace(/\D/g, "");
  if (d.length === 11 && d.startsWith("1")) d = d.slice(1);
  if (d.length > 10) return String(raw); // not a phone: show what was typed
  if (d.length < 4) return d;
  return `(${d.slice(0, 3)}) ${d.slice(3, 6)}${d.length > 6 ? `-${d.slice(6)}` : ""}`;
}

export function signatureSectionHtml(detail) {
  const sig = detail.signature;
  const body = sig
    ? `<img class="wo-signature-image" alt="Witness signature" src="${escapeHtml(sig.image_url)}">
       <p><strong>${escapeHtml(sig.witness_name)}</strong> · ${escapeHtml(sig.witness_phone_display)}</p>
       <p class="hint">Captured by ${escapeHtml(sig.captured_by_name)} on ${escapeHtml(sig.captured_at_label)}</p>
       ${isSupervisorPlus()
         ? `<button type="button" class="btn-danger" data-action="clear-signature" data-witness="${escapeHtml(sig.witness_name)}">Clear signature</button>`
         : ""}`
    : `<p class="hint">Captured step by step with the witness present. It locks once saved.</p>
       <div class="wo-notes-actions"><button type="button" data-action="capture-signature">Capture witness signature</button></div>`;
  return `<details class="wo-section-card wo-signature-section">
            <summary class="wo-section-summary">Signature</summary>
            <div class="wo-section-content">${body}<p class="wo-signature-message" aria-live="polite"></p></div>
          </details>`;
}

// --- the pad -------------------------------------------------------------

const ASPECT = 5 / 2; // the paper: the on-screen pad and the saved PNG share it
const EXPORT_W = 1000; // the saved PNG is 1000x400 whatever the device
const MAX_PAD_W = 900;
const INK = 0.0042; // base line width, as a fraction of the paper's width

// Pen feel: the line thins as the hand speeds up (`speed` in paper-widths per
// second), and the low-pass keeps it from stepping between samples.
export function inkWidth(prev, speed) {
  const target = Math.min(1.3, Math.max(0.6, 1.3 - 0.35 * speed));
  return prev * 0.6 + target * 0.4;
}

// One stroke of `[x, y, width]` points in paper coordinates (0..1 each way).
// Smooth ink is a quadratic through each pair's midpoint, one short path per
// segment so the width can vary and nothing is stroked twice. `from` lets a
// live stroke draw only its new points; `done` adds the tail to the last one.
function drawStroke(ctx, pts, W, H, from, done) {
  const X = (p) => p[0] * W;
  const Y = (p) => p[1] * H;
  const base = INK * W;
  const last = pts[pts.length - 1];
  if (pts.length === 1) {
    if (!done) return;
    ctx.beginPath(); // a tap: i-dots and periods
    ctx.arc(X(last), Y(last), (base * last[2]) / 2, 0, 2 * Math.PI);
    ctx.fill();
    return;
  }
  for (let i = Math.max(from, 1); i < pts.length; i++) {
    const a = pts[i - 1];
    const b = pts[i];
    const start = i === 1 ? a : [(pts[i - 2][0] + a[0]) / 2, (pts[i - 2][1] + a[1]) / 2];
    ctx.beginPath();
    ctx.lineWidth = (base * (a[2] + b[2])) / 2;
    ctx.moveTo(X(start), Y(start));
    ctx.quadraticCurveTo(X(a), Y(a), (X(a) + X(b)) / 2, (Y(a) + Y(b)) / 2);
    ctx.stroke();
  }
  if (!done) return;
  const prev = pts[pts.length - 2];
  ctx.beginPath();
  ctx.lineWidth = base * last[2];
  ctx.moveTo((X(prev) + X(last)) / 2, (Y(prev) + Y(last)) / 2);
  ctx.lineTo(X(last), Y(last));
  ctx.stroke();
}

function paint(ctx, strokes, W, H, guide) {
  ctx.fillStyle = "#fff"; // opaque white (S13): the PNG reads the same in dark mode
  ctx.fillRect(0, 0, W, H);
  Object.assign(ctx, { lineCap: "round", lineJoin: "round" });
  if (guide) {
    // The sign-here line: on the pad only, never in the saved PNG.
    Object.assign(ctx, { strokeStyle: "#c4c4c4", lineWidth: Math.max(1, W * 0.002) });
    ctx.beginPath();
    ctx.moveTo(W * 0.06, H * 0.78);
    ctx.lineTo(W * 0.94, H * 0.78);
    ctx.stroke();
  }
  Object.assign(ctx, { strokeStyle: "#000", fillStyle: "#000" });
  for (const stroke of strokes) drawStroke(ctx, stroke, W, H, 1, true);
}

// The pad keeps strokes, not pixels: every resize, Undo and the saved PNG are
// a fresh drawing of the same points, so nothing blurs, shrinks or stretches.
function createPad(canvas, onChange) {
  const ctx = canvas.getContext("2d");
  const strokes = [];
  let turned = false;
  // ponytail: the first contact owns the pad, so a palm that lands before the
  // finger blocks it until lifted. Prefer pointerType "pen" if that bites.
  let active = null;
  let current = null;
  let lastT = 0;

  const repaint = () => paint(ctx, strokes, canvas.width, canvas.height, true);

  // Paper coordinates of a pointer event. A turned pad's own x runs down the
  // screen and its y runs right to left.
  function point(e) {
    const r = canvas.getBoundingClientRect();
    const across = (e.clientX - r.left) / (r.width || 1);
    const down = (e.clientY - r.top) / (r.height || 1);
    return turned ? [down, 1 - across] : [across, down];
  }

  function add(e) {
    const [x, y] = point(e);
    const prev = current[current.length - 1];
    const dist = Math.hypot(x - prev[0], (y - prev[1]) / ASPECT); // paper widths
    if (dist < 0.0015) return; // sub-pixel jitter
    const seconds = Math.max(e.timeStamp - lastT, 1) / 1000;
    lastT = e.timeStamp;
    current.push([x, y, inkWidth(prev[2], dist / seconds)]);
  }

  canvas.addEventListener("pointerdown", (e) => {
    if (active !== null || e.button) return;
    active = e.pointerId;
    current = [[...point(e), 1]];
    strokes.push(current);
    lastT = e.timeStamp;
    onChange();
    canvas.setPointerCapture?.(e.pointerId);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (e.pointerId !== active) return;
    const from = current.length;
    // Every digitizer sample, not one per frame: a fast curve stays round.
    const samples = e.getCoalescedEvents?.() ?? [];
    for (const sample of samples.length ? samples : [e]) add(sample);
    drawStroke(ctx, current, canvas.width, canvas.height, from, false);
  });
  const end = (e) => {
    if (e.pointerId !== active) return;
    drawStroke(ctx, current, canvas.width, canvas.height, current.length, true);
    active = current = null;
  };
  canvas.addEventListener("pointerup", end);
  canvas.addEventListener("pointercancel", end);

  function drop(count) {
    strokes.splice(strokes.length - count, count);
    active = current = null; // a second finger on a button mid-stroke
    repaint();
    onChange();
  }

  return {
    isEmpty: () => strokes.length === 0,
    clear: () => drop(strokes.length),
    undo: () => drop(1),
    // Size the pad to the largest paper its stage holds, then redraw.
    fit(isTurned) {
      turned = isTurned;
      const stage = canvas.parentElement;
      canvas.hidden = true; // measure the stage, not the old pad
      const w = Math.min(
        stage.clientWidth, stage.clientHeight ? stage.clientHeight * ASPECT : Infinity, MAX_PAD_W,
      );
      canvas.hidden = false;
      const ratio = window.devicePixelRatio || 1;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${w / ASPECT}px`;
      canvas.width = Math.round(w * ratio);
      canvas.height = Math.round((w / ASPECT) * ratio);
      repaint();
    },
    toPng() {
      const out = document.createElement("canvas");
      out.width = EXPORT_W;
      out.height = EXPORT_W / ASPECT;
      paint(out.getContext("2d"), strokes, out.width, out.height, false);
      return out.toDataURL("image/png");
    },
  };
}

// --- the flow ------------------------------------------------------------

const STEPS = [
  ["intro", "Before you start"],
  ["details", "Witness details"],
  ["sign", "Witness signs"],
  ["confirm", "Confirm sign-off"],
];

function flowHtml(number) {
  const wo = escapeHtml(number);
  return `<div class="modal-box wo-sig-box" role="dialog" aria-modal="true" aria-labelledby="wo-sig-title" tabindex="-1">
    <p class="wo-sig-step hint"></p>
    <p class="modal-title" id="wo-sig-title"></p>
    <div class="wo-sig-panel" data-step="intro">
      <ul class="wo-sig-guidance">
        <li>You enter the witness's printed name and phone number, then hand them this device to sign.</li>
        <li>The witness signs in their own hand. Never sign for someone else.</li>
        <li>Once saved, the sign-off is locked and recorded under your name. Only a supervisor can clear it.</li>
      </ul>
      <div class="modal-buttons">
        <button type="button" class="secondary-btn" data-sig="cancel">Cancel</button>
        <button type="button" data-sig="next">Begin</button>
      </div>
    </div>
    <div class="wo-sig-panel" data-step="details" hidden>
      <label class="wo-signature-field"><span>Witness printed name</span>
        <input type="text" class="wo-signature-name" maxlength="120" autocomplete="off" autocapitalize="words"></label>
      <label class="wo-signature-field"><span>Witness phone number</span>
        <input type="tel" class="wo-signature-phone" inputmode="tel" autocomplete="off" placeholder="(555) 555-1234"></label>
      <p class="wo-sig-needed hint" aria-live="polite"></p>
      <div class="modal-buttons">
        <button type="button" class="secondary-btn" data-sig="back">Back</button>
        <button type="button" data-sig="next" disabled>Continue</button>
      </div>
    </div>
    <div class="wo-sig-panel" data-step="sign" hidden>
      <p class="hint">Hand the device to the witness. Sign above the line, then press Submit.</p>
      <div class="wo-sig-stage"><canvas class="wo-signature-pad" aria-label="Signature pad"></canvas></div>
      <div class="modal-buttons wo-sig-sign-actions">
        <button type="button" class="secondary-btn" data-sig="back">Back</button>
        <button type="button" class="secondary-btn" data-sig="clear" disabled>Clear</button>
        <button type="button" class="secondary-btn" data-sig="undo" disabled>Undo stroke</button>
        <button type="button" data-sig="next" disabled>Submit</button>
      </div>
    </div>
    <div class="wo-sig-panel" data-step="confirm" hidden>
      <img class="wo-signature-image wo-sig-preview" alt="Witness signature">
      <p class="wo-sig-who"></p>
      <p class="hint">Saving locks this sign-off to WO ${wo} and records it under your name. Only a supervisor can clear it.</p>
      <p class="wo-sig-error" aria-live="polite"></p>
      <div class="modal-buttons">
        <button type="button" class="secondary-btn" data-sig="back">Go back</button>
        <button type="button" data-sig="save">Save and lock</button>
      </div>
    </div>
  </div>`;
}

// One flow at a time, mounted on the Work Orders page rather than in the list:
// the list's `<section>` has a backdrop-filter, which traps a fixed overlay
// inside it. On the page it still hides with the app at the login screen.
// `onSave(payload)` resolving closes the flow; throwing keeps it open with the
// reason shown.
export function openSignatureFlow({ number, onSave }) {
  const host = document.getElementById("work-orders-page") ?? document.body;
  if (host.querySelector(".wo-sig-flow")) return;
  const opener = document.activeElement;
  const flow = document.createElement("div");
  flow.className = "modal-overlay wo-sig-flow";
  flow.innerHTML = flowHtml(number);
  host.appendChild(flow);

  const one = (selector) => flow.querySelector(selector);
  const box = one(".wo-sig-box");
  const name = one(".wo-signature-name");
  const phone = one(".wo-signature-phone");
  const listeners = new AbortController();
  let step = 0;
  let image = "";
  const panel = () => one(`[data-step="${STEPS[step][0]}"]`);

  // Each step says what it still needs rather than leaving a dead button.
  function gate() {
    const missing = [
      name.value.trim() ? null : "printed name",
      normalizePhone(phone.value) ? null : "10-digit phone number",
    ].filter(Boolean);
    one(".wo-sig-needed").textContent = missing.length ? `Still needed: ${missing.join(" and ")}.` : "";
    one('[data-step="details"] [data-sig="next"]').disabled = missing.length > 0;
    for (const act of ["clear", "undo", "next"]) {
      one(`[data-step="sign"] [data-sig="${act}"]`).disabled = pad.isEmpty();
    }
  }
  const pad = createPad(one(".wo-signature-pad"), gate);

  function layout() {
    const signing = STEPS[step][0] === "sign";
    const { clientWidth: W, clientHeight: H } = flow;
    // A phone signs edge to edge. A portrait one signs sideways: the box is
    // laid out landscape and turned a quarter, so the pad gets the long edge
    // whatever the rotation lock says. Leaving the step stands it back up.
    const full = signing && (W <= 700 || H <= 500);
    const turned = full && W < H;
    flow.classList.toggle("wo-sig-flow--sign", signing);
    flow.classList.toggle("wo-sig-flow--full", full);
    flow.classList.toggle("wo-sig-flow--turned", turned);
    box.style.width = turned ? `${H}px` : "";
    box.style.height = turned ? `${W}px` : "";
    if (signing) pad.fit(turned);
  }

  function show(index) {
    step = index;
    for (const el of flow.querySelectorAll(".wo-sig-panel")) el.hidden = el !== panel();
    one(".wo-sig-step").textContent = `Step ${step + 1} of ${STEPS.length} · WO ${number}`;
    one(".modal-title").textContent = STEPS[step][1];
    if (STEPS[step][0] === "confirm") {
      image = pad.toPng();
      one(".wo-sig-preview").src = image;
      one(".wo-sig-who").textContent = `${name.value.trim()} · ${formatPhone(phone.value)}`;
    }
    layout();
    // Never a button: a stray Enter must not carry a step.
    (panel().querySelector("input") ?? box).focus();
  }

  function close() {
    listeners.abort();
    flow.remove();
    opener?.focus?.();
  }

  flow.addEventListener("click", async (event) => {
    const btn = event.target.closest("[data-sig]");
    if (!btn) return;
    const act = btn.dataset.sig;
    if (act === "cancel") close();
    else if (act === "back") show(step - 1);
    else if (act === "next") show(step + 1);
    else if (act === "clear") pad.clear();
    else if (act === "undo") pad.undo();
    else if (act === "save") {
      // A double tap must not race itself into a 409 under its own signature.
      btn.disabled = true;
      one(".wo-sig-error").textContent = "";
      try {
        await onSave({ image, witnessName: name.value.trim(), witnessPhone: normalizePhone(phone.value) });
        close();
      } catch (err) {
        btn.disabled = false;
        one(".wo-sig-error").textContent = friendlyError(err, "Could not save the sign-off.");
      }
    }
  });
  flow.addEventListener("input", (event) => {
    // Only at the end of the field: reformatting mid-edit would move the caret.
    if (event.target === phone && phone.selectionStart === phone.value.length) {
      phone.value = formatPhone(phone.value);
    }
    gate();
  });
  window.addEventListener("resize", layout, { signal: listeners.signal });
  // Browser Back swaps the page under the flow; its card is gone with it.
  window.addEventListener("popstate", close, { signal: listeners.signal });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (step) show(step - 1);
      else close();
      return;
    }
    if (event.key !== "Tab") return;
    const stops = [...panel().querySelectorAll("input, button:not([disabled])")];
    const at = stops.indexOf(document.activeElement);
    if (event.shiftKey ? at <= 0 : at === -1 || at === stops.length - 1) {
      event.preventDefault();
      stops[event.shiftKey ? stops.length - 1 : 0].focus();
    }
  }, { signal: listeners.signal });

  gate();
  show(0);
}
