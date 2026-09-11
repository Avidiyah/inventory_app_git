import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import {
  actionSelect, answerConfirm, answerDecode, answerLookup, clearRequests, el, headers, mountItems,
  requestFor, requests, restoreItems, rows, upload,
} from "../helpers/items.js";
import { item as itemFactory } from "../helpers/factories.js";

afterEach(() => restoreItems());

describe("mountItems", () => {
  it("mounts against the real Find Item markup with nothing loaded", async () => {
    const { mod } = await mountItems({ role: "admin" });
    expect(typeof mod.loadItems).toBe("function");
    expect(el.table().hidden).toBe(true);
    expect(requests()).toHaveLength(0);
  });
});

describe("loadItems", () => {
  it("opens empty: no request, search cleared, empty panel with the opening copy", async () => {
    const { mod } = await mountItems({ role: "admin", items: [itemFactory()] });
    el.search().value = "stale";
    mod.loadItems();
    expect(requests()).toHaveLength(0);
    expect(el.search().value).toBe("");
    expect(el.table().hidden).toBe(true);
    expect(el.empty().hidden).toBe(false);
    expect(el.emptyText().textContent).toBe("Search by name or barcode to get started.");
    expect(el.iconSearch().hidden).toBe(false);
    expect(el.iconBox().hidden).toBe(true);
    expect(el.count().hidden).toBe(true);
  });
});

describe("search", () => {
  it("a blank term asks for one, focuses the field and fetches nothing", async () => {
    await mountItems({ role: "admin" });
    await userEvent.setup().click(el.searchBtn());
    expect(el.message().textContent).toBe("Enter a name or barcode to search.");
    expect(el.message().className).toBe("error");
    expect(document.activeElement).toBe(el.search());
    expect(requests()).toHaveLength(0);
  });

  it("Search sends the trimmed term as q, paints a skeleton, then rows and a count", async () => {
    const items = [itemFactory({ name: "Bulb A19", barcode: "B1" }), itemFactory({ name: "Bulb PAR", barcode: "B2" })];
    await mountItems({ role: "admin", items });
    const user = userEvent.setup();
    await user.type(el.search(), "  bulb  ");
    await user.click(el.searchBtn());
    await vi.waitFor(() => expect(rows()).toHaveLength(2));
    expect(requestFor("/items/?q=", "GET").url).toBe("/items/?q=bulb");
    expect(el.count().textContent).toBe("2 items found");
    expect(el.searchBtn().disabled).toBe(false);
    expect(el.loadAllBtn().disabled).toBe(false);
  });

  it("while a search is in flight the table shows a skeleton and both buttons are disabled", async () => {
    // user-event's click resolves only after its own pipeline has run, by
    // which time a resolved fetch has already repainted -- so the in-flight
    // state is observed against a list request that never answers.
    await mountItems({ role: "admin", handlers: [
      http.get("/items/", () => new Promise(() => {})),
    ] });
    const user = userEvent.setup();
    await user.type(el.search(), "bulb");
    user.click(el.searchBtn());
    await vi.waitFor(() => expect(el.searchBtn().disabled).toBe(true));
    expect(el.table().hidden).toBe(false);
    expect(el.loadAllBtn().disabled).toBe(true);
    expect(el.empty().hidden).toBe(true);
    expect(el.count().hidden).toBe(true);
    expect(el.tbody().querySelectorAll("tr.skel-row")).toHaveLength(6);
    expect(rows()[0].querySelector(".sr-only").textContent).toBe("Loading…");
  });

  it("Enter in the field searches too, and one result reads '1 item found'", async () => {
    await mountItems({ role: "admin", items: [itemFactory({ name: "Only", barcode: "Z9" })] });
    await userEvent.setup().type(el.search(), "only{Enter}");
    await vi.waitFor(() => expect(rows()).toHaveLength(1));
    expect(el.count().textContent).toBe("1 item found");
  });

  it("no match: empty panel with search icon and the catalogue-request prompt for the term", async () => {
    await mountItems({ role: "admin", items: [] });
    await userEvent.setup().type(el.search(), "widget{Enter}");
    await vi.waitFor(() => expect(el.empty().hidden).toBe(false));
    expect(el.table().hidden).toBe(true);
    expect(el.emptyText().textContent).toBe("No items match that search.");
    expect(el.iconSearch().hidden).toBe(false);
    const prompt = el.emptyExtra().querySelector(".catalogue-request");
    expect(prompt.dataset.source).toBe("find_item");
    expect(prompt.dataset.searchedText).toBe("widget");
  });

  it("a failed list renders friendlyError in a single error cell and re-enables the buttons", async () => {
    await mountItems({ role: "admin", handlers: [
      http.get("/items/", () => HttpResponse.json({ detail: "boom" }, { status: 500 })),
    ] });
    await userEvent.setup().type(el.search(), "x{Enter}");
    await vi.waitFor(() => expect(el.tbody().querySelector("td.error")).not.toBeNull());
    // DEFECT (N-P5-CHARACTERIZED): the colspan is hardcoded at 8 while an
    // admin's table has 9 columns, so the error cell under-spans.
    expect(el.tbody().querySelector("td.error").getAttribute("colspan")).toBe("8");
    expect(headers()).toHaveLength(9);
    expect(el.searchBtn().disabled).toBe(false);
  });

  it("a slower earlier search cannot overwrite a later one (request id guard)", async () => {
    let releaseFirst;
    const first = new Promise((r) => { releaseFirst = r; });
    let calls = 0;
    await mountItems({ role: "admin", handlers: [
      http.get("/items/", async ({ request }) => {
        calls += 1;
        const q = new URL(request.url).searchParams.get("q");
        if (calls === 1) await first;
        return HttpResponse.json([itemFactory({ name: `result for ${q}`, barcode: q })]);
      }),
    ] });
    const user = userEvent.setup();
    await user.type(el.search(), "one{Enter}");
    await user.clear(el.search());
    await user.type(el.search(), "two{Enter}");
    await vi.waitFor(() => expect(rows()).toHaveLength(1));
    releaseFirst();
    await new Promise((r) => setTimeout(r, 20));
    expect(rows()[0].textContent).toContain("result for two");
  });
});

