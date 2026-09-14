// Characterization coverage for views/push.js: the eligibility gate and the
// whole subscription ladder in `initPushForUser`, the logout path in
// `unsubscribeThisDevice`, `resetPushView`, `requestPermissionAtLogin`, and the
// Owner's test button through the real message overlay.
//
// The browser side is stubbed at the BROWSER boundary by `stubPush`
// (helpers/media.js, P5b): `navigator.serviceWorker`, `window.PushManager` and
// `window.Notification` are the three `pushSupported()` checks, and jsdom has
// none of them -- so "unsupported" is this suite's default and the stub is what
// makes any push branch reachable at all. `views/push.js` itself is never
// mocked; the real `api.js` runs behind MSW.
//
// P5b's auth.test.js owns the LOGIN WIRING (the checkbox, the permission
// request landing before the login POST, logout calling unsubscribe first).
// This file owns the module's own branches.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { mountView } from "../helpers/shell.js";
import { setTestUser } from "../helpers/session.js";
import { restorePush, stubPush } from "../helpers/media.js";
import { clearRequests, requestFor, requests, startRecording, stopRecording } from "../helpers/requests.js";
import { answerConfirm, confirmOverlay, confirmTitle } from "../helpers/dialogs.js";

afterEach(() => {
  restorePush();
  stopRecording();
});

const testBtn = () => document.getElementById("push-test-btn");

// "QUJD" is base64url for the bytes of "ABC", which is the key `stubPush` mints
// an existing subscription against -- so a handler answering this key takes the
// "the key still matches" branch and one answering anything else rotates.
const CONFIG_KEY = "QUJD";

const configOk = (key = CONFIG_KEY) =>
  http.get("/push/config", () => HttpResponse.json({ public_key: key }));
const configFails = () =>
  http.get("/push/config", () => HttpResponse.json({ detail: "No VAPID key." }, { status: 500 }));
const subscribeOk = () =>
  http.post("/push/subscribe", () => new HttpResponse(null, { status: 204 }));
const unsubscribeOk = () =>
  http.post("/push/unsubscribe", () => new HttpResponse(null, { status: 204 }));

// `permission: "unsupported"` installs no stub at all -- the browser that
// cannot do push (a plain iOS Safari tab, and jsdom).
async function mountPush({ role = "owner", permission = "granted", subscription = null, handlers = [] } = {}) {
  if (handlers.length) server.use(...handlers);
  if (role) await setTestUser({ role });
  const push = permission === "unsupported" ? null : stubPush({ permission, subscription });
  startRecording();
  const mod = await mountView("views/push.js");
  clearRequests();
  return { mod, push };
}

describe("initPushForUser: the test button", () => {
  // An unsupported browser so the visibility decision is all that runs.
  it.each([
    ["technician", true],
    ["supervisor", true],
    ["techfm_oa", true],
    ["admin", true],
    ["owner", false],
  ])("%s: the button is hidden=%s, and nothing is requested", async (role, hidden) => {
    const { mod } = await mountPush({ role, permission: "unsupported" });
    await mod.initPushForUser();
    expect(testBtn().hidden).toBe(hidden);
    expect(requests()).toEqual([]);
  });

  it("hides the button again on a role that lost it", async () => {
    const { mod } = await mountPush({ role: "owner", permission: "unsupported" });
    await mod.initPushForUser();
    expect(testBtn().hidden).toBe(false);
    mod.resetPushView();
    expect(testBtn().hidden).toBe(true);
  });
});

describe("initPushForUser: the eligibility gate", () => {
  // SUBSCRIBE_MIN_ROLE is "technician", which is rank 0 -- the lowest role there
  // is -- so `roleAtLeast(role, SUBSCRIBE_MIN_ROLE)` is true for every real
  // role and the only way past this gate is to have no role at all. Filed under
  // N-P6-CHARACTERIZED: the constant reads like a floor and is one only in the
  // sense that it excludes a signed-out page.
  it("with no user at all: nothing is shown, nothing is registered, nothing is requested", async () => {
    const { mod, push } = await mountPush({ role: null, permission: "granted" });
    await mod.initPushForUser();
    expect(testBtn().hidden).toBe(true);
    expect(push.register).not.toHaveBeenCalled();
    expect(requests()).toEqual([]);
  });

  it("on an unsupported browser an owner still gets the button, but no subscription is attempted", async () => {
    const { mod } = await mountPush({ role: "owner", permission: "unsupported" });
    await mod.initPushForUser();
    expect(testBtn().hidden).toBe(false);
    expect(requests()).toEqual([]);
  });

  // Subscribing without permission would trigger the prompt on page load, and
  // iOS gives no second chance after a denial.
  it.each(["default", "denied"])("permission '%s': no registration and no request", async (permission) => {
    const { mod, push } = await mountPush({ role: "owner", permission });
    await mod.initPushForUser();
    expect(push.register).not.toHaveBeenCalled();
    expect(requests()).toEqual([]);
  });
});

