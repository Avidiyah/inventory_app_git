// Characterization coverage for `backend/static/views/auth.js`.
//
// Assertions state what the code does today, not what it ought to do. Where a
// branch reads as a defect the comment says so and the row is filed in
// `docs/open-work.md` under N-P5-CHARACTERIZED -- the test still pins the
// current behaviour, so a fix has to come with a deliberate edit here.
//
// Nothing is mocked. The fixture (`helpers/auth.js`) mounts the real module
// against the real shell; MSW answers `fetch` and a scriptable class answers
// `new WebSocket`.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import {
  answerLogin, answerLogout, el, mountAuth, requestFor, requests, restoreAuth,
  savedBatch, seedBatch, signedIn,
} from "../helpers/auth.js";
import { user as userFactory, workOrderCard, workOrderDetail } from "../helpers/factories.js";
import { stubPush } from "../helpers/media.js";
import { restoreBrowserStubs, stubScroll } from "../helpers/browserStubs.js";

afterEach(() => restoreAuth());

describe("mountAuth", () => {
  it("mounts auth.js against the real login markup without booting", async () => {
    const { mod } = await mountAuth();
    expect(typeof mod.initAuth).toBe("function");
    expect(el.screen().hidden).toBe(true);
    expect(el.root().hidden).toBe(true);
  });

  it("signedIn reveals the app on a technician's landing page", async () => {
    const { ws } = await signedIn({ role: "technician" });
    expect(el.root().hidden).toBe(false);
    expect(el.page("user-hub").classList.contains("active")).toBe(true);
    expect(ws.sockets).toHaveLength(1);
  });
});

describe("initAuth — a valid session", () => {
  it.each([
    ["technician", ["saved-users", "history", "create-item"]],
    ["supervisor", ["create-item", "low-stock"]],
    ["techfm_oa", []],
    ["admin", []],
    ["owner", []],
  ])("%s: reveals the app, names the user, hides %j", async (role, hiddenPages) => {
    const { user } = await signedIn({ role, full_name: "Pat Example" });
    expect(el.screen().hidden).toBe(true);
    expect(el.root().hidden).toBe(false);
    expect(el.indicator().querySelector(".user-hub-name").textContent).toBe("Pat Example");
    expect(el.indicator().getAttribute("aria-label")).toContain("Pat Example");
    for (const page of hiddenPages) {
      expect(document.querySelector(`.nav-btn[data-page="${page}"]`).hidden).toBe(true);
    }
    // Every role lands on the hub (LANDING_PAGE_BY_ROLE maps all five to it);
    // the role only changes what the nav offers from there.
    expect(el.page("user-hub").classList.contains("active")).toBe(true);
    expect(user.role).toBe(role);
  });

  it("role label on the indicator comes from roles.js", async () => {
    await signedIn({ role: "techfm_oa" });
    expect(el.indicator().querySelector(".user-hub-role").textContent).toBe("TechFM OA");
  });

  it("supervisor+ primes the user list", async () => {
    // signedIn() clears requests() after boot, so drive initAuth by hand.
    const { mod, ws } = await mountAuth({ me: userFactory({ role: "supervisor" }) });
    await mod.initAuth();
    expect(requestFor("/users/", "GET")).not.toBeNull();
    expect(ws.sockets).toHaveLength(1);
  });

  it("a technician fires no /users/ load", async () => {
    const { mod } = await mountAuth({ me: userFactory({ role: "technician" }) });
    await mod.initAuth();
    expect(requestFor("/users/")).toBeNull();
  });

  it("setHistoryTab('all') on a fresh mount is a no-op: no transactions request", async () => {
    // history.html pre-marks the All tab active, and subnav.showFeature returns
    // early when the feature is unchanged. Characterization: the "primed" comment
    // in enterApp describes a load that does not happen on first boot.
    const { mod } = await mountAuth({ me: userFactory({ role: "admin" }) });
    await mod.initAuth();
    expect(requestFor("/transactions")).toBeNull();
  });
});

