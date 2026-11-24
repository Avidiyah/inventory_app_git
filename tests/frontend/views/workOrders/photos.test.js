// The work-order Photos section (spec 2026-11-24 photo export): the strip
// loads on open, uploads go one file per request, and a 507 shows the
// server's message.

import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../../helpers/handlers.js";
import { workOrderDetail } from "../../helpers/factories.js";
import { setTestUser } from "../../helpers/session.js";
import { importView, mountShell } from "../../helpers/shell.js";

const settle = () => new Promise((r) => setTimeout(r, 20));
const PHOTOS = [
  { id: "p1", filename: "7001_2026-11-20_Commons_13_13G.jpg", taken_on: "2026-11-20" },
  { id: "p2", filename: "7001_2026-11-20_Commons_13_13G_1.jpg", taken_on: "2026-11-20" },
];

async function mount(detail, role = "owner") {
  await setTestUser({ role });
  mountShell();
  const mod = await importView("views/workOrderPhotos.js");
  const card = document.createElement("div");
  card.className = "wo-card";
  card.dataset.id = detail.id;
  card.innerHTML = `<div class="wo-body">${mod.photosSectionHtml(detail)}</div>`;
  document.getElementById("work-orders-list").appendChild(card);
  return { mod, section: card.querySelector(".wo-photos-section") };
}

describe("work-order Photos section", () => {
  it("shows the count in the title and loads the strip when opened", async () => {
    const detail = workOrderDetail({ photo_count: 2 });
    server.use(http.get(`/work-orders/${detail.id}/photos`, () => HttpResponse.json(PHOTOS)));
    const { section } = await mount(detail);
    expect(section.querySelector("summary").textContent).toBe("Photos · 2");
    expect(section.querySelectorAll(".wo-photo-thumb")).toHaveLength(0);
    section.open = true;
    section.dispatchEvent(new Event("toggle"));
    await settle();
    const thumbs = [...section.querySelectorAll(".wo-photo-thumb")];
    expect(thumbs.map((t) => t.getAttribute("src"))).toEqual([
      "/work-order-photos/p1/preview",
      "/work-order-photos/p2/preview",
    ]);
  });

  it("uploads each picked file in its own request, then reloads the strip", async () => {
    const detail = workOrderDetail({ photo_count: 0 });
    let uploads = 0;
    server.use(
      http.post(`/work-orders/${detail.id}/photos`, () => {
        uploads += 1;
        return HttpResponse.json([{ id: `n${uploads}`, taken_on: "2026-11-20", seq: 0 }], { status: 201 });
      }),
      http.get(`/work-orders/${detail.id}/photos`, () => HttpResponse.json(PHOTOS)),
    );
    const { mod, section } = await mount(detail);
    const files = [new File(["a"], "a.jpg", { type: "image/jpeg" }), new File(["b"], "b.jpg", { type: "image/jpeg" })];
    await mod.uploadPhotos(section, files);
    expect(uploads).toBe(2);
    expect(section.querySelector("[data-photos-msg]").textContent).toBe("2 photos added.");
    expect(section.querySelector("summary").textContent).toBe("Photos · 2");
  });

  it("shows the server's message when storage is full (507)", async () => {
    const detail = workOrderDetail({ photo_count: 0 });
    server.use(
      http.post(`/work-orders/${detail.id}/photos`, () =>
        HttpResponse.json({ detail: "Photo storage is full — export and clear first." }, { status: 507 })),
      http.get(`/work-orders/${detail.id}/photos`, () => HttpResponse.json([])),
    );
    const { mod, section } = await mount(detail);
    await mod.uploadPhotos(section, [new File(["a"], "a.jpg", { type: "image/jpeg" })]);
    expect(section.querySelector("[data-photos-msg]").textContent).toContain("Photo storage is full");
  });

  it("Take photo opens the camera input, Add photos the gallery input", async () => {
    const { section } = await mount(workOrderDetail({}));
    const camera = section.querySelector("#wo-photo-camera");
    const gallery = section.querySelector("#wo-photo-input");
    expect(camera.getAttribute("capture")).toBe("environment");
    expect(gallery.hasAttribute("capture")).toBe(false);
    expect(gallery.multiple).toBe(true);
    const opened = [];
    camera.click = () => opened.push("camera");
    gallery.click = () => opened.push("gallery");
    section.querySelector("#wo-photo-take").click();
    section.querySelector("#wo-photo-add").click();
    expect(opened).toEqual(["camera", "gallery"]);
  });

  it("hides Add photos from a Technician off the crew", async () => {
    const detail = workOrderDetail({ assigned_to_ids: ["someone-else"] });
    const { section } = await mount(detail, "technician");
    expect(section.querySelector(".wo-photo-input")).toBeNull();
  });
});