describe("load all", () => {
  it("clears the search box, fetches /items/ with no q, and uses the box icon when empty", async () => {
    await mountItems({ role: "admin", items: [] });
    const user = userEvent.setup();
    await user.type(el.search(), "leftover");
    await user.click(el.loadAllBtn());
    await vi.waitFor(() => expect(el.empty().hidden).toBe(false));
    expect(el.search().value).toBe("");
    expect(requestFor("/items/", "GET").url).toBe("/items/");
    expect(el.emptyText().textContent).toBe("No items yet.");
    expect(el.iconBox().hidden).toBe(false);
    expect(el.iconSearch().hidden).toBe(true);
    expect(el.emptyExtra().innerHTML).toBe(""); // no catalogue prompt on load-all
  });
});

describe("renderItems cells", () => {
  it("money, safe link, notes summary, escaped name", async () => {
    const items = [itemFactory({
      name: "<b>Bold</b>", price: "12.5", product_link: "https://example.com/p",
      notes: { color: "red" }, quantity: "3",
    }), itemFactory({ price: null, product_link: "javascript:alert(1)", notes: {} })];
    await mountItems({ role: "admin", items });
    await userEvent.setup().click(el.loadAllBtn());
    await vi.waitFor(() => expect(rows()).toHaveLength(2));
    const [r1, r2] = rows();
    expect(r1.textContent).toContain("$12.50");
    expect(r1.querySelector("a[href='https://example.com/p']").getAttribute("rel")).toBe("noopener noreferrer");
    expect(r1.querySelector("b")).toBeNull();
    expect(r1.textContent).toContain("<b>Bold</b>");
    expect(r1.querySelector(".notes-cell").textContent).toBe("color: red");
    expect(r1.querySelector("strong").textContent).toBe("3");
    expect(r2.querySelector("a")).toBeNull();
    expect(r2.querySelector(".notes-cell .empty")).not.toBeNull();
  });

  // DEFECT (N-P5-CHARACTERIZED): the Created cell is
  // `new Date(i.created_at).toLocaleString()` with no guard, so a missing
  // timestamp is rendered as a date rather than left blank.
  const createdCell = () => Array.from(rows()[0].querySelectorAll("td"))
    .find((td) => td.dataset.label === "Created");

  it("a null created_at renders the epoch, not a blank", async () => {
    await mountItems({ role: "admin", items: [itemFactory({ created_at: null })] });
    await userEvent.setup().click(el.loadAllBtn());
    await vi.waitFor(() => expect(rows()).toHaveLength(1));
    // Compared against the epoch rendered here, so the assertion holds in any
    // timezone -- the point is that a missing date renders as a real one.
    expect(createdCell().textContent).toBe(new Date(0).toLocaleString());
  });

  it("an absent created_at renders the literal 'Invalid Date'", async () => {
    const { created_at, ...withoutCreatedAt } = itemFactory();
    await mountItems({ role: "admin", items: [withoutCreatedAt] });
    await userEvent.setup().click(el.loadAllBtn());
    await vi.waitFor(() => expect(rows()).toHaveLength(1));
    expect(createdCell().textContent).toBe("Invalid Date");
  });

  it("the primary (name) cell carries data-primary; others carry data-label", async () => {
    await mountItems({ role: "admin", items: [itemFactory()] });
    await userEvent.setup().click(el.loadAllBtn());
    await vi.waitFor(() => expect(rows()).toHaveLength(1));
    const tds = rows()[0].querySelectorAll("td");
    expect(tds[1].hasAttribute("data-primary")).toBe(true);
    expect(tds[0].dataset.label).toBe("Barcode");
  });
});