describe("initAuth — no session", () => {
  it("401 shows the login screen silently and runs no page loader", async () => {
    const { mod, ws } = await mountAuth({ me: 401 });
    await mod.initAuth();
    expect(el.screen().hidden).toBe(false);
    expect(el.root().hidden).toBe(true);
    expect(el.message().textContent).toBe("");
    expect(requestFor("/hub")).toBeNull();
    expect(ws.sockets).toHaveLength(0);
    expect(document.activeElement).toBe(el.username());
  });

  it("a network failure also lands on the login screen, silently", async () => {
    const { mod } = await mountAuth({
      handlers: [http.get("/auth/me", () => HttpResponse.error())],
    });
    await mod.initAuth();
    expect(el.screen().hidden).toBe(false);
    expect(el.message().textContent).toBe("");
  });

  it("boot 401 discards a saved batch snapshot", async () => {
    // The api.js 401 hook fires showLoginScreen({expired:true}) BEFORE initAuth's
    // catch calls showLoginScreen() again. keepSaved is true on the first call and
    // false on the second -- so the snapshot the first call deliberately preserved
    // is cleared a moment later. Characterization; filed under N-P5-CHARACTERIZED.
    seedBatch({ userId: 1, workOrder: { id: "w1", number: "1" } });
    const { mod } = await mountAuth({ me: 401 });
    await mod.initAuth();
    expect(savedBatch()).toBeNull();
  });
});

describe("login form wiring", () => {
  it("password toggle flips type, label and aria-pressed", async () => {
    await mountAuth();
    const user = userEvent.setup();
    await user.click(el.toggle());
    expect(el.password().type).toBe("text");
    expect(el.toggle().textContent).toBe("Hide");
    expect(el.toggle().getAttribute("aria-pressed")).toBe("true");
    await user.click(el.toggle());
    expect(el.password().type).toBe("password");
    expect(el.toggle().getAttribute("aria-label")).toBe("Show password");
  });

  it("Enter in either field submits", async () => {
    await mountAuth();
    const user = userEvent.setup();
    await user.type(el.username(), "{Enter}");
    expect(el.message().textContent).toBe("Enter a username and password.");
    expect(el.message().className).toBe("error");
    expect(requestFor("/auth/login")).toBeNull();
  });
});

async function fillAndSubmit({ username = "pat", password = "pw", remember = false } = {}) {
  const user = userEvent.setup();
  await user.type(el.username(), username);
  await user.type(el.password(), password);
  if (remember) await user.click(el.remember());
  await user.click(el.btn());
  return user;
}

