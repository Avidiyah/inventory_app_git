// Work Orders: the Photos section (spec 2026-11-24 photo export).
//
// Layer: the section HTML (built into the card by workOrderCardHtml.js) and
// two listeners delegated off `#work-orders-list`, registered as a side effect
// of importing this module (as workOrderActions.js does). The strip loads when
// the section opens, so a closed card never fetches previews. Only previews
// are shown; originals leave the server through the Integrations export.

import { apiListWorkOrderPhotos, apiUploadWorkOrderPhoto } from "../api.js";
import { setMessage } from "../dom.js";
import { escapeHtml, friendlyError } from "../format.js";
import { isCrewLocked } from "./workOrderPresenters.js";

export function photosTabLabel(count) {
  return count ? `Photos · ${count}` : "Photos";
}

export function photosSectionHtml(detail) {
  const add = isCrewLocked(detail)
    ? ""
    : `<div class="wo-notes-actions">
         <button type="button" class="secondary-btn wo-photo-take" id="wo-photo-take" data-photo-add="wo-photo-camera">Take photo</button>
         <button type="button" class="secondary-btn" id="wo-photo-add" data-photo-add="wo-photo-input">Add photos</button>
         <input type="file" class="wo-photo-input" id="wo-photo-camera" accept="image/*" capture="environment" hidden>
         <input type="file" class="wo-photo-input" id="wo-photo-input" accept="image/*,.heic,.heif" multiple hidden>
       </div>`;
  return `<details class="wo-section-card wo-photos-section" id="wo-sec-photos">
            <summary class="wo-section-summary">${escapeHtml(photosTabLabel(detail.photo_count))}</summary>
            <div class="wo-section-content">
              <div class="wo-photo-strip" id="wo-photo-strip" data-live-keep aria-label="Work order photos"></div>
              ${add}
              <p id="wo-photos-msg" data-photos-msg data-live-keep aria-live="polite"></p>
            </div>
          </details>`;
}

function stripHtml(photos) {
  if (!photos.length) return `<p class="hint">No photos yet.</p>`;
  return photos
    .map((p) => `<img class="wo-photo-thumb" loading="lazy" alt="${escapeHtml(p.filename)}" title="${escapeHtml(p.filename)}"
                      src="/work-order-photos/${escapeHtml(p.id)}/preview">`)
    .join("");
}

function showCount(section, count) {
  const label = photosTabLabel(count);
  section.querySelector(".wo-section-summary").textContent = label;
  const tab = section.parentElement?.querySelector(':scope > .wo-tabs > .wo-tab[data-wo-tab="photos"]');
  if (tab) tab.textContent = label;
}

export async function loadPhotoStrip(section) {
  const cardEl = section.closest(".wo-card");
  const strip = section.querySelector(".wo-photo-strip");
  try {
    const photos = await apiListWorkOrderPhotos(cardEl.dataset.id);
    strip.innerHTML = stripHtml(photos);
    showCount(section, photos.length);
  } catch (err) {
    setMessage(section.querySelector("[data-photos-msg]"), friendlyError(err, "Could not load photos."), "error");
  }
}

export async function uploadPhotos(section, files) {
  const cardEl = section.closest(".wo-card");
  const msg = section.querySelector("[data-photos-msg]");
  const list = [...files];
  let done = 0;
  try {
    for (const file of list) {
      setMessage(msg, `Uploading ${done + 1} of ${list.length}…`);
      await apiUploadWorkOrderPhoto(cardEl.dataset.id, file);
      done += 1;
    }
    setMessage(msg, `${done} photo${done === 1 ? "" : "s"} added.`, "success");
  } catch (err) {
    const saved = done ? ` ${done} of ${list.length} were saved.` : "";
    setMessage(msg, friendlyError(err, "Could not upload the photo.") + saved, "error");
  }
  await loadPhotoStrip(section);
}

const listEl = document.getElementById("work-orders-list");

// `toggle` does not bubble: capture phase. Every open (including a repaint's
// reopen, which rebuilt the strip empty) reloads it.
listEl?.addEventListener(
  "toggle",
  (event) => {
    if (event.target.matches?.(".wo-photos-section") && event.target.open) loadPhotoStrip(event.target);
  },
  true
);

listEl?.addEventListener("click", (event) => {
  const btn = event.target.closest?.("[data-photo-add]");
  // Take photo -> the camera input (phones open the rear camera); Add photos -> the gallery.
  if (btn) btn.closest(".wo-photos-section").querySelector(`#${btn.dataset.photoAdd}`).click();
});

listEl?.addEventListener("change", (event) => {
  const input = event.target;
  if (!input.classList?.contains("wo-photo-input") || !input.files?.length) return;
  const files = [...input.files];
  input.value = ""; // picking the same file again still fires change
  uploadPhotos(input.closest(".wo-photos-section"), files);
});