describe("itemColumns per role", () => {
  it.each([
    ["technician", ["Name", "Quantity", "Location", "Barcode", "Notes"], []],
    ["supervisor", ["Barcode", "Name", "Quantity", "Location", "Notes", "Created", "Actions"], ["notes"]],
    ["techfm_oa", ["Barcode", "Name", "Quantity", "Location", "Notes", "Price", "Link", "Created", "Actions"], ["edit", "notes", "correct", "delete"]],
    ["admin", ["Barcode", "Name", "Quantity", "Location", "Notes", "Price", "Link", "Created", "Actions"], ["edit", "notes", "correct", "delete"]],
    ["owner", ["Barcode", "Name", "Quantity", "Location", "Notes", "Price", "Link", "Created", "Actions"], ["edit", "notes", "correct", "delete"]],
  ])("%s sees %j with actions %j", async (role, expectedHeaders, actions) => {
    await mountItems({ role, items: [itemFactory({ name: "Widget" })] });
    await userEvent.setup().click(el.loadAllBtn());
    await vi.waitFor(() => expect(rows()).toHaveLength(1));
    expect(headers()).toEqual(expectedHeaders);
    const select = actionSelect(0);
    if (actions.length === 0) {
      expect(select).toBeNull();
    } else {
      expect(Array.from(select.options).map((o) => o.value).filter(Boolean)).toEqual(actions);
      expect(select.getAttribute("aria-label")).toBe("Actions for Widget");
      expect(rows()[0].querySelector(`label[for="${select.id}"]`).className).toBe("sr-only");
    }
  });

  it("the skeleton header matches the role's column count", async () => {
    await mountItems({ role: "technician", handlers: [
      http.get("/items/", () => new Promise(() => {})), // never resolves
    ] });
    userEvent.setup().click(el.loadAllBtn());
    await vi.waitFor(() => expect(headers()).toHaveLength(5));
    expect(rows()).toHaveLength(6);
    expect(rows()[0].querySelectorAll("td")).toHaveLength(5);
  });
});

async function loadedRow(role = "admin", overrides = {}) {
  const target = itemFactory({ name: "Target", ...overrides });
  const mounted = await mountItems({ role, items: [target] });
  await userEvent.setup().click(el.loadAllBtn());
  await vi.waitFor(() => expect(rows()).toHaveLength(1));
  clearRequests();
  return { ...mounted, target };
}

