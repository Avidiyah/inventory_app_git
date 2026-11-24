// Integrations -> Image export (spec 2026-11-24 photo export).

import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { answerConfirm } from "../helpers/dialogs.js";
import { setTestUser } from "../helpers/session.js";
import { importView, mountShell } from "../helpers/shell.js";

const el = (id) => document.getElementById(id);
const settle = () => new Promise((r) => setTimeout(r, 20));
const storage = (o = {}) => ({
  used: 566231040, disk: 1073741824, ratio: 0.5273, warn: true, full: false,
  waiting_photos: 12, waiting_bytes: 1, exported_photos: 3, ...o,
});

async function load(role = "admin") {
  await setTestUser({ role });
  mountShell();
  const mod = await importView("views/imageExport.js");
  await mod.loadImageExport();
  return mod;
}

describe("Image export section", () => {
  it("renders the usage line and counts for an Admin", async () => {
    server.use(http.get("/work-order-photos/storage", () => HttpResponse.json(storage())));
    await load();
    expect(el("integrations-image-export").hidden).toBe(false);
    expect(el("image-export-usage").textContent).toBe("Database 540 MB of 1 GB (53%) · 12 photos waiting");
    expect(el("image-export-download-btn").textContent).toBe("Download photos (15)");
    expect(el("image-export-clear-btn").textContent).toBe("Clear exported (3)");
  });

  it("disables both buttons at zero", async () => {
    server.use(http.get("/work-order-photos/storage", () =>
      HttpResponse.json(storage({ waiting_photos: 0, exported_photos: 0 }))));
    await load();
    expect(el("image-export-download-btn").disabled).toBe(true);
    expect(el("image-export-clear-btn").disabled).toBe(true);
  });

  it("stays hidden below Admin", async () => {
    await load("techfm_oa");
    expect(el("integrations-image-export").hidden).toBe(true);
  });

  it("asks before clearing; No sends nothing, Yes posts and refreshes", async () => {
    let posts = 0;
    server.use(
      http.get("/work-order-photos/storage", () => HttpResponse.json(storage())),
      http.post("/work-order-photos/clear-exported", () => {
        posts += 1;
        return HttpResponse.json({ deleted: 3, storage: storage({ exported_photos: 0, ratio: 0.4 }) });
      }),
    );
    await load();
    el("image-export-clear-btn").click();
    await answerConfirm(false);
    await settle();
    expect(posts).toBe(0);
    el("image-export-clear-btn").click();
    await answerConfirm(true);
    await settle();
    expect(posts).toBe(1);
    expect(el("image-export-clear-btn").textContent).toBe("Clear exported (0)");
    expect(el("image-export-message").textContent).toBe("Cleared 3 photos.");
  });
});