describe("login submit", () => {
  it("posts username, password and remember, then enters the app", async () => {
    const { ws } = await mountAuth({ me: 401 });
    const current = userFactory({ role: "supervisor" });
    answerLogin(current);
    await fillAndSubmit({ remember: true });
    await vi.waitFor(() => expect(el.root().hidden).toBe(false));
    expect(requestFor("/auth/login", "POST").body).toEqual({ username: "pat", password: "pw", remember: true });
    expect(el.username().value).toBe("");
    expect(el.password().value).toBe("");
    expect(el.screen().hidden).toBe(true);
    expect(el.page("user-hub").classList.contains("active")).toBe(true);
    expect(document.querySelector('.nav-btn[data-page="create-item"]').hidden).toBe(true);
    expect(ws.sockets).toHaveLength(1);
    const state = await import("../../../backend/static/state.js");
    expect(state.getCurrentUser()).toEqual(current);
  });

  it("remember defaults to false", async () => {
    await mountAuth({ me: 401 });
    answerLogin(userFactory());
    await fillAndSubmit();
    await vi.waitFor(() => expect(el.root().hidden).toBe(false));
    expect(requestFor("/auth/login", "POST").body.remember).toBe(false);
  });

  it("username is trimmed; a blank one short-circuits before any request", async () => {
    await mountAuth({ me: 401 });
    await fillAndSubmit({ username: "   " });
    expect(el.message().textContent).toBe("Enter a username and password.");
    expect(requestFor("/auth/login")).toBeNull();
  });

  it("401: credential copy, app stays hidden, password cleared, toggle re-masked", async () => {
    await mountAuth({ me: 401 });
    answerLogin(401);
    const user = userEvent.setup();
    await user.click(el.toggle()); // reveal, so the reset is observable
    await fillAndSubmit();
    await vi.waitFor(() =>
      expect(el.message().textContent).toBe("That sign-in did not work. Check the username and password, then try again."));
    expect(el.message().className).toBe("error");
    expect(el.root().hidden).toBe(true);
    expect(el.password().value).toBe("");
    expect(el.password().type).toBe("password");
    expect(el.toggle().textContent).toBe("Show");
    // The 401 hook ran showLoginScreen({expired:true}) with the app hidden, so
    // no timeout copy -- the catch's credential copy is what stands.
  });

  it("a bad-password attempt keeps a saved batch snapshot (401 hook -> keepSaved:true)", async () => {
    seedBatch({ userId: 7, workOrder: { id: "w1", number: "1" } });
    await mountAuth({ me: 401 });
    // initAuth NOT called: the boot 401's second showLoginScreen() would clear it.
    answerLogin(401);
    await fillAndSubmit();
    await vi.waitFor(() => expect(el.message().className).toBe("error"));
    expect(savedBatch()).not.toBeNull();
  });

  it("429 shows the server's detail verbatim", async () => {
    await mountAuth({ me: 401 });
    answerLogin(429, { detail: "Too many attempts. Try again in 42 seconds." });
    await fillAndSubmit();
    await vi.waitFor(() =>
      expect(el.message().textContent).toBe("Too many attempts. Try again in 42 seconds."));
    expect(el.root().hidden).toBe(true);
  });

  it("any other failure shows friendlyError with the sign-in fallback", async () => {
    await mountAuth({ me: 401 });
    answerLogin(500, { detail: "" });
    await fillAndSubmit();
    await vi.waitFor(() => expect(el.message().textContent).toBe("Sign in failed."));
    expect(el.message().className).toBe("error");
    expect(el.root().hidden).toBe(true);
  });

  it("a network failure shows the unreachable copy", async () => {
    await mountAuth({ me: 401, handlers: [http.post("/auth/login", () => HttpResponse.error())] });
    await fillAndSubmit();
    await vi.waitFor(() =>
      expect(el.message().textContent).toBe("Could not reach the app. Check your signal and try again."));
  });
});

const TIMEOUT_COPY = "Your session timed out — any scans you already saved are safe in the work order's history. Sign in to pick up where you left off.";

describe("session expiry — a 401 while signed in", () => {
  it("shows the timeout copy, disconnects realtime, keeps the batch snapshot", async () => {
    const { ws, user } = await signedIn({ role: "supervisor" });
    seedBatch({ userId: user.id, workOrder: { id: "w1", number: "1" } });
    server.use(http.get("/users/", () => HttpResponse.json({ detail: "expired" }, { status: 401 })));
    const api = await import("../../../backend/static/api.js");
    await expect(api.apiListUsers()).rejects.toMatchObject({ status: 401 });

    expect(el.screen().hidden).toBe(false);
    expect(el.root().hidden).toBe(true);
    expect(el.message().textContent).toBe(TIMEOUT_COPY);
    expect(el.message().className).toBe("");
    expect(ws.last().closed).not.toBeNull();
    expect(savedBatch()).not.toBeNull();
    const state = await import("../../../backend/static/state.js");
    expect(state.getCurrentUser()).toBeNull();
    expect(document.activeElement).toBe(el.username());
  });

  it("a second 401 while already on the login screen clears the reassurance", async () => {
    await signedIn({ role: "admin" });
    server.use(http.get("/users/", () => HttpResponse.json({ detail: "expired" }, { status: 401 })));
    const api = await import("../../../backend/static/api.js");
    await expect(api.apiListUsers()).rejects.toMatchObject({ status: 401 });
    expect(el.message().textContent).toBe(TIMEOUT_COPY);
    await expect(api.apiListUsers()).rejects.toMatchObject({ status: 401 });
    // `wasInApp` is false on the second pass (appRoot is already hidden), so the
    // else branch clears the copy. The handler's "this is idempotent if already
    // showing" comment does not hold for the message: the reassurance vanishes
    // when two requests expire together. Filed under N-P5-CHARACTERIZED.
    expect(el.message().textContent).toBe("");
  });

  it("the boot-time 401 is silent (asymmetry with the in-app 401)", async () => {
    const { mod } = await mountAuth({ me: 401 });
    await mod.initAuth();
    expect(el.message().textContent).toBe("");
  });
});

