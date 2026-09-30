// Work Orders: the witness Signature section (spec 2026-09-30).
//
// Layer: HTML builders + the drawing pad. The click handlers for
// `save-signature`, `clear-signature`, `clear-signature-pad` and
// `signature-fullscreen` live in workOrderActions.js; this module only
// builds markup and owns the canvas.
// Imports only format.js and workOrderPresenters.js.

import { escapeHtml } from "../format.js";
import { isSupervisorPlus } from "./workOrderPresenters.js";

// Mirror of the domain rule (S7): strip non-digits, drop one leading `1`
// from eleven, require exactly ten. `null` means "not a phone yet".
export function normalizePhone(raw) {
  let digits = String(raw ?? "").replace(/\D/g, "");
  if (digits.length === 11 && digits.startsWith("1")) digits = digits.slice(1);
  return digits.length === 10 ? digits : null;
}

export function signatureSectionHtml(detail) {
  const sig = detail.signature;
  const body = sig
    ? `<img class="wo-signature-image" alt="Witness signature" src="${escapeHtml(sig.image_url)}">
       <p><strong>${escapeHtml(sig.witness_name)}</strong> · ${escapeHtml(sig.witness_phone_display)}</p>
       <p class="hint">Captured by ${escapeHtml(sig.captured_by_name)} on ${escapeHtml(sig.captured_at_label)}</p>
       ${isSupervisorPlus()
         ? `<button type="button" class="btn-danger" data-action="clear-signature">Clear signature</button>`
         : ""}`
    : `<div class="wo-signature-pad-wrap">
         <canvas class="wo-signature-pad" aria-label="Signature pad"></canvas>
         <div class="wo-signature-pad-actions">
           <span class="wo-signature-rotate-hint hint">Turn your phone sideways</span>
           <button type="button" class="secondary-btn" data-action="clear-signature-pad">Clear</button>
           <button type="button" class="secondary-btn" data-action="signature-fullscreen">Full screen</button>
         </div>
       </div>
       <label class="wo-signature-field"><span>Witness Printed Name:</span>
         <input type="text" class="wo-signature-name" maxlength="120"></label>
       <label class="wo-signature-field"><span>Phone number:</span>
         <input type="tel" class="wo-signature-phone" autocomplete="tel"></label>
       <div class="wo-notes-actions"><button type="button" data-action="save-signature" disabled>Save signature</button></div>`;
  return `<details class="wo-section-card wo-signature-section">
            <summary class="wo-section-summary">Signature</summary>
            <div class="wo-section-content">${body}<p class="wo-signature-message" aria-live="polite"></p></div>
          </details>`;
}

// S6: Save needs a stroke, a nonblank name, and a phone that normalizes.
function updateSaveEnabled(section) {
  const save = section.querySelector('[data-action="save-signature"]');
  if (!save) return;
  save.disabled = !(
    section.dataset.hasStroke === "1"
    && section.querySelector(".wo-signature-name")?.value.trim()
    && normalizePhone(section.querySelector(".wo-signature-phone")?.value)
  );
}

// White before ink (S13): the PNG is opaque, so it reads the same in dark mode.
function wipe(canvas) {
  const ctx = canvas.getContext("2d");
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
}

// Idempotent: a section re-opened after a live refresh is a fresh element,
// but the same element toggled twice must not bind twice.
export function mountSignaturePad(section) {
  const canvas = section.querySelector(".wo-signature-pad");
  if (!canvas || section.dataset.padMounted) return;
  section.dataset.padMounted = "1";
  const ratio = window.devicePixelRatio || 1;
  wipe(canvas);
  fitPad(canvas);
  const ctx = canvas.getContext("2d");
  const point = (e) => {
    const r = canvas.getBoundingClientRect();
    return [
      (e.clientX - r.left) * (canvas.width / (r.width || 1)),
      (e.clientY - r.top) * (canvas.height / (r.height || 1)),
    ];
  };
  let drawing = false;
  canvas.addEventListener("pointerdown", (e) => {
    drawing = true;
    canvas.setPointerCapture?.(e.pointerId);
    Object.assign(ctx, { strokeStyle: "#000", lineWidth: 2.5 * ratio, lineCap: "round", lineJoin: "round" });
    ctx.beginPath();
    ctx.moveTo(...point(e));
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!drawing) return;
    ctx.lineTo(...point(e));
    ctx.stroke();
    section.dataset.hasStroke = "1";
    updateSaveEnabled(section);
  });
  const end = () => { drawing = false; };
  canvas.addEventListener("pointerup", end);
  canvas.addEventListener("pointercancel", end);
  section.addEventListener("input", () => updateSaveEnabled(section));
}

// Size the backing store to the CSS box, carrying the drawing across
// contain-fit so a change of shape (full screen, a turned phone) loses
// nothing. A hidden pad (collapsed card) has no box and is left alone.
function fitPad(canvas) {
  const ratio = window.devicePixelRatio || 1;
  const w = Math.round(canvas.clientWidth * ratio);
  const h = Math.round(canvas.clientHeight * ratio);
  if (!w || !h || (w === canvas.width && h === canvas.height)) return;
  const old = document.createElement("canvas");
  old.width = canvas.width;
  old.height = canvas.height;
  old.getContext("2d").drawImage(canvas, 0, 0);
  canvas.width = w;
  canvas.height = h;
  wipe(canvas);
  const s = Math.min(w / old.width, h / old.height);
  canvas.getContext("2d").drawImage(old, 0, 0, old.width * s, old.height * s);
}

// One pad at most can cover the screen, so one exit hook is enough.
let leaveFullscreen = null;

export function toggleSignatureFullscreen(section) {
  const wrap = section.querySelector(".wo-signature-pad-wrap");
  const canvas = wrap.querySelector(".wo-signature-pad");
  leaveFullscreen?.();
  leaveFullscreen = null;
  const full = wrap.classList.toggle("wo-signature-pad-wrap--full");
  wrap.querySelector('[data-action="signature-fullscreen"]').textContent = full ? "Done" : "Full screen";
  if (full) {
    const ac = new AbortController();
    window.addEventListener("resize", () => fitPad(canvas), { signal: ac.signal });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") toggleSignatureFullscreen(section);
    }, { signal: ac.signal });
    leaveFullscreen = () => ac.abort();
  }
  fitPad(canvas); // reading the box forces layout, so the class change is in effect
}

export function clearSignaturePad(section) {
  const canvas = section.querySelector(".wo-signature-pad");
  if (canvas) wipe(canvas);
  delete section.dataset.hasStroke;
  updateSaveEnabled(section);
}

export function signaturePayload(section) {
  return {
    image: section.querySelector(".wo-signature-pad").toDataURL("image/png"),
    witnessName: section.querySelector(".wo-signature-name").value.trim(),
    witnessPhone: normalizePhone(section.querySelector(".wo-signature-phone").value),
  };
}

// Resume after a forced re-login (S11): refill the fields and paint the
// drafted PNG back onto the pad so the operator can save, not redraw.
export function restoreSignatureDraft(section, { image, witnessName, witnessPhone }) {
  mountSignaturePad(section);
  section.querySelector(".wo-signature-name").value = witnessName ?? "";
  section.querySelector(".wo-signature-phone").value = witnessPhone ?? "";
  const canvas = section.querySelector(".wo-signature-pad");
  const img = new Image();
  img.onload = () => {
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    section.dataset.hasStroke = "1";
    section.dispatchEvent(new Event("input")); // re-run the Save gate
  };
  img.src = image;
}
