// View: the expanded body of a Low Stock card.
//
// Layer: views. Sibling of `lowStock.js`, which owns the list, the tabs and
// the threshold control; this module owns everything behind the card's
// "Edit item" disclosure -- the core fields, the additional barcodes, and
// the count correction.
//
// The card itself is the `<details>` (`lowStock.js` builds it); this module
// contributes only the markup that sits inside its body, so nothing here is
// a disclosure of its own.
//
// Every handler is delegated off `#low-stock-list`, so cards rebuilt by a
// reload need no rewiring. After any successful save the page reloads in
// the background rather than patching the card, because a correction or a
// threshold change can remove the row it was made on -- the same rule
// `lowStock.js` already follows.

import { apiCreateCorrection } from "../api.js";
import { setMessage } from "../dom.js";
import { escapeHtml, friendlyError } from "../format.js";
import { saveItemCore } from "../itemSave.js";
import { loadLowStock } from "./lowStock.js";

const listEl = document.getElementById("low-stock-list");

function barcodeRowHtml(code) {
  return (
    `<div class="ls-barcode-row">` +
      `<input type="text" class="ls-alt-barcode" placeholder="Additional barcode" ` +
        `aria-label="Additional barcode" value="${escapeHtml(code)}">` +
      `<button type="button" class="note-remove-btn" data-action="remove-barcode" ` +
        `title="Remove" aria-label="Remove barcode">&times;</button>` +
    `</div>`
  );
}

// The editable half of an open card. Built as a string (like the card
// itself) and injected once; the inputs are read back out of the DOM on
// save, so no draft state is held in JS.
export function cardBodyHtml(row) {
  const codes = Array.isArray(row.barcodes) ? row.barcodes : [];
  return (
      `<div class="low-stock-edit">` +
        `<label class="ls-field"><span>Name</span>` +
          `<input type="text" class="ls-name" value="${escapeHtml(row.name)}"></label>` +
        `<label class="ls-field"><span>Barcode</span>` +
          `<input type="text" class="ls-barcode" value="${escapeHtml(row.barcode)}"></label>` +
        `<label class="ls-field"><span>Location</span>` +
          `<input type="text" class="ls-location" value="${escapeHtml(row.location)}"></label>` +
        `<label class="ls-field"><span>Price</span>` +
          `<input type="number" step="0.01" min="0" inputmode="decimal" class="ls-price" ` +
            `value="${escapeHtml(row.price ?? "")}"></label>` +
        `<label class="ls-field ls-field-wide"><span>Product link</span>` +
          `<input type="url" class="ls-product-link" ` +
            `value="${escapeHtml(row.product_link ?? "")}"></label>` +

        `<div class="ls-field ls-field-wide">` +
          `<span>Additional barcodes</span>` +
          `<div class="ls-barcode-rows">${codes.map(barcodeRowHtml).join("")}</div>` +
          `<button type="button" class="secondary-btn" data-action="add-barcode">Add barcode</button>` +
        `</div>` +

        `<div class="ls-actions">` +
          `<button type="button" data-action="save-item">Save item</button>` +
        `</div>` +
      `</div>` +

      `<div class="low-stock-correction">` +
        `<h4>Correct the count</h4>` +
        `<p class="hint">Recording an absolute recount. The app writes the ` +
          `difference as an audited correction, so the reason is required.</p>` +
        `<label class="ls-field"><span>New count</span>` +
          `<input type="number" min="0" step="1" inputmode="numeric" class="ls-correct-qty" ` +
            `value="${escapeHtml(String(Number(row.quantity)))}"></label>` +
        `<label class="ls-field ls-field-wide"><span>Reason</span>` +
          `<input type="text" class="ls-correct-reason" placeholder="Why the count changed"></label>` +
        `<div class="ls-actions">` +
          `<button type="button" data-action="save-correction">Save correction</button>` +
        `</div>` +
      `</div>` +

      `<p class="low-stock-edit-message" aria-live="polite"></p>`
  );
}

function collectAltBarcodes(card, messageEl) {
  const codes = [];
  const seen = new Set();
  for (const input of card.querySelectorAll(".ls-alt-barcode")) {
    const code = input.value.trim();
    if (!code) continue;
    if (seen.has(code)) {
      setMessage(messageEl, `The barcode "${code}" is listed twice. Remove the duplicate.`, "error");
      return null;
    }
    seen.add(code);
    codes.push(code);
  }
  return codes;
}

async function saveItem(card) {
  const messageEl = card.querySelector(".low-stock-edit-message");
  setMessage(messageEl, "", "");

  const barcode = card.querySelector(".ls-barcode").value.trim();
  const name = card.querySelector(".ls-name").value.trim();
  const location = card.querySelector(".ls-location").value.trim();
  const price = card.querySelector(".ls-price").value.trim();
  const productLink = card.querySelector(".ls-product-link").value.trim();

  if (!barcode || !name || !location) {
    setMessage(messageEl, "Barcode, name, and location are required.", "error");
    return;
  }

  const codes = collectAltBarcodes(card, messageEl);
  if (codes === null) return;

  try {
    await saveItemCore(
      card.dataset.id,
      {
        barcode,
        name,
        location,
        price: price ? parseFloat(price) : null,
        product_link: productLink ? productLink : null,
      },
      {
        originalBarcode: card.dataset.barcode,
        originalBarcodes: JSON.parse(card.dataset.barcodes || "[]"),
        barcodes: codes,
      }
    );
    setMessage(messageEl, "Item saved.", "success");
    loadLowStock({ background: true });
  } catch (err) {
    if (err && err.cancelled) {
      setMessage(messageEl, "", "");
      return;
    }
    setMessage(messageEl, friendlyError(err, "Could not save the changes. Try again."), "error");
  }
}

async function saveCorrection(card) {
  const messageEl = card.querySelector(".low-stock-edit-message");
  setMessage(messageEl, "", "");

  const raw = card.querySelector(".ls-correct-qty").value;
  const newQuantity = Number(raw);
  if (raw === "" || !Number.isFinite(newQuantity)) {
    setMessage(messageEl, "Enter a valid new count.", "error");
    return;
  }
  if (newQuantity < 0) {
    setMessage(messageEl, "Enter a count of zero or more.", "error");
    return;
  }
  const reason = card.querySelector(".ls-correct-reason").value.trim();
  if (!reason) {
    setMessage(messageEl, "Enter a reason for the correction.", "error");
    return;
  }

  try {
    await apiCreateCorrection({ itemId: card.dataset.id, newQuantity, reason });
    // A correction that clears the threshold removes this card entirely, so
    // say what happened before the reload takes the message with it.
    setMessage(messageEl, "Count corrected.", "success");
    loadLowStock({ background: true });
  } catch (err) {
    setMessage(messageEl, friendlyError(err, "Could not save the correction. Try again."), "error");
  }
}

if (listEl) {
  listEl.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-action]");
    if (!btn || !listEl.contains(btn)) return;
    const card = btn.closest(".low-stock-card");
    if (!card) return;

    const action = btn.dataset.action;
    if (action === "add-barcode") {
      card.querySelector(".ls-barcode-rows").insertAdjacentHTML("beforeend", barcodeRowHtml(""));
    } else if (action === "remove-barcode") {
      btn.closest(".ls-barcode-row").remove();
    } else if (action === "save-item") {
      saveItem(card);
    } else if (action === "save-correction") {
      saveCorrection(card);
    }
  });
}