describe("logout", () => {
  it("unsubscribes push first, posts /auth/logout, clears the batch, resets tools and push, disconnects", async () => {
    const push = stubPush({ permission: "granted", subscription: { endpoint: "https://push.example/dev1" } });
    server.use(
      http.get("/push/config", () => HttpResponse.json({ public_key: "QUJD" })),
      http.post("/push/subscribe", () => new HttpResponse(null, { status: 204 })),
      http.post("/push/unsubscribe", () => new HttpResponse(null, { status: 204 })),
    );
    const { ws, user } = await signedIn({ role: "owner" });
    seedBatch({ userId: user.id, workOrder: { id: "w1", number: "1" } });
    answerLogout(204);
    const testBtn = document.getElementById("push-test-btn");
    await vi.waitFor(() => expect(testBtn.hidden).toBe(false)); // owner only, after initPushForUser

    await userEvent.setup().click(el.logout());
    await vi.waitFor(() => expect(el.screen().hidden).toBe(false));

    const order = requests().map((r) => `${r.method} ${r.url}`);
    expect(order.indexOf("POST /push/unsubscribe")).toBeGreaterThan(-1);
    expect(order.indexOf("POST /push/unsubscribe")).toBeLessThan(order.indexOf("POST /auth/logout"));
    expect(requestFor("/push/unsubscribe", "POST").body).toEqual({ endpoint: "https://push.example/dev1" });
    expect(push.unsubscribe).toHaveBeenCalledTimes(1);
    expect(savedBatch()).toBeNull();
    expect(testBtn.hidden).toBe(true);
    expect(ws.last().closed).not.toBeNull();
    expect(el.message().textContent).toBe("");
    expect(el.root().hidden).toBe(true);
  });

  it("a failing /auth/logout still lands on the login screen", async () => {
    await signedIn({ role: "technician" });
    answerLogout(500);
    await userEvent.setup().click(el.logout());
    await vi.waitFor(() => expect(el.screen().hidden).toBe(false));
    expect(el.root().hidden).toBe(true);
  });

  it("with push unsupported, logout makes no push request", async () => {
    await signedIn({ role: "technician" });
    answerLogout(204);
    await userEvent.setup().click(el.logout());
    await vi.waitFor(() => expect(el.screen().hidden).toBe(false));
    expect(requestFor("/push/")).toBeNull();
  });
});

// The five answers a deep link consumes: the number search that resolves the
// id, the card detail, its requests strip, and the reference lists
// `ensureReferenceData` primes. Ordered so `/work-orders/` and
// `/work-orders/:id/requests` are matched before the bare `:id`.
function answerWorkOrder(detail) {
  return [
    http.get("/work-orders/", ({ request }) => {
      const q = new URL(request.url).searchParams.get("q");
      return HttpResponse.json(q === detail.number ? [workOrderCard({ id: detail.id, number: detail.number })] : []);
    }),
    http.get("/work-orders/:id/requests", () => HttpResponse.json([])),
    http.get("/work-orders/:id", ({ params }) =>
      params.id === detail.id ? HttpResponse.json(detail) : HttpResponse.json({ detail: "Not found" }, { status: 404 })),
    http.get("/items/", () => HttpResponse.json([])),
    http.get("/users/", () => HttpResponse.json([])),
  ];
}