describe("row actions", () => {
  it("edit opens the item editor for that row and resets the select", async () => {
    const { target } = await loadedRow();
    await userEvent.setup().selectOptions(actionSelect(0), "edit");
    expect(el.editorSection().hidden).toBe(false);
    expect(document.getElementById("item-editor-selected").textContent).toBe("Editing: Target");
    expect(document.getElementById("item-editor-barcode").value).toBe(target.barcode);
    expect(actionSelect(0).value).toBe("");
  });

  it("correct opens the correction panel", async () => {
    await loadedRow();
    await userEvent.setup().selectOptions(actionSelect(0), "correct");
    expect(el.correctionSection().hidden).toBe(false);
    expect(document.getElementById("correction-selected").textContent).toContain("Target");
  });

  it("notes opens the notes editor", async () => {
    await loadedRow("supervisor");
    await userEvent.setup().selectOptions(actionSelect(0), "notes");
    expect(el.notesSection().hidden).toBe(false);
    expect(document.getElementById("notes-editor-selected").textContent).toBe("Editing notes for: Target");
  });

  it("delete: No leaves the item and issues nothing", async () => {
    await loadedRow();
    const choosing = userEvent.setup().selectOptions(actionSelect(0), "delete");
    await answerConfirm(false);
    await choosing;
    expect(requestFor("/items/", "DELETE")).toBeNull();
    expect(rows()).toHaveLength(1);
  });

  it("delete: Yes archives, closes an open sub-flow for that item, reports, and refreshes the displayed set", async () => {
    const { target } = await loadedRow();
    server.use(http.delete(`/items/${target.id}`, () => new HttpResponse(null, { status: 204 })));
    const user = userEvent.setup();
    await user.selectOptions(actionSelect(0), "edit");
    expect(el.editorSection().hidden).toBe(false);
    const choosing = user.selectOptions(actionSelect(0), "delete");
    await answerConfirm(true);
    await choosing;
    await vi.waitFor(() => expect(el.message().textContent).toBe('Archived "Target".'));
    expect(el.message().className).toBe("success");
    expect(requestFor(`/items/${target.id}`, "DELETE")).not.toBeNull();
    expect(el.editorSection().hidden).toBe(true);
    expect(requestFor("/items/", "GET").url).toBe("/items/"); // load-all mode refreshes with no q
  });

  it("delete: a failing DELETE surfaces friendlyError", async () => {
    const { target } = await loadedRow();
    server.use(http.delete(`/items/${target.id}`, () => HttpResponse.json({ detail: "nope" }, { status: 403 })));
    const choosing = userEvent.setup().selectOptions(actionSelect(0), "delete");
    await answerConfirm(true);
    await choosing;
    await vi.waitFor(() => expect(el.message().className).toBe("error"));
    expect(el.message().textContent).toBe("Your account can't do that. Ask a supervisor if this seems wrong.");
    expect(rows()).toHaveLength(1);
  });

  it("the confirm copy names the item", async () => {
    await loadedRow();
    const choosing = userEvent.setup().selectOptions(actionSelect(0), "delete");
    await vi.waitFor(() => expect(document.getElementById("scan-confirm-overlay").hidden).toBe(false));
    expect(document.getElementById("scan-confirm-title").textContent)
      .toBe('Archive "Target"? It will be hidden from lookup and lists, but its history is kept.');
    await answerConfirm(false);
    await choosing;
  });
});

describe("save callbacks refresh the displayed set", () => {
  it("in search mode the refresh repeats the search", async () => {
    const target = itemFactory({ name: "Target" });
    await mountItems({ role: "admin", items: [target] });
    const user = userEvent.setup();
    await user.type(el.search(), "target{Enter}");
    await vi.waitFor(() => expect(rows()).toHaveLength(1));
    clearRequests();
    // notes.js setOnSaved(refreshDisplayedItems): drive a notes save through
    // its real button rather than reaching for the callback.
    server.use(http.patch(`/items/${target.id}/notes`, () => HttpResponse.json(target)));
    await user.selectOptions(actionSelect(0), "notes");
    await user.click(document.getElementById("notes-save-btn"));
    await vi.waitFor(() => expect(requestFor("/items/?q=target", "GET")).not.toBeNull());
  });

  it("in 'none' mode a save refreshes nothing", async () => {
    const target = itemFactory({ name: "Target" });
    const { mod } = await mountItems({ role: "admin", items: [target] });
    await userEvent.setup().click(el.loadAllBtn());
    await vi.waitFor(() => expect(rows()).toHaveLength(1));
    // Open the notes editor from a loaded row, THEN drop back to resultMode
    // "none" -- the editor keeps its item, so Save still fires, and the
    // refresh guard is the only reason no list request follows.
    await userEvent.setup().selectOptions(actionSelect(0), "notes");
    mod.loadItems();
    clearRequests();
    server.use(http.patch(`/items/${target.id}/notes`, () => HttpResponse.json(target)));
    await userEvent.setup().click(document.getElementById("notes-save-btn"));
    await vi.waitFor(() => expect(requestFor(`/items/${target.id}/notes`, "PATCH")).not.toBeNull());
    expect(requestFor("/items/", "GET")).toBeNull();
  });
});

