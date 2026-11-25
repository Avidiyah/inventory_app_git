// The post-login notification prompt (views/pushPrompt.js): what it says for an
// undecided, a blocked and an iOS-in-a-tab device, who it skips, and how often.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { bootApp } from "../helpers/app.js";
import { restorePush, stubPush } from "../helpers/media.js";

const prompt = () => document.querySelector(".push-prompt");
const settle = () => new Promise((r) => setTimeout(r, 30));

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => {
  restorePush();
  vi.restoreAllMocks();
});

describe("post-login notification prompt", () => {
  it("undecided: asks, and the button requests permission", async () => {
    const push = stubPush({ permission: "default" });
    await bootApp({ role: "owner" });
    await vi.waitFor(() => expect(prompt()).not.toBeNull());
    expect(prompt().textContent).toContain("Get work-order alerts?");
    prompt().querySelector('[data-action="enable"]').click();
    expect(push.requestPermission).toHaveBeenCalledTimes(1);
    expect(prompt()).toBeNull();
  });

  it("Not now closes it and it stays away for the rest of the sign-in", async () => {
    const push = stubPush({ permission: "default" });
    await bootApp({ role: "owner" });
    await vi.waitFor(() => expect(prompt()).not.toBeNull());
    prompt().querySelector('[data-action="later"]').click();
    expect(prompt()).toBeNull();
    expect(push.requestPermission).not.toHaveBeenCalled();
    await bootApp({ role: "owner" });
    await settle();
    expect(prompt()).toBeNull();
  });

  it("blocked: explains how to re-enable, once per device", async () => {
    stubPush({ permission: "denied" });
    await bootApp({ role: "owner" });
    await vi.waitFor(() => expect(prompt()).not.toBeNull());
    expect(prompt().textContent).toContain("Notifications are blocked");
    expect(prompt().querySelector('[data-action="enable"]')).toBeNull();
    prompt().querySelector('[data-action="later"]').click();
    await bootApp({ role: "owner" });
    await settle();
    expect(prompt()).toBeNull();
  });

  it("iPhone in a Safari tab: says to add the app to the Home Screen", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)");
    await bootApp({ role: "owner" });
    await vi.waitFor(() => expect(prompt()).not.toBeNull());
    expect(prompt().textContent).toContain("Add to Home Screen");
  });

  it("says nothing when permission is granted, or on a browser with no push", async () => {
    stubPush({ permission: "granted" });
    await bootApp({ role: "owner" });
    await settle();
    expect(prompt()).toBeNull();
    restorePush();
    await bootApp({ role: "owner" }); // jsdom: no push support, not iOS
    await settle();
    expect(prompt()).toBeNull();
  });
});