describe("deep link /workorder_card/<n>", () => {
  // `openWorkOrderPage` restores scroll through `window.scrollTo`, which jsdom
  // logs as not implemented.
  afterEach(() => restoreBrowserStubs());

  it("a signed-in session lands on the card page, not the landing page", async () => {
    stubScroll();
    const detail = workOrderDetail({ number: "4242" });
    window.history.replaceState({}, "", "/workorder_card/4242");
    const { mod } = await mountAuth({ me: userFactory({ role: "technician" }), handlers: answerWorkOrder(detail) });
    await mod.initAuth();
    expect(el.page("work-orders").classList.contains("active")).toBe(true);
    expect(el.page("user-hub").classList.contains("active")).toBe(false);
    await vi.waitFor(() =>
      expect(document.querySelector("#work-orders-list .wo-card")?.dataset.id).toBe(detail.id));
    expect(requestFor("/work-orders/?q=4242", "GET")).not.toBeNull();
  });

  it("a resumed batch wins over the deep link", async () => {
    stubScroll();
    const detail = workOrderDetail({ number: "4242", status: "in_progress" });
    window.history.replaceState({}, "", "/workorder_card/4242");
    const current = userFactory({ role: "technician" });
    seedBatch({ userId: current.id, workOrder: { id: detail.id, number: detail.number, status: "in_progress" } });
    const { mod } = await mountAuth({ me: current, handlers: answerWorkOrder(detail) });
    await mod.initAuth();
    expect(el.page("transaction").classList.contains("active")).toBe(true);
    expect(requestFor("/work-orders/?q=")).toBeNull();
  });

  it("every role can reach work-orders, so the drop-the-URL branch is unreachable today", async () => {
    // enterApp's `else if (deepLinkNumber !== null)` -> history.replaceState("/")
    // needs a role with no work-orders access. PAGE_ACCESS grants all five, so
    // the branch cannot be entered without a production change. Asserted here so
    // the claim goes red the day that map changes.
    const nav = await import("../../../backend/static/views/nav.js");
    for (const role of ["owner", "admin", "techfm_oa", "supervisor", "technician"]) {
      expect(nav.canAccessPage(role, "work-orders")).toBe(true);
    }
  });
});

