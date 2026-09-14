// Characterization coverage for views/catalogueRequest.js: the pure prompt
// builder and the document-level form lifecycle it owns.
//
// Mounted directly (P7 deviation 4): the module imports only api.js and
// format.js, and its three hosts are already pinned where they render it --
// editorActions.test.js (`work_orders`), items.test.js (`find_item`),
// workOrders/requests.test.js (`request_card`). The prompt is injected into
// `#app-root`, the way every host does it through `innerHTML`.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { mountView } from "../helpers/shell.js";
import { requestFor, requests, startRecording, stopRecording } from "../helpers/requests.js";

afterEach(() => stopRecording());

const ENDPOINT = "/user-requests/catalogue-request";
const OPEN_COPY = "Can't find it? Request it for the catalogue";

async function mount(opts = { searchedText: "widget", source: "find_item" }) {
  const mod = await mountView("views/catalogueRequest.js");
  startRecording();
  const root = document.getElementById("app-root");
  root.hidden = false;
  root.innerHTML = mod.catalogueRequestPromptHtml(opts);
  return mod;
}

const prompt = () => document.querySelector(".catalogue-request");
const openBtn = () => prompt().querySelector(".catalogue-request-open");
const formEl = () => prompt().querySelector(".catalogue-request-form");
const text = () => prompt().querySelector(".catalogue-request-text");
const qty = () => prompt().querySelector(".catalogue-request-qty");
const note = () => prompt().querySelector(".catalogue-request-note");
const submit = () => prompt().querySelector(".catalogue-request-submit");
const cancel = () => prompt().querySelector(".catalogue-request-cancel");
const message = () => prompt().querySelector(".catalogue-request-message");

async function opened(opts) {
  const mod = await mount(opts);
  openBtn().click();
  return mod;
}

describe("catalogueRequestPromptHtml", () => {
  it("throws on a source no host is allowed to use", async () => {
    const mod = await mountView("views/catalogueRequest.js");
    expect(() => mod.catalogueRequestPromptHtml({ searchedText: "x", source: "bogus" }))
      .toThrow("catalogueRequestPromptHtml: unknown source bogus");
    expect(() => mod.catalogueRequestPromptHtml({ searchedText: "x" }))
      .toThrow("unknown source undefined");
  });

  it.each([[""], ["   "], [null], [undefined]])("renders nothing for a searched text of %j", async (searchedText) => {
    const mod = await mountView("views/catalogueRequest.js");
    expect(mod.catalogueRequestPromptHtml({ searchedText, source: "find_item" })).toBe("");
  });

  it.each([["work_orders"], ["find_item"], ["request_card"]])("accepts %s as the source", async (source) => {
    await mount({ searchedText: "widget", source });
    expect(prompt().dataset.source).toBe(source);
  });

  it("carries the trimmed text, the work order only when given, and the open button", async () => {
    await mount({ searchedText: "  widget  ", source: "work_orders", workOrderId: "wo-1" });
    expect(prompt().dataset.searchedText).toBe("widget");
    expect(prompt().dataset.workOrderId).toBe("wo-1");
    expect(prompt().children).toHaveLength(1);
    expect(openBtn().className).toBe("secondary-btn catalogue-request-open");
    expect(openBtn().type).toBe("button");
    expect(openBtn().textContent.trim()).toBe(OPEN_COPY);
    await mount({ searchedText: "widget", source: "find_item" });
    expect(prompt().hasAttribute("data-work-order-id")).toBe(false);
  });

  it("escapes the text into the attribute", async () => {
    const mod = await mount({ searchedText: `a<b>&"c"'d`, source: "find_item" });
    expect(prompt().dataset.searchedText).toBe(`a<b>&"c"'d`);
    expect(mod.catalogueRequestPromptHtml({ searchedText: `a<b>&"c"'d`, source: "find_item" }))
      .toContain('data-searched-text="a&lt;b&gt;&amp;&quot;c&quot;&#39;d"');
  });
});

