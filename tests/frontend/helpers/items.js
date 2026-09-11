// The Find Item / Add Item mount fixture.
//
// items.js fetches nothing at import and nothing on loadItems(); every request
// is a test's explicit choice, so there is no default bundle here -- only the
// one list handler mountItems registers off the `items` it was given.

import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "./handlers.js";
import { startRecording, stopRecording, requests, requestFor, clearRequests } from "./requests.js";
import { importView, mountView } from "./shell.js";
import { setTestUser } from "./session.js";
import { restoreMediaStubs, stubPermissions, stubUserMedia } from "./media.js";
import { restoreBrowserStubs, stubScrollIntoView } from "./browserStubs.js";

// Getters, not nodes: every mount replaces `document.documentElement`, so a
// captured node would be a corpse from the previous test.
const byId = (id) => () => document.getElementById(id);

export const el = {
  page: byId("saved-items-page"),
  search: byId("items-search"), searchBtn: byId("items-search-btn"), loadAllBtn: byId("items-load-all-btn"),
  table: byId("items-table"), theadRow: byId("items-thead-row"), tbody: byId("items-tbody"),
  count: byId("items-count"), empty: byId("items-empty"), emptyText: byId("items-empty-text"),
  emptyExtra: byId("items-empty-extra"), iconSearch: byId("items-empty-icon-search"),
  iconBox: byId("items-empty-icon-box"), message: byId("items-message"),
  createBtn: byId("create-item-btn"), createMessage: byId("create-item-message"),
  barcode: byId("barcode"), name: byId("name"), location: byId("location"),
  quantity: byId("quantity"), price: byId("price"), productLink: byId("product-link"),
  itemScanInput: byId("item-scan-input"), itemScanMessage: byId("item-scan-message"),
  itemScanChooser: byId("item-scan-chooser"), itemScanControls: byId("item-scan-controls"),
  itemScanToggle: byId("item-scan-toggle-btn"),
  itemsScanInput: byId("items-scan-input"), itemsScanMessage: byId("items-scan-message"),
  itemsScanChooser: byId("items-scan-chooser"),
  notesSection: byId("notes-editor-section"), editorSection: byId("item-editor-section"),
  correctionSection: byId("correction-section"), addBarcodeSection: byId("add-barcode-section"),
  subNavBtn: (feature) => document.querySelector(`#saved-items-page .sub-nav-btn[data-feature="${feature}"]`),
};

export const rows = () => Array.from(el.tbody().querySelectorAll("tr"));
export const headers = () => Array.from(el.theadRow().querySelectorAll("th")).map((th) => th.textContent);
export const actionSelect = (rowIndex = 0) => rows()[rowIndex]?.querySelector("select.row-actions-select") ?? null;

// --- request recording -----------------------------------------------------
// The shared recorder in `helpers/requests.js`; re-exported so this fixture's
// import surface is unchanged.
export { requests, requestFor, clearRequests };

// --- answers ----------------------------------------------------------------
export function answerLookup(barcode, itemOrStatus) {
  server.use(http.get(`/items/${encodeURIComponent(barcode)}`, () =>
    typeof itemOrStatus === "number"
      ? HttpResponse.json({ detail: "Item not found" }, { status: itemOrStatus })
      : HttpResponse.json(itemOrStatus)));
}

export function answerDecode(barcodes) {
  server.use(http.post("/barcodes/decode", () =>
    HttpResponse.json({ barcodes: barcodes.map((text) => ({ text, format: "CODE_128" })) })));
}

// --- the shared confirm modal (dom.js) -------------------------------------
export { answerConfirm } from "./dialogs.js";

// --- upload -----------------------------------------------------------------
export async function upload(inputEl, name = "label.png") {
  const file = new File([new Uint8Array([0x89])], name, { type: "image/png" });
  await userEvent.setup().upload(inputEl, file);
}

// --- mount ------------------------------------------------------------------
export async function mountItems({ role = "admin", items = [], handlers = [] } = {}) {
  // `handlers` go FIRST: MSW takes the first matching handler within one
  // `use()` call, so a test's `/items/` override must precede the default.
  // (`/items/:barcode` is a different path and never collides with `/items/`.)
  server.use(
    ...handlers,
    http.get("/items/", ({ request }) => {
      const q = new URL(request.url).searchParams.get("q");
      if (q === null) return HttpResponse.json(items);
      const needle = q.toLowerCase();
      return HttpResponse.json(items.filter((i) =>
        i.name.toLowerCase().includes(needle) || i.barcode.toLowerCase().includes(needle)));
    }),
  );
  stubUserMedia();
  stubPermissions("prompt");
  // The sub-flow panels scroll themselves into view on open; jsdom has no
  // such method, and the call is unguarded in notes.js / itemEditor.js /
  // correctionPanel.js / addBarcode.js.
  stubScrollIntoView();
  const currentUser = await setTestUser({ role });
  startRecording();
  // items.js cannot be the entry point of its own module graph: it reaches
  // nav.js through scan.js -> transactions.js, and nav.js re-enters scan.js
  // through tools.js while scan.js's own imports are still initializing
  // (TDZ on BarcodeDecoder). production/main.js enters at nav.js first, so
  // the fixture primes the graph the same way before importing items.js.
  await mountView("views/nav.js");
  const mod = await importView("views/items.js");
  clearRequests();
  return { mod, currentUser };
}

export function restoreItems() {
  stopRecording();
  restoreMediaStubs();
  restoreBrowserStubs();
}