describe("initPushForUser: the subscription ladder", () => {
  it("granted on a fresh device: registers at the app scope, reads the key, subscribes, posts", async () => {
    const { mod, push } = await mountPush({ role: "owner", handlers: [configOk(), subscribeOk()] });
    await mod.initPushForUser();

    // Registered at "/service-worker.js" so its scope is the whole app.
    expect(push.register).toHaveBeenCalledWith("/service-worker.js");
    expect(push.registration.pushManager.getSubscription).toHaveBeenCalled();
    expect(requestFor("/push/config", "GET")).not.toBeNull();

    const [options] = push.registration.pushManager.subscribe.mock.calls[0];
    expect(options.userVisibleOnly).toBe(true);
    expect(Array.from(options.applicationServerKey)).toEqual([65, 66, 67]);
    expect(requestFor("/push/subscribe", "POST").body).toEqual({
      endpoint: "https://push.example/new",
      keys: { p256dh: "p", auth: "a" },
    });
  });

  // vapidKeyToBytes is private; the bytes handed to subscribe() are its only
  // observable output. "-_8" needs one "=" of padding and carries both
  // URL-safe characters, so this one key pins all three transformations.
  it("decodes a base64url key that needs padding and carries both URL-safe characters", async () => {
    const { mod, push } = await mountPush({ role: "owner", handlers: [configOk("-_8"), subscribeOk()] });
    await mod.initPushForUser();
    const [{ applicationServerKey }] = push.registration.pushManager.subscribe.mock.calls[0];
    expect(Array.from(applicationServerKey)).toEqual([251, 255]);
  });

  // The re-POST is the shared-device fix: it reassigns the endpoint row to
  // whoever just logged in, so the previous account stops receiving here.
  it("an existing subscription on the same key is kept, not re-minted, and posted again", async () => {
    const { mod, push } = await mountPush({
      role: "owner",
      subscription: { endpoint: "https://push.example/dev1" },
      handlers: [configOk(), subscribeOk()],
    });
    await mod.initPushForUser();
    expect(push.unsubscribe).not.toHaveBeenCalled();
    expect(push.registration.pushManager.subscribe).not.toHaveBeenCalled();
    expect(requestFor("/push/subscribe", "POST").body.endpoint).toBe("https://push.example/dev1");
  });

  // A subscription minted against a rotated key can never be delivered to, and
  // subscribe() refuses to replace it -- dropping it here is what makes a key
  // rotation recoverable without the user clearing site data.
  it("an existing subscription on a different key is dropped first, then re-minted", async () => {
    const { mod, push } = await mountPush({
      role: "owner",
      subscription: {
        endpoint: "https://push.example/dev1",
        applicationServerKey: Uint8Array.from("XYZ", (c) => c.charCodeAt(0)),
      },
      handlers: [configOk(), subscribeOk()],
    });
    await mod.initPushForUser();
    const { subscribe } = push.registration.pushManager;
    expect(push.unsubscribe).toHaveBeenCalled();
    expect(subscribe).toHaveBeenCalled();
    expect(push.unsubscribe.mock.invocationCallOrder[0])
      .toBeLessThan(subscribe.mock.invocationCallOrder[0]);
    expect(requestFor("/push/subscribe", "POST")).not.toBeNull();
  });

  it("a 500 from /push/config is swallowed: no subscribe, no post, no throw", async () => {
    const { mod, push } = await mountPush({ role: "owner", handlers: [configFails()] });
    await expect(mod.initPushForUser()).resolves.toBeUndefined();
    expect(push.registration.pushManager.subscribe).not.toHaveBeenCalled();
    expect(requestFor("/push/subscribe")).toBeNull();
  });

  it("a rejecting subscribe() is swallowed: nothing is posted", async () => {
    const { mod, push } = await mountPush({ role: "owner", handlers: [configOk()] });
    push.registration.pushManager.subscribe.mockRejectedValueOnce(
      Object.assign(new Error("Registration failed"), { name: "NotAllowedError" }),
    );
    await expect(mod.initPushForUser()).resolves.toBeUndefined();
    expect(requestFor("/push/subscribe")).toBeNull();
  });
});