describe("the form", () => {
  it("opens with the text prefilled, the quantity at 1 and the text focused", async () => {
    await opened({ searchedText: `Flux <b> "cap"`, source: "find_item" });
    expect(openBtn()).toBeNull();
    expect(formEl().querySelector(".hint").textContent).toBe("Send this to staff to add to the catalogue.");
    const labels = Array.from(formEl().querySelectorAll(".catalogue-request-label"), (l) => l.firstChild.textContent.trim());
    expect(labels).toEqual(["Item you searched for", "Quantity needed", "Note (optional)"]);
    expect(text().value).toBe(`Flux <b> "cap"`);
    expect(text().maxLength).toBe(200);
    expect(qty().value).toBe("1");
    expect(qty().getAttribute("min")).toBe("0.01");
    expect(qty().getAttribute("step")).toBe("any");
    expect(qty().getAttribute("inputmode")).toBe("decimal");
    expect(note().maxLength).toBe(500);
    expect(note().placeholder).toBe("e.g. sweat type, not press");
    expect(submit().textContent).toBe("Send request");
    expect(cancel().textContent).toBe("Cancel");
    expect(cancel().className).toBe("secondary-btn catalogue-request-cancel");
    expect(message().textContent).toBe("");
    expect(message().getAttribute("aria-live")).toBe("polite");
    expect(document.activeElement).toBe(text());
  });

  it("Cancel puts the open button back", async () => {
    await opened();
    text().value = "edited";
    cancel().click();
    expect(formEl()).toBeNull();
    expect(prompt().children).toHaveLength(1);
    expect(openBtn().textContent.trim()).toBe(OPEN_COPY);
    // Reopening starts from the searched text, not the edit.
    openBtn().click();
    expect(text().value).toBe("widget");
  });

  it("a click anywhere outside a prompt is ignored", async () => {
    await mount();
    const stray = document.createElement("button");
    stray.className = "catalogue-request-open";
    document.body.append(stray);
    stray.click();
    document.getElementById("app-root").click();
    expect(formEl()).toBeNull();
    expect(openBtn()).not.toBeNull();
  });
});

describe("submit", () => {
  it("refuses a blank description and focuses the text", async () => {
    await opened();
    text().value = "   ";
    submit().click();
    expect(message().textContent).toBe("Describe the item you need.");
    expect(message().className).toBe("catalogue-request-message error");
    expect(document.activeElement).toBe(text());
    expect(requests()).toEqual([]);
  });

  it.each([["0"], ["-1"], ["abc"]])("refuses a quantity of %s and focuses it", async (value) => {
    await opened();
    // DEFECT (N-P7-CHARACTERIZED): an `input[type=number]` hands "abc" back as
    // "", and Number("") is 0, so the `<= 0` half answers; `!isFinite` is dead.
    qty().value = value;
    submit().click();
    expect(message().textContent).toBe("Enter a quantity greater than zero.");
    expect(message().className).toBe("catalogue-request-message error");
    expect(document.activeElement).toBe(qty());
    expect(requests()).toEqual([]);
  });

  it("posts the trimmed fields with the source and work order, then replaces the prompt", async () => {
    server.use(http.post(ENDPOINT, () => HttpResponse.json({ id: "c1" })));
    await opened({ searchedText: "widget", source: "work_orders", workOrderId: "wo-1" });
    text().value = "  wide widget ";
    qty().value = "2.5";
    note().value = " sweat type ";
    const btn = submit();
    btn.click();
    expect(btn.disabled).toBe(true);
    expect(message().textContent).toBe("Sending…");
    expect(message().className).toBe("catalogue-request-message");
    await vi.waitFor(() => expect(prompt().querySelector(".catalogue-request-sent")).not.toBeNull());
    expect(requestFor(ENDPOINT, "POST").body).toEqual({
      searched_text: "wide widget", quantity: 2.5, note: "sweat type", work_order_id: "wo-1", source: "work_orders",
    });
    expect(prompt().innerHTML).toBe('<p class="catalogue-request-sent success">Catalogue request sent to staff.</p>');
    expect(prompt().dataset.searchedText).toBe("widget");
  });

  it("nulls a blank note and a missing work order", async () => {
    server.use(http.post(ENDPOINT, () => HttpResponse.json({ id: "c1" })));
    await opened({ searchedText: "widget", source: "request_card" });
    submit().click();
    await vi.waitFor(() => expect(requestFor(ENDPOINT, "POST")).not.toBeNull());
    expect(requestFor(ENDPOINT, "POST").body).toEqual({
      searched_text: "widget", quantity: 1, note: null, work_order_id: null, source: "request_card",
    });
  });

  it("a failure re-enables the button and shows the server's detail, keeping the form", async () => {
    server.use(http.post(ENDPOINT, () => HttpResponse.json({ detail: "Too many" }, { status: 500 })));
    await opened();
    const btn = submit();
    btn.click();
    await vi.waitFor(() => expect(message().textContent).toBe("Too many"));
    expect(message().className).toBe("catalogue-request-message error");
    expect(btn.disabled).toBe(false);
    expect(text().value).toBe("widget");
  });

  it("a failure without a detail falls back to the fixed copy", async () => {
    server.use(http.post(ENDPOINT, () => HttpResponse.json({ detail: "" }, { status: 500 })));
    await opened();
    submit().click();
    await vi.waitFor(() => expect(message().textContent).toBe("Could not send that request."));
  });

  it("a network failure reads as a signal problem", async () => {
    server.use(http.post(ENDPOINT, () => HttpResponse.error()));
    await opened();
    submit().click();
    await vi.waitFor(() =>
      expect(message().textContent).toBe("Could not reach the app. Check your signal and try again."));
    expect(submit().disabled).toBe(false);
  });
});