async function fillCreate({ barcode = "NEW1", name = "New Thing", location = "A1", quantity = "4", price = "1.25", link = "" } = {}) {
  const user = userEvent.setup();
  if (barcode) await user.type(el.barcode(), barcode);
  if (name) await user.type(el.name(), name);
  if (location) await user.type(el.location(), location);
  await user.clear(el.quantity());
  if (quantity) await user.type(el.quantity(), quantity);
  if (price) await user.type(el.price(), price);
  if (link) await user.type(el.productLink(), link);
  return user;
}

describe("create item", () => {
  it("client checks: barcode+name first, then location; no request", async () => {
    await mountItems({ role: "admin" });
    const user = await fillCreate({ barcode: "", location: "" });
    await user.click(el.createBtn());
    expect(el.createMessage().textContent).toBe("Enter a barcode and an item name.");
    await user.type(el.barcode(), "B");
    await user.click(el.createBtn());
    expect(el.createMessage().textContent).toBe("Enter a location.");
    expect(requests()).toHaveLength(0);
  });

  it("posts the parsed payload with override_archived false, then clears the form", async () => {
    await mountItems({ role: "admin", handlers: [http.post("/items/", () => HttpResponse.json(itemFactory(), { status: 201 }))] });
    const user = await fillCreate({ link: "https://x.example/p" });
    await user.click(el.createBtn());
    await vi.waitFor(() => expect(el.createMessage().textContent).toBe("Item saved."));
    expect(el.createMessage().className).toBe("success");
    expect(requestFor("/items/", "POST").body).toEqual({
      barcode: "NEW1", name: "New Thing", location: "A1", quantity: 4, price: 1.25,
      product_link: "https://x.example/p", override_archived: false,
    });
    for (const f of [el.barcode, el.name, el.location, el.quantity, el.price, el.productLink]) expect(f().value).toBe("");
  });

  it("blank quantity/price post as 0 and a blank link as null", async () => {
    await mountItems({ role: "admin", handlers: [http.post("/items/", () => HttpResponse.json(itemFactory(), { status: 201 }))] });
    const user = await fillCreate({ quantity: "", price: "" });
    await user.click(el.createBtn());
    await vi.waitFor(() => expect(requestFor("/items/", "POST")).not.toBeNull());
    expect(requestFor("/items/", "POST").body).toMatchObject({ quantity: 0, price: 0, product_link: null });
  });

  it("409 → confirm → Yes re-posts with override_archived true", async () => {
    let posts = 0;
    await mountItems({ role: "admin", handlers: [http.post("/items/", () => {
      posts += 1;
      return posts === 1
        ? HttpResponse.json({ detail: "Barcode exists but is archived." }, { status: 409 })
        : HttpResponse.json(itemFactory(), { status: 201 });
    })] });
    const user = await fillCreate();
    const clicking = user.click(el.createBtn());
    await answerConfirm(true);
    await clicking;
    await vi.waitFor(() => expect(el.createMessage().textContent).toBe("Item saved."));
    const bodies = requests().filter((r) => r.method === "POST").map((r) => r.body.override_archived);
    expect(bodies).toEqual([false, true]);
  });

  it("409 → confirm → No: one post, message cleared, form kept", async () => {
    await mountItems({ role: "admin", handlers: [http.post("/items/", () =>
      HttpResponse.json({ detail: "archived" }, { status: 409 }))] });
    const user = await fillCreate();
    const clicking = user.click(el.createBtn());
    expect(document.getElementById("scan-confirm-title").textContent).toBe("");
    await answerConfirm(false);
    await clicking;
    expect(requests().filter((r) => r.method === "POST")).toHaveLength(1);
    expect(el.createMessage().textContent).toBe("");
    expect(el.barcode().value).toBe("NEW1");
  });

  it("the 409 confirm copy is the archived-reuse prompt", async () => {
    await mountItems({ role: "admin", handlers: [http.post("/items/", () =>
      HttpResponse.json({ detail: "archived" }, { status: 409 }))] });
    const user = await fillCreate();
    const clicking = user.click(el.createBtn());
    await vi.waitFor(() =>
      expect(document.getElementById("scan-confirm-title").textContent)
        .toBe("Barcode exists but is archived. Continue?"));
    await answerConfirm(false);
    await clicking;
  });

  it("any other failure shows friendlyError with the save fallback and keeps the form", async () => {
    await mountItems({ role: "admin", handlers: [http.post("/items/", () =>
      HttpResponse.json({ detail: "Barcode already exists." }, { status: 400 }))] });
    const user = await fillCreate();
    await user.click(el.createBtn());
    await vi.waitFor(() => expect(el.createMessage().className).toBe("error"));
    expect(el.createMessage().textContent).not.toBe("");
    expect(el.name().value).toBe("New Thing");
  });
});

