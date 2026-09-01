// Foundation: the one item-save sequence.
//
// Layer: foundation (beside `api.js` / `dom.js`, below the views). Two
// editors now write the same item -- the Saved Items panel
// (`views/itemEditor.js`) and the Low Stock card (`views/lowStockCard.js`)
// -- and the order of operations here is load-bearing in three ways that a
// second hand-written copy would eventually get wrong:
//
//   1. The additional barcodes PATCH goes FIRST, so a duplicate-code 400
//      surfaces before the core fields are touched.
//   2. Both writes ride ONE `confirmArchivedReuse`, so a collision with an
//      archived item prompts once and retries the whole (idempotent)
//      sequence with `override_archived`.
//   3. A changed primary barcode warns first, because scanner labels in
//      the field still pointing at the old code stop resolving.
//
// No DOM access and no selectors: callers own their own markup and pass
// plain values.

import { apiUpdateItem, apiUpdateBarcodes } from "./api.js";
import { confirmArchivedReuse, confirmDialog } from "./dom.js";

export const BARCODE_CHANGE_WARNING =
  "Changing this barcode breaks any scanner labels still pointing at this row. Continue?";

// `fields` is `{barcode, name, location, price, product_link}` -- `price` a
// number or null, `product_link` a string or null. `barcodes` is the full
// desired list of *additional* codes; it is only PATCHed when it differs
// from `originalBarcodes`, so an unchanged list costs no request.
//
// Throws `{cancelled: true}` if the user declines the barcode-change warning
// or the archived-reuse prompt, matching `confirmArchivedReuse`'s contract so
// callers can clear their status line instead of showing an error.
export async function saveItemCore(
  itemId,
  fields,
  { originalBarcode, originalBarcodes = [], barcodes = [] } = {}
) {
  if (fields.barcode !== originalBarcode) {
    const ok = await confirmDialog(BARCODE_CHANGE_WARNING);
    if (!ok) throw { cancelled: true };
  }

  const barcodesChanged =
    JSON.stringify(barcodes) !== JSON.stringify(originalBarcodes);

  await confirmArchivedReuse(async (override) => {
    if (barcodesChanged) {
      await apiUpdateBarcodes(itemId, barcodes, override);
    }
    await apiUpdateItem(itemId, { ...fields, override_archived: override });
  });
}
