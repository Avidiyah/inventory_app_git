// Characterization for views/clockInPrompt.js: the post-login "You have not
// clocked in" modal.

import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { bootApp } from "../helpers/app.js";
import { attendanceMe } from "../helpers/factories.js";

const prompt = () => document.querySelector(".clock-in-prompt");
const settle = () => new Promise((r) => setTimeout(r, 20));

describe("the clock-in prompt", () => {
  it("appears for someone off the clock, and Continue dismisses it", async () => {
    await bootApp({ role: "technician" });
    await settle();
    expect(prompt().textContent).toContain("You have not clocked in");
    document.querySelector('[data-action="skip"]').click();
    expect(prompt()).toBeNull();
  });

  it("Clock in punches in and closes", async () => {
    let punched = false;
    server.use(http.post("/attendance/punch-in", () => {
      punched = true;
      return HttpResponse.json({ id: "00000000-0000-0000-0000-000000000001", started_at: "2026-09-10T12:00:00Z", start_source: "self", needs_review: false });
    }));
    await bootApp({ role: "technician" });
    await settle();
    document.querySelector('[data-action="clock-in"]').click();
    await settle();
    expect(punched).toBe(true);
    expect(prompt()).toBeNull();
  });

  it("stays away when already clocked in", async () => {
    const clockedIn = attendanceMe({ open_punch: { started_at: "2026-09-10T08:00:00Z", stale: false } });
    await bootApp({ role: "technician", handlers: [http.get("/attendance/me", () => HttpResponse.json(clockedIn))] });
    await settle();
    expect(prompt()).toBeNull();
  });

  it("is skipped for the Owner", async () => {
    await bootApp({ role: "owner" });
    await settle();
    expect(prompt()).toBeNull();
  });
});
