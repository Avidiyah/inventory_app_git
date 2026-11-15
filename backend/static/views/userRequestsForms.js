// User Requests: read an open panel into a save payload.
//
// Layer: below userRequests.js, which owns the clicks. Pure reads of the
// panel's fields; each returns `{ error }` when the form is not ready.

export function fulfillPayload(panel) {
  const mode = panel.querySelector(".user-request-mode:checked").value;
  const siblingIds = Array.from(
    panel.querySelectorAll(".user-request-sibling-check:checked")
  ).map((box) => box.value);

  if (mode === "link") {
    const itemId = panel.dataset.pickedItemId || null;
    if (!itemId) return { error: "Search and pick an item first." };
    return { itemId, siblingIds };
  }

  const barcode = panel.querySelector(".user-request-new-barcode").value.trim();
  const name = panel.querySelector(".user-request-new-name").value.trim();
  const location = panel.querySelector(".user-request-new-location").value.trim();
  if (!barcode) return { error: "Enter a barcode for the new item." };
  if (!name) return { error: "Enter a name for the new item." };
  if (!location) return { error: "Enter a location for the new item." };

  const rawPrice = panel.querySelector(".user-request-new-price").value.trim();
  const rawLink = panel.querySelector(".user-request-new-link").value.trim();
  return {
    newItem: {
      barcode,
      name,
      location,
      quantity: Number(panel.querySelector(".user-request-new-qty").value || 0),
      price: rawPrice ? Number(rawPrice) : null,
      product_link: rawLink || null,
    },
    siblingIds,
  };
}

// The Edit panel: `{ message, details }`, `details` null for types whose
// item fields are not editable.
export function editPayload(card, panel) {
  const message = panel.querySelector(".user-request-edit-message").value.trim();
  if (!message) return { error: "The message cannot be blank." };
  const field = (cls) => panel.querySelector(cls).value.trim();

  if (card.dataset.requestType === "material_request") {
    const link = panel.querySelector(".user-request-edit-link");
    if (link.value.trim() && !link.checkValidity()) return { error: "Enter a valid product link." };
    return {
      message,
      details: {
        quantity: field(".user-request-edit-qty") || "1",
        product_link: link.value.trim() || null,
        note: field(".user-request-edit-note") || null,
      },
    };
  }
  if (card.dataset.requestType === "catalogue_request") {
    const text = field(".user-request-edit-text");
    if (!text) return { error: "Describe the item that was searched for." };
    return {
      message,
      details: {
        searched_text: text,
        quantity: field(".user-request-edit-qty") || "1",
        note: field(".user-request-edit-note") || null,
      },
    };
  }
  return { message, details: null };
}
