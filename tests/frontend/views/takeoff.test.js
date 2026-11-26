// views/takeoff.js: the Owner/Admin/TechFM OA Takeoff page. One row per item
// per service type; the Ordered control sets the row's on-the-way figure.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { mountView } from "../helpers/shell.js";
import { setTestUser } from "../helpers/session.js";
import { bootApp } from "../helpers/app.js";
import { clearRequests, requestFor, requests, startRecording, stopRecording } from "../helpers/requests.js";

afterEach(() => stopRecording());

const row = (o = {}) => ({
  item_id: "i1", item_name: "Toilet", product_link: "https://example.com/toilet",
  price: "120.00", need: "110.00", total: "13200.00", stock: "12.00", on_the_way: "0",
  shortfall: "98.00", shared: false, work_orders: [], ...o,
});
const group = (label, rows, total = "0") => ({
  service_type_key: label.toLowerCase(), service_type_label: label, total, rows,
});

const byId = (id) => document.getElementById(id);
const groups = () => Array.from(document.querySelectorAll(".tk-group"));
const rows = (g = document) => Array.from(g.querySelectorAll(".tk-row"));
const rowFor = (itemId, key) =>
  document.querySelector(`.tk-row[data-item-id="${itemId}"][data-key="${key}"]`);
const cell = (r, name) => r.querySelector(`.tk-${name}`).textContent.replace(/\s+/g, " ").trim();

async function mountTakeoff({ overview = { groups: [] }, handlers = [], role = "admin" } = {}) {
  server.use(...handlers, http.get("/takeoff/", () => HttpResponse.json(overview)));
  await setTestUser({ role });
  startRecording();
  const mod = await mountView("views/takeoff.js");
  await mod.loadTakeoff();
  clearRequests();
  return mod;
}

