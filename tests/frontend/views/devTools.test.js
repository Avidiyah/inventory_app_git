// The Owner's SMR27 switch on Dev Tools (views/devTools.js): it reflects
// `smr_enabled` from /auth/me, and flipping it shows or hides the SMR pages
// in the nav straight away.

import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { bootApp } from "../helpers/app.js";

const smrSwitch = () => document.getElementById("smr-switch");
const smrNavHidden = () => document.querySelector('.nav-btn[data-page="smr"]').hidden;

function flipTo(enabled) {
  smrSwitch().checked = enabled;
  smrSwitch().dispatchEvent(new Event("change", { bubbles: true }));
}

describe("the SMR27 switch", () => {
  it("starts off, and turning it on shows the SMR pages", async () => {
    const { requestsFor } = await bootApp({
      role: "owner",
      page: "dev-tools",
      handlers: [http.put("/feature-switches/smr", () => HttpResponse.json({ enabled: true }))],
    });
    expect(smrSwitch().checked).toBe(false);
    expect(smrNavHidden()).toBe(true);

    flipTo(true);
    await expect.poll(() => smrNavHidden()).toBe(false);
    expect(requestsFor("/feature-switches/smr", "PUT")).toHaveLength(1);
    expect(document.getElementById("smr-switch-message").textContent).toBe("SMR27 is on for everyone.");
  });

  it("turning it off hides them again", async () => {
    await bootApp({
      role: "owner",
      user: { smr_enabled: true },
      page: "dev-tools",
      handlers: [http.put("/feature-switches/smr", () => HttpResponse.json({ enabled: false }))],
    });
    expect(smrSwitch().checked).toBe(true);
    expect(smrNavHidden()).toBe(false);

    flipTo(false);
    await expect.poll(() => smrNavHidden()).toBe(true);
  });

  it("puts the box back when the server refuses", async () => {
    await bootApp({
      role: "owner",
      page: "dev-tools",
      handlers: [http.put("/feature-switches/smr", () => HttpResponse.json({ detail: "nope" }, { status: 500 }))],
    });
    flipTo(true);
    await expect.poll(() => document.getElementById("smr-switch-message").className).toBe("error");
    expect(smrSwitch().checked).toBe(false);
    expect(smrNavHidden()).toBe(true);
  });
});