describe("resuming a held work-order editor after a session expiry", () => {
  afterEach(() => restoreBrowserStubs());

  it("captures the held section on 401 and reopens it, refilled, after re-login", async () => {
    stubScroll();
    const detail = workOrderDetail({
      number: "4242",
      assigned_to_ids: ["t1"],
      assigned_to_names: ["Ada L"],
    });
    window.history.replaceState({}, "", "/workorder_card/4242");
    const current = userFactory({ role: "supervisor" });
    const { mod } = await mountAuth({ me: current, handlers: answerWorkOrder(detail) });
    await mod.initAuth();
    await vi.waitFor(() =>
      expect(document.querySelector(".wo-labor-section")).not.toBeNull());

    // The operator had the labor editor open, typed an hours entry, and the
    // save had already failed once (workOrderActions.js's saveDraft) by the
    // time the session actually timed out -- this is that draft.
    const drafts = await import("../../../backend/static/workOrderDrafts.js");
    drafts.saveDraft(detail.id, "labor", {
      number: detail.number,
      action: "add-labor",
      payload: { technicianId: "t1", minutes: 90 },
    });
    document.querySelector(".wo-labor-section").open = true;

    server.use(http.get("/users/", () => HttpResponse.json({ detail: "expired" }, { status: 401 })));
    const api = await import("../../../backend/static/api.js");
    await expect(api.apiListUsers()).rejects.toMatchObject({ status: 401 });
    expect(el.screen().hidden).toBe(false);
    expect(JSON.parse(localStorage.getItem("wo-draft-resume"))).toEqual({
      workOrderId: detail.id,
      number: detail.number,
      section: "labor",
    });

    server.use(...answerWorkOrder(detail));
    answerLogin(current);
    await fillAndSubmit();
    await vi.waitFor(() => expect(el.root().hidden).toBe(false));

    await vi.waitFor(() =>
      expect(document.querySelector("#work-orders-list .wo-card")?.dataset.id).toBe(detail.id));
    await vi.waitFor(() =>
      expect(document.querySelector(".wo-labor-section")?.open).toBe(true));
    expect(document.querySelector(".wo-new-labor-hours").value).toBe("1.5");
    // One-shot: consumed on the open it was waiting for, not left to fire on
    // some unrelated later card.
    expect(localStorage.getItem("wo-draft-resume")).toBeNull();
  });

  it("a deliberate logout does not capture a resume", async () => {
    stubScroll();
    const detail = workOrderDetail({ number: "4242" });
    window.history.replaceState({}, "", "/workorder_card/4242");
    const { mod } = await mountAuth({
      me: userFactory({ role: "technician" }),
      handlers: answerWorkOrder(detail),
    });
    await mod.initAuth();
    await vi.waitFor(() =>
      expect(document.querySelector(".wo-notes-section")).not.toBeNull());
    document.querySelector(".wo-notes-section").open = true;

    answerLogout(204);
    await userEvent.setup().click(el.logout());
    await vi.waitFor(() => expect(el.screen().hidden).toBe(false));
    expect(localStorage.getItem("wo-draft-resume")).toBeNull();
  });
});

describe("batch resume at sign-in", () => {
  const wo = { id: "00000000-0000-4000-8000-000000000042", number: "4242", status: "in_progress" };

  it("the owning user resumes on Transaction regardless of role", async () => {
    const current = userFactory({ role: "admin" });
    seedBatch({ userId: current.id, workOrder: wo });
    const { mod } = await mountAuth({
      me: current,
      handlers: [http.get("/work-orders/:id", () => HttpResponse.json(workOrderDetail({ ...wo })))],
    });
    await mod.initAuth();
    expect(el.page("transaction").classList.contains("active")).toBe(true);
    expect(savedBatch()).not.toBeNull();
    expect(document.getElementById("scango-wo-label").textContent).toBe("Work order: 4242");
  });

  it("a different user does not resume, and the snapshot is discarded", async () => {
    seedBatch({ userId: 999999, workOrder: wo });
    const { mod } = await mountAuth({ me: userFactory({ role: "admin" }) });
    await mod.initAuth();
    expect(el.page("user-hub").classList.contains("active")).toBe(true);
    expect(requestFor("/work-orders/")).toBeNull();
    expect(savedBatch()).toBeNull(); // resetBatch() default keepSaved:false
  });

  it("a stale work order clears the snapshot, but the explanation never reaches the gate", async () => {
    const current = userFactory({ role: "technician" });
    seedBatch({ userId: current.id, workOrder: wo });
    const { mod } = await mountAuth({
      me: current,
      handlers: [http.get("/work-orders/:id", () => HttpResponse.json(workOrderDetail({ ...wo, status: "completed" })))],
    });
    await mod.initAuth();
    expect(el.page("user-hub").classList.contains("active")).toBe(true);
    expect(savedBatch()).toBeNull();
    // `tryResumeBatch` writes "Your previous work order is no longer active --
    // pick another to continue." into #wo-gate-message and returns false;
    // `enterApp` then calls `resetBatch()`, whose `resetWoCards()` blanks that
    // same element (transactions.js:436). The operator is never told why their
    // batch vanished. Filed under N-P5-CHARACTERIZED.
    expect(el.woGateMessage().textContent).toBe("");
  });

  it("a 404 on the work order clears the snapshot; a network error also loses it", async () => {
    const current = userFactory({ role: "technician" });
    seedBatch({ userId: current.id, workOrder: wo });
    const { mod } = await mountAuth({
      me: current,
      handlers: [http.get("/work-orders/:id", () => HttpResponse.json({ detail: "gone" }, { status: 404 }))],
    });
    await mod.initAuth();
    expect(savedBatch()).toBeNull();

    // A network error is inconclusive, so `tryResumeBatch` deliberately keeps
    // the snapshot "so the next boot can retry" -- and then returns false, at
    // which point `enterApp` calls `resetBatch()` with the default
    // keepSaved:false and discards it anyway. The comment describes an
    // intention the caller defeats. Filed under N-P5-CHARACTERIZED.
    seedBatch({ userId: current.id, workOrder: wo });
    server.use(http.get("/work-orders/:id", () => HttpResponse.error()));
    await mod.initAuth();
    expect(savedBatch()).toBeNull();
  });
});