describe("loadTakeoff", () => {
  it("groups render in label order with row totals", async () => {
    await mountTakeoff({
      overview: {
        groups: [
          group("Plumbing", [row({ item_id: "i2", item_name: "Wax ring", price: "4.50", need: "4.00", total: "18.00", stock: "20.00", shortfall: "0" })], "18.00"),
          group("WMR", [row()], "13200.00"),
        ],
      },
    });
    expect(groups().map((g) => g.querySelector(".tk-group-title").textContent)).toEqual(["Plumbing", "WMR"]);
    expect(groups()[1].querySelector(".tk-group-total").textContent).toBe("$13,200.00 planned");
    const toilet = rows(groups()[1])[0];
    expect(cell(toilet, "need")).toContain("110");
    expect(cell(toilet, "price")).toContain("$120.00");
    expect(cell(toilet, "total")).toContain("$13,200.00");
    expect(cell(toilet, "stock")).toContain("12");
    expect(cell(toilet, "way")).toContain("—");
  });

  it("shared item shows the same shortfall on both rows", async () => {
    await mountTakeoff({
      overview: {
        groups: [
          group("Plumbing", [row({ shared: true, shortfall: "10.00" })]),
          group("WMR", [row({ shared: true, shortfall: "10.00" })]),
        ],
      },
    });
    const texts = rows().map((r) => r.querySelector(".tk-ordered").textContent.replace(/\s+/g, " "));
    expect(texts).toHaveLength(2);
    for (const t of texts) {
      expect(t).toContain("Order 10 more");
      expect(t).toContain("shared with other service types");
    }
  });

  it("blank product link renders plain text", async () => {
    await mountTakeoff({
      overview: {
        groups: [group("WMR", [row(), row({ item_id: "i2", item_name: "Wax ring", product_link: null })])],
      },
    });
    const [linked, plain] = rows();
    const a = linked.querySelector(".tk-item a");
    expect(a.getAttribute("href")).toBe("https://example.com/toilet");
    expect(a.getAttribute("target")).toBe("_blank");
    expect(a.getAttribute("rel")).toBe("noopener");
    expect(plain.querySelector(".tk-item a")).toBeNull();
    expect(plain.querySelector(".tk-item-name").textContent).toBe("Wax ring");
  });

  it("null price shows —", async () => {
    await mountTakeoff({
      overview: { groups: [group("WMR", [row({ price: null, total: null })])] },
    });
    const r = rows()[0];
    expect(cell(r, "price")).toContain("—");
    expect(cell(r, "total")).toContain("—");
  });

  it("empty state copy", async () => {
    await mountTakeoff();
    expect(byId("takeoff-message").textContent).toBe("No takeoff material on open work orders.");
    expect(groups()).toHaveLength(0);
  });

  it("covered rows say Ordered when stuff is on the way, else Covered by stock", async () => {
    await mountTakeoff({
      overview: {
        groups: [group("WMR", [
          row({ item_id: "a", shortfall: "0", on_the_way: "100.00" }),
          row({ item_id: "b", shortfall: "0", on_the_way: "0" }),
        ])],
      },
    });
    const [ordered, covered] = rows();
    expect(ordered.querySelector(".tk-ord").textContent).toContain("Ordered");
    expect(cell(ordered, "way")).toContain("100");
    expect(covered.querySelector(".tk-ord").textContent).toContain("Covered by stock");
  });

  it("shows a skeleton only when nothing is on screen yet", async () => {
    const mod = await mountTakeoff({ overview: { groups: [group("WMR", [row()])] } });
    const list = byId("takeoff-list");
    let pending = mod.loadTakeoff();
    expect(list.querySelector(".skel-list-item")).toBeNull();
    await pending;
    list.replaceChildren();
    pending = mod.loadTakeoff();
    expect(list.querySelector(".skel-list-item")).not.toBeNull();
    await pending;
    expect(list.querySelector(".skel-list-item")).toBeNull();
  });

  it("the work order count toggles the order links", async () => {
    await mountTakeoff({
      overview: {
        groups: [group("WMR", [row({ work_orders: [
          { id: "w1", number: "1042", quantity: "4.00" }, { id: "w2", number: "1043", quantity: "2.50" },
        ] })])],
      },
    });
    const r = rows()[0];
    const list = r.querySelector(".tk-wos");
    expect(list.hidden).toBe(true);
    const toggle = r.querySelector('[data-act="wos"]');
    expect(toggle.textContent).toBe("2 work orders");
    await userEvent.click(toggle);
    expect(list.hidden).toBe(false);
    expect(Array.from(list.querySelectorAll("button"), (b) => b.textContent)).toEqual(["WO 1042 ×4", "WO 1043 ×2.5"]);
  });
});

