import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { installFetchSpy, restoreFetchSpy } from "../helpers/fetchSpy.js";
import { mountView } from "../helpers/shell.js";

// itemSave.js -> dom.js -> the shell overlays, so the shell must be mounted
// before the import chain runs. mountView does both, in that order.
let itemSave;
let calls;
let user;

const FIELDS = { barcode: "B1", name: "Bulb", location: "A1", price: 2, product_link: null };

beforeEach(async () => {
  user = userEvent.setup({ document });
  itemSave = await mountView("itemSave.js");
  calls = installFetchSpy();
});

afterEach(() => restoreFetchSpy());

const yes = () => document.getElementById("scan-confirm-yes");
const no = () => document.getElementById("scan-confirm-no");
const overlayShown = () => document.getElementById("scan-confirm-overlay").hidden === false;
const paths = () => calls.map((c) => `${c.init.method ?? "GET"} ${c.url}`);

describe("saveItemCore", () => {
  it("PATCHes the item and skips the barcodes call when the list is unchanged", async () => {
    server.use(http.patch("/items/:id", () => HttpResponse.json({ id: 5 })));
    await itemSave.saveItemCore(5, FIELDS, { originalBarcode: "B1", originalBarcodes: [], barcodes: [] });
    expect(paths()).toEqual(["PATCH /items/5"]);
    expect(JSON.parse(calls[0].init.body)).toEqual({ ...FIELDS, override_archived: false });
  });

  it("PATCHes barcodes FIRST, so a duplicate-code 400 lands before the core fields move", async () => {
    server.use(
      http.patch("/items/:id/barcodes", () => HttpResponse.json({ detail: "Barcode in use" }, { status: 400 })),
      http.patch("/items/:id", () => HttpResponse.json({ id: 5 })),
    );
    await expect(itemSave.saveItemCore(5, FIELDS, {
      originalBarcode: "B1", originalBarcodes: [], barcodes: ["EXTRA"],
    })).rejects.toEqual({ status: 400, detail: "Barcode in use" });
    expect(paths()).toEqual(["PATCH /items/5/barcodes"]);
  });

  it("sends both PATCHes in order when both changed", async () => {
    server.use(
      http.patch("/items/:id/barcodes", () => HttpResponse.json({})),
      http.patch("/items/:id", () => HttpResponse.json({ id: 5 })),
    );
    await itemSave.saveItemCore(5, FIELDS, {
      originalBarcode: "B1", originalBarcodes: ["OLD"], barcodes: ["NEW"],
    });
    expect(paths()).toEqual(["PATCH /items/5/barcodes", "PATCH /items/5"]);
  });

  it("warns before changing the primary barcode and proceeds on Yes", async () => {
    server.use(http.patch("/items/:id", () => HttpResponse.json({ id: 5 })));
    const pending = itemSave.saveItemCore(5, { ...FIELDS, barcode: "B2" }, { originalBarcode: "B1" });
    await vi.waitFor(() => expect(overlayShown()).toBe(true));
    expect(document.getElementById("scan-confirm-title").textContent).toBe(itemSave.BARCODE_CHANGE_WARNING);
    await user.click(yes());
    await pending;
    expect(paths()).toEqual(["PATCH /items/5"]);
  });

  it("throws {cancelled: true} and sends nothing when the barcode warning is declined", async () => {
    // The rejection assertion is attached before the awaits below: the
    // dialog settles while `user.click` is still resolving, and a handler
    // attached afterwards surfaces as an unhandled rejection.
    const pending = itemSave.saveItemCore(5, { ...FIELDS, barcode: "B2" }, { originalBarcode: "B1" });
    const rejected = expect(pending).rejects.toEqual({ cancelled: true });
    await vi.waitFor(() => expect(overlayShown()).toBe(true));
    await user.click(no());
    await rejected;
    expect(calls).toHaveLength(0);
  });

  it("retries the WHOLE sequence with override_archived on a confirmed 409", async () => {
    let attempt = 0;
    server.use(
      http.patch("/items/:id/barcodes", () => HttpResponse.json({})),
      http.patch("/items/:id", () => {
        attempt += 1;
        return attempt === 1
          ? HttpResponse.json({ detail: "archived" }, { status: 409 })
          : HttpResponse.json({ id: 5 });
      }),
    );
    const pending = itemSave.saveItemCore(5, FIELDS, {
      originalBarcode: "B1", originalBarcodes: [], barcodes: ["EXTRA"],
    });
    await vi.waitFor(() => expect(overlayShown()).toBe(true));
    await user.click(yes());
    await pending;
    // Both writes ride ONE confirmArchivedReuse: the barcodes PATCH is
    // re-sent too, with the flag set.
    expect(paths()).toEqual([
      "PATCH /items/5/barcodes", "PATCH /items/5",
      "PATCH /items/5/barcodes", "PATCH /items/5",
    ]);
    expect(JSON.parse(calls[2].init.body)).toMatchObject({ override_archived: true });
    expect(JSON.parse(calls[3].init.body)).toMatchObject({ override_archived: true });
  });

  it("prompts once, not twice, when both the barcode change and a 409 occur", async () => {
    let attempt = 0;
    server.use(http.patch("/items/:id", () => {
      attempt += 1;
      return attempt === 1
        ? HttpResponse.json({ detail: "archived" }, { status: 409 })
        : HttpResponse.json({ id: 5 });
    }));
    const pending = itemSave.saveItemCore(5, { ...FIELDS, barcode: "B2" }, { originalBarcode: "B1" });
    await vi.waitFor(() => expect(overlayShown()).toBe(true));
    await user.click(yes()); // the barcode-change warning
    await vi.waitFor(() => expect(overlayShown()).toBe(true));
    await user.click(yes()); // the archived-reuse confirm
    await pending;
    expect(attempt).toBe(2);
  });
});