describe("unsubscribeThisDevice", () => {
  it("an unsupported browser: nothing at all", async () => {
    const { mod } = await mountPush({ role: "owner", permission: "unsupported" });
    await expect(mod.unsubscribeThisDevice()).resolves.toBeUndefined();
    expect(requests()).toEqual([]);
  });

  it("no registration: nothing", async () => {
    const { mod, push } = await mountPush({ role: "owner" });
    push.getRegistration.mockResolvedValueOnce(null);
    await mod.unsubscribeThisDevice();
    expect(push.registration.pushManager.getSubscription).not.toHaveBeenCalled();
    expect(requests()).toEqual([]);
  });

  it("no subscription on this device: nothing", async () => {
    const { mod, push } = await mountPush({ role: "owner" });
    await mod.unsubscribeThisDevice();
    expect(push.registration.pushManager.getSubscription).toHaveBeenCalled();
    expect(push.unsubscribe).not.toHaveBeenCalled();
    expect(requests()).toEqual([]);
  });

  it("posts the endpoint server-side FIRST, then drops the browser subscription", async () => {
    const order = [];
    const { mod, push } = await mountPush({
      role: "owner",
      subscription: { endpoint: "https://push.example/dev1" },
      handlers: [http.post("/push/unsubscribe", () => {
        order.push("server");
        return new HttpResponse(null, { status: 204 });
      })],
    });
    push.unsubscribe.mockImplementation(async () => { order.push("device"); return true; });

    await mod.unsubscribeThisDevice();
    expect(requestFor("/push/unsubscribe", "POST").body).toEqual({ endpoint: "https://push.example/dev1" });
    expect(order).toEqual(["server", "device"]);
  });

  // Server-side-first plus a swallowed failure means a 500 leaves the browser
  // subscription alive against a row the server may already have dropped --
  // the device keeps receiving, or keeps a dead endpoint, and the next login's
  // re-POST is the only thing that reconciles it. Filed.
  it("a 500 is swallowed AND the browser subscription is kept", async () => {
    const { mod, push } = await mountPush({
      role: "owner",
      subscription: { endpoint: "https://push.example/dev1" },
      handlers: [http.post("/push/unsubscribe", () =>
        HttpResponse.json({ detail: "nope" }, { status: 500 }))],
    });
    await expect(mod.unsubscribeThisDevice()).resolves.toBeUndefined();
    expect(push.unsubscribe).not.toHaveBeenCalled();
  });
});

describe("requestPermissionAtLogin", () => {
  it("permission 'default': prompts exactly once", async () => {
    const { mod, push } = await mountPush({ role: "owner", permission: "default" });
    await mod.requestPermissionAtLogin();
    expect(push.requestPermission).toHaveBeenCalledTimes(1);
    expect(requests()).toEqual([]);
  });

  it.each(["granted", "denied"])("permission '%s' is already decided: no prompt", async (permission) => {
    const { mod, push } = await mountPush({ role: "owner", permission });
    await mod.requestPermissionAtLogin();
    expect(push.requestPermission).not.toHaveBeenCalled();
  });

  it("an unsupported browser: no prompt, no throw", async () => {
    const { mod } = await mountPush({ role: "owner", permission: "unsupported" });
    await expect(mod.requestPermissionAtLogin()).resolves.toBeUndefined();
  });

  // A rejected prompt must not block the login click it is attached to.
  it("a rejecting prompt is swallowed", async () => {
    const { mod, push } = await mountPush({ role: "owner", permission: "default" });
    push.requestPermission.mockRejectedValueOnce(new TypeError("not allowed here"));
    await expect(mod.requestPermissionAtLogin()).resolves.toBeUndefined();
  });
});

describe("the Owner's test button", () => {
  const pushTest = (body, status = 200) =>
    http.post("/push/test", () => HttpResponse.json(body, { status }));

  // Unsupported, so revealing the button is all initPushForUser does here.
  async function ownerWithButton(handler) {
    const { mod } = await mountPush({ role: "owner", permission: "unsupported", handlers: [handler] });
    await mod.initPushForUser();
    expect(testBtn().hidden).toBe(false);
    return mod;
  }

  it("disables itself, sends, and reports the three counts through the real overlay", async () => {
    await ownerWithButton(pushTest({ sent: 3, dropped: 1, failed: 2 }));
    await userEvent.setup().click(testBtn());

    await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(false));
    expect(testBtn().disabled).toBe(true);
    expect(confirmTitle()).toBe("Sent to 3 device(s). 1 stale subscription(s) removed, 2 failed.");
    expect(requestFor("/push/test", "POST")).not.toBeNull();

    await answerConfirm(true);
    expect(testBtn().disabled).toBe(false);
  });

  it("a failed send shows friendlyError in the same overlay and re-enables the button", async () => {
    await ownerWithButton(pushTest({ detail: "Push send failed." }, 500));
    await userEvent.setup().click(testBtn());

    await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(false));
    expect(confirmTitle()).toBe("Push send failed.");
    await answerConfirm(true);
    expect(testBtn().disabled).toBe(false);
  });
});