describe("the Ordered control", () => {
  it("tick sends on_the_way + entered and reloads", async () => {
    await mountTakeoff({
      overview: { groups: [group("WMR", [row({ on_the_way: "5.00", shortfall: "10.00" })])] },
    });
    const r = rows()[0];
    await userEvent.click(r.querySelector(".tk-ord"));
    const form = r.querySelector(".tk-form");
    expect(form.hidden).toBe(false);
    expect(form.textContent).toContain("How many did you order?");
    const input = form.querySelector("input");
    expect(input.value).toBe("10");
    await userEvent.clear(input);
    await userEvent.type(input, "12");
    server.use(http.put("/takeoff/purchases", () => new HttpResponse(null, { status: 204 })));
    await userEvent.click(form.querySelector('[data-act="save"]'));
    expect(requestFor("/takeoff/purchases", "PUT").body).toEqual({
      item_id: "i1", service_type_key: "wmr", service_type_label: "WMR", quantity: 17,
    });
    await vi.waitFor(() => expect(requests().filter((q) => q.url === "/takeoff/")).toHaveLength(1));
  });

  it("clear sends 0", async () => {
    await mountTakeoff({
      overview: { groups: [group("WMR", [row({ on_the_way: "100.00", shortfall: "0" })])] },
    });
    const r = rows()[0];
    await userEvent.click(r.querySelector(".tk-ord"));
    const form = r.querySelector(".tk-form");
    expect(form.textContent).toContain("On the way");
    expect(form.querySelector("input").value).toBe("100");
    server.use(http.put("/takeoff/purchases", () => new HttpResponse(null, { status: 204 })));
    await userEvent.click(form.querySelector('[data-act="clear"]'));
    expect(requestFor("/takeoff/purchases", "PUT").body.quantity).toBe(0);
  });

  const shortWithStockOnTheWay = () => ({
    groups: [group("WMR", [row({ on_the_way: "40.00", shortfall: "58.00" })])],
  });

  it("short row with stock on the way can edit it", async () => {
    await mountTakeoff({ overview: shortWithStockOnTheWay() });
    const r = rows()[0];
    await userEvent.click(r.querySelector('[data-act="edit-way"]'));
    const form = r.querySelector(".tk-form");
    expect(form.hidden).toBe(false);
    expect(form.textContent).toContain("On the way");
    expect(form.querySelector("input").value).toBe("40");
    await userEvent.clear(form.querySelector("input"));
    await userEvent.type(form.querySelector("input"), "30");
    server.use(http.put("/takeoff/purchases", () => new HttpResponse(null, { status: 204 })));
    await userEvent.click(form.querySelector('[data-act="save"]'));
    expect(requestFor("/takeoff/purchases", "PUT").body.quantity).toBe(30);
    await vi.waitFor(() => expect(requests().filter((q) => q.url === "/takeoff/")).toHaveLength(1));
  });

  it("short row with stock on the way can clear it", async () => {
    await mountTakeoff({ overview: shortWithStockOnTheWay() });
    const r = rows()[0];
    await userEvent.click(r.querySelector('[data-act="edit-way"]'));
    server.use(http.put("/takeoff/purchases", () => new HttpResponse(null, { status: 204 })));
    await userEvent.click(r.querySelector('.tk-form [data-act="clear"]'));
    expect(requestFor("/takeoff/purchases", "PUT").body.quantity).toBe(0);
  });

  it("the empty box still adds to what is on the way", async () => {
    await mountTakeoff({ overview: shortWithStockOnTheWay() });
    const r = rows()[0];
    await userEvent.click(r.querySelector(".tk-ord"));
    const form = r.querySelector(".tk-form");
    expect(form.textContent).toContain("How many did you order?");
    expect(form.querySelector("input").value).toBe("58");
    expect(form.querySelector('[data-act="clear"]').hidden).toBe(true);
  });

  it("an edited on-the-way figure is sent as entered", async () => {
    await mountTakeoff({
      overview: { groups: [group("WMR", [row({ on_the_way: "100.00", shortfall: "0" })])] },
    });
    const r = rows()[0];
    await userEvent.click(r.querySelector(".tk-ord"));
    const input = r.querySelector(".tk-form input");
    await userEvent.clear(input);
    await userEvent.type(input, "60");
    server.use(http.put("/takeoff/purchases", () => new HttpResponse(null, { status: 204 })));
    await userEvent.click(r.querySelector('.tk-form [data-act="save"]'));
    expect(requestFor("/takeoff/purchases", "PUT").body.quantity).toBe(60);
  });

  it("a failed save shows the error and keeps the form", async () => {
    await mountTakeoff({
      overview: { groups: [group("WMR", [row()])] },
    });
    const r = rows()[0];
    await userEvent.click(r.querySelector(".tk-ord"));
    server.use(http.put("/takeoff/purchases", () => HttpResponse.json({ detail: "Nope." }, { status: 400 })));
    await userEvent.click(r.querySelector('.tk-form [data-act="save"]'));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(byId("takeoff-message").className).toBe("error");
    expect(r.querySelector(".tk-form").hidden).toBe(false);
  });
});

describe("access", () => {
  it.each(["technician", "supervisor"])("%s cannot reach the page", async (role) => {
    await bootApp({ role });
    expect(document.querySelector('.nav-btn[data-page="takeoff"]').hidden).toBe(true);
  });

  it.each(["techfm_oa", "admin", "owner"])("%s sees the nav entry", async (role) => {
    await bootApp({ role });
    expect(document.querySelector('.nav-btn[data-page="takeoff"]').hidden).toBe(false);
  });
});