describe("itemScanWidget (Add Item form)", () => {
  it("toggle reveals the controls; collapsing hides them again", async () => {
    await mountItems({ role: "admin" });
    const user = userEvent.setup();
    expect(el.itemScanControls().hidden).toBe(true);
    await user.click(el.itemScanToggle());
    expect(el.itemScanControls().hidden).toBe(false);
    await user.click(el.itemScanToggle());
    expect(el.itemScanControls().hidden).toBe(true);
  });

  it("a miss fills #barcode and collapses the controls; no create shortcut (allowCreate:false)", async () => {
    await mountItems({ role: "admin" });
    answerDecode(["ZZ9"]);
    answerLookup("ZZ9", 404);
    await userEvent.setup().click(el.itemScanToggle());
    await upload(el.itemScanInput());
    await vi.waitFor(() => expect(el.barcode().value).toBe("ZZ9"));
    expect(el.itemScanControls().hidden).toBe(true);
    expect(el.itemScanMessage().textContent).toBe("No item matches that barcode.");
    expect(el.itemScanChooser().querySelector(".scan-create-btn")).toBeNull();
    expect(el.itemScanChooser().hidden).toBe(true);
  });

  it("a hit warns with the owning item's name", async () => {
    await mountItems({ role: "admin" });
    answerDecode(["B1"]);
    answerLookup("B1", itemFactory({ name: "Existing", barcode: "B1" }));
    await upload(el.itemScanInput());
    await vi.waitFor(() => expect(el.itemScanMessage().textContent).toBe("Already in use by Existing."));
    expect(el.itemScanMessage().className).toBe("error");
    expect(el.barcode().value).toBe("");
  });
});