describe("push at login", () => {
  const pushOk = () => [
    http.get("/push/config", () => HttpResponse.json({ public_key: "QUJD" })),
    http.post("/push/subscribe", () => new HttpResponse(null, { status: 204 })),
  ];

  it("checkbox on + permission 'default': requests permission BEFORE the login request", async () => {
    // The whole point of requestPermissionAtLogin: the click's user gesture is
    // still valid here and gone after the first await. iOS gives no second chance.
    const push = stubPush({ permission: "default" });
    const sequence = [];
    push.requestPermission.mockImplementation(async () => { sequence.push("permission"); return "granted"; });
    await mountAuth({ me: 401, handlers: pushOk() });
    server.use(http.post("/auth/login", () => { sequence.push("login"); return HttpResponse.json(userFactory()); }));
    const user = userEvent.setup();
    await user.click(el.notifications());
    await fillAndSubmit();
    await vi.waitFor(() => expect(el.root().hidden).toBe(false));
    expect(sequence).toEqual(["permission", "login"]);
  });

  it("checkbox off: never asks", async () => {
    const push = stubPush({ permission: "default" });
    await mountAuth({ me: 401 });
    answerLogin(userFactory());
    await fillAndSubmit();
    await vi.waitFor(() => expect(el.root().hidden).toBe(false));
    expect(push.requestPermission).not.toHaveBeenCalled();
  });

  it("checkbox on but permission already decided: no prompt", async () => {
    const push = stubPush({ permission: "denied" });
    await mountAuth({ me: 401 });
    answerLogin(userFactory());
    await userEvent.setup().click(el.notifications());
    await fillAndSubmit();
    await vi.waitFor(() => expect(el.root().hidden).toBe(false));
    expect(push.requestPermission).not.toHaveBeenCalled();
    expect(requestFor("/push/")).toBeNull();
  });

  it("permission granted: initPushForUser subscribes this device after enterApp", async () => {
    const push = stubPush({ permission: "granted" });
    await mountAuth({ me: 401, handlers: pushOk() });
    answerLogin(userFactory({ role: "technician" }));
    await fillAndSubmit();
    await vi.waitFor(() => expect(requestFor("/push/subscribe", "POST")).not.toBeNull());
    expect(push.register).toHaveBeenCalledWith("/service-worker.js");
    expect(requestFor("/push/subscribe", "POST").body.endpoint).toBe("https://push.example/new");
  });

  it("a rejected requestPermission does not block sign-in", async () => {
    const push = stubPush({ permission: "default" });
    push.requestPermission.mockRejectedValue(new Error("nope"));
    await mountAuth({ me: 401 });
    answerLogin(userFactory());
    await userEvent.setup().click(el.notifications());
    await fillAndSubmit();
    await vi.waitFor(() => expect(el.root().hidden).toBe(false));
  });
});