describe("itemsScanner (Find Item → Scan)", () => {
  it("a hit switches to Find, renders just that item in scan mode, fills the search box", async () => {
    await mountItems({ role: "technician" });
    const found = itemFactory({ name: "Found", barcode: "F1" });
    answerDecode(["F1"]);
    answerLookup("F1", found);
    await userEvent.setup().click(el.subNavBtn("scan"));
    expect(el.page().dataset.activeFeature).toBe("scan");
    await upload(el.itemsScanInput());
    await vi.waitFor(() => expect(rows()).toHaveLength(1));
    expect(el.page().dataset.activeFeature).toBe("find");
    expect(el.search().value).toBe("F1");
    expect(el.count().textContent).toBe("1 item found");
    expect(el.itemsScanMessage().textContent).toBe("Matched Found (F1).");
    expect(requestFor("/items/?q=")).toBeNull(); // rendered from the lookup, no list fetch
  });

  it("after a scan, a save-callback refresh repeats the barcode as q", async () => {
    // resultMode "scan" refreshes through loadItemResults({query: barcode}).
    const found = itemFactory({ name: "Found", barcode: "F1" });
    await mountItems({ role: "admin", items: [found] });
    answerDecode(["F1"]);
    answerLookup("F1", found);
    await upload(el.itemsScanInput());
    await vi.waitFor(() => expect(rows()).toHaveLength(1));
    clearRequests();
    server.use(http.delete(`/items/${found.id}`, () => new HttpResponse(null, { status: 204 })));
    const choosing = userEvent.setup().selectOptions(actionSelect(0), "delete");
    await answerConfirm(true);
    await choosing;
    await vi.waitFor(() => expect(requestFor("/items/?q=F1", "GET")).not.toBeNull());
  });

  it("404 for a technician: message only, no chooser", async () => {
    await mountItems({ role: "technician" });
    answerDecode(["N0"]);
    answerLookup("N0", 404);
    await upload(el.itemsScanInput());
    await vi.waitFor(() => expect(el.itemsScanMessage().textContent).toBe("No item matches that barcode."));
    expect(el.itemsScanChooser().hidden).toBe(true);
  });

  it("404 for techfm_oa+: Create and Add-barcode shortcuts; Create prefills #barcode and switches page", async () => {
    await mountItems({ role: "techfm_oa" });
    answerDecode(["N0"]);
    answerLookup("N0", 404);
    const navBtn = document.querySelector('.nav-btn[data-page="create-item"]');
    const navClicked = vi.fn();
    navBtn.addEventListener("click", navClicked);
    await upload(el.itemsScanInput());
    await vi.waitFor(() => expect(el.itemsScanChooser().hidden).toBe(false));
    const create = el.itemsScanChooser().querySelector(".scan-create-btn");
    const add = el.itemsScanChooser().querySelector(".scan-addbarcode-btn");
    expect(create.textContent).toBe("Create a new item for N0");
    expect(add.textContent).toBe("Add N0 to an existing item");
    await userEvent.setup().click(create);
    expect(el.barcode().value).toBe("N0");
    expect(navClicked).toHaveBeenCalledTimes(1);
    // nav.js is mounted here (the fixture primes the module graph through it),
    // so the click really routes: the create-item page becomes active.
    expect(document.getElementById("create-item-page").classList.contains("active")).toBe(true);
    expect(el.itemsScanChooser().hidden).toBe(true); // reset() after the shortcut
  });

  it("Add-barcode shortcut opens the add-barcode sub-flow for the code", async () => {
    await mountItems({ role: "admin" });
    answerDecode(["N0"]);
    answerLookup("N0", 404);
    await upload(el.itemsScanInput());
    await vi.waitFor(() => expect(el.itemsScanChooser().hidden).toBe(false));
    await userEvent.setup().click(el.itemsScanChooser().querySelector(".scan-addbarcode-btn"));
    expect(el.addBarcodeSection().hidden).toBe(false);
    expect(document.getElementById("add-barcode-scanned").textContent).toBe("Scanned code: N0");
  });

  it("a decode with no barcodes reports it and looks nothing up", async () => {
    await mountItems({ role: "admin" });
    answerDecode([]);
    await upload(el.itemsScanInput());
    await vi.waitFor(() => expect(el.itemsScanMessage().className).toBe("error"));
    expect(el.itemsScanMessage().textContent).toBe("Could not read that barcode. Move closer, hold steady, and try again.");
    expect(requestFor("/items/")).toBeNull();
  });

  it("multiple barcodes render a chooser; picking one resolves it", async () => {
    await mountItems({ role: "admin" });
    answerDecode(["A1", "A2"]);
    answerLookup("A2", itemFactory({ name: "Second", barcode: "A2" }));
    await upload(el.itemsScanInput());
    await vi.waitFor(() => expect(el.itemsScanChooser().querySelectorAll(".scan-choice-btn")).toHaveLength(2));
    await userEvent.setup().click(el.itemsScanChooser().querySelectorAll(".scan-choice-btn")[1]);
    await vi.waitFor(() => expect(rows()).toHaveLength(1));
    expect(rows()[0].textContent).toContain("Second");
  });
});

describe("Find/Scan sub-nav lifecycle", () => {
  it("switching feature closes every open sub-flow", async () => {
    await loadedRow("admin");
    const user = userEvent.setup();
    await user.selectOptions(actionSelect(0), "edit");
    expect(el.editorSection().hidden).toBe(false);
    await user.click(el.subNavBtn("scan"));
    expect(el.editorSection().hidden).toBe(true);
    expect(el.notesSection().hidden).toBe(true);
    expect(el.correctionSection().hidden).toBe(true);
    expect(el.addBarcodeSection().hidden).toBe(true);
  });
});
