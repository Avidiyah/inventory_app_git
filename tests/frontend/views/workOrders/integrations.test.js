// Characterization: the Integrations page surface this module also owns --
// the CSV import, the two exports, the NetFacilities enrichment job, and the
// per-user cloud session.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../../helpers/handlers.js";
import {
  mountWorkOrders, requestFor, requests, respond, seedList, state,
} from "../../helpers/workOrders.js";
import {
  restoreBrowserStubs, stubObjectUrl, stubScroll, stubWindowOpen,
} from "../../helpers/browserStubs.js";
import { workOrderCard } from "../../helpers/factories.js";

afterEach(() => restoreBrowserStubs());

const el = (id) => document.getElementById(id);
const statusLine = () => el("wo-netfacilities-status");
const importLine = () => el("wo-import-message");
const exportLine = () => el("work-orders-export-message");

// The capability shape `GET /cloud/session` answers with.
function capability(overrides = {}) {
  return {
    available: true,
    has_saved_session: false,
    message: "Sign in to NetFacilities to import tasks.",
    status: null,
    ...overrides,
  };
}

function cloudStatus(overrides = {}) {
  return {
    state: "idle",
    attempt_id: "a1",
    chain_stage: null,
    last_download_filename: null,
    capture_consumed: false,
    import_result: null,
    import_error: null,
    enrichment_job_id: null,
    ...overrides,
  };
}

const SESSION = "/integrations/netfacilities/cloud/session";

// Mount, then run the Integrations page entry point with a given capability.
async function mountIntegrations({ role = "admin", session = capability() } = {}) {
  stubScroll();
  const mounted = await mountWorkOrders({ role });
  if (session) respond("get", SESSION, session);
  await mounted.mod.loadIntegrationsPage();
  // `loadIntegrationsPage` fires the session read with `void`, so the
  // controls are painted a few ticks after it resolves.
  if (session && role === "admin") {
    // Waiting for the request only proves it started. The controls move off
    // their pristine markup state (hidden, enabled) once the response has
    // been applied, whichever branch it takes.
    await vi.waitFor(() => {
      const enrich = el("wo-netfacilities-enrich-btn");
      expect(enrich.hidden === false || enrich.disabled === true).toBe(true);
    });
  }
  return mounted;
}

describe("loadIntegrationsPage", () => {
  it("reveals the card and asks for the cloud session at Admin+", async () => {
    await mountIntegrations({ role: "admin" });
    expect(el("integrations-import-section").hidden).toBe(false);
    await vi.waitFor(() => expect(requestFor(SESSION)).not.toBeNull());
  });

  it("keeps it hidden, and asks for nothing, below Admin+", async () => {
    const { mod } = await mountWorkOrders({ role: "supervisor" });
    await mod.loadIntegrationsPage();
    expect(el("integrations-import-section").hidden).toBe(true);
    expect(requestFor(SESSION)).toBeNull();
  });

  it("says the status is unavailable when the session request fails", async () => {
    const { mod } = await mountWorkOrders({ role: "admin" });
    respond("get", SESSION, { detail: "no" }, { status: 500 });
    await mod.loadIntegrationsPage();
    await vi.waitFor(() => expect(statusLine().textContent)
      .toBe("NetFacilities status is unavailable. CSV import still works normally."));
  });
});

describe("the CSV import", () => {
  const csv = () => new File(["number,task\n1,x"], "wo.csv", { type: "text/csv" });

  function chooseFile(file) {
    const input = el("wo-import-file");
    Object.defineProperty(input, "files", { configurable: true, value: file ? [file] : [] });
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  it("opens the file picker from the visible button", async () => {
    await mountIntegrations();
    const clicked = vi.fn();
    el("wo-import-file").addEventListener("click", clicked);
    el("wo-import-btn").click();
    expect(clicked).toHaveBeenCalledTimes(1);
  });

  it("does nothing when the picker is dismissed", async () => {
    await mountIntegrations();
    chooseFile(null);
    await new Promise((r) => setTimeout(r, 20));
    expect(requestFor("/work-orders/import")).toBeNull();
  });

  it("uploads, summarises, and reloads the list", async () => {
    await mountIntegrations();
    respond("post", "/work-orders/import", { created: 2, supervisors_matched: 1 });
    seedList([workOrderCard({ number: "1" })]);
    chooseFile(csv());
    await vi.waitFor(() => expect(importLine().textContent)
      .toBe("2 new work orders · 1 with a supervisor name match."));
    expect(importLine().className).toBe("success");
    expect(requestFor("/work-orders/import", "POST")).not.toBeNull();
    expect(requestFor("/work-orders/?")).not.toBeNull();
    // The input is cleared so the same file can be chosen again.
    expect(el("wo-import-btn").disabled).toBe(false);
  });

  it("uses the singular noun for one work order", async () => {
    await mountIntegrations();
    respond("post", "/work-orders/import", { created: 1, supervisors_matched: 0 });
    chooseFile(csv());
    await vi.waitFor(() => expect(importLine().textContent)
      .toBe("1 new work order · 0 with a supervisor name match."));
  });

  it("says so when the file added nothing", async () => {
    await mountIntegrations();
    respond("post", "/work-orders/import", { created: 0, supervisors_matched: 0 });
    chooseFile(csv());
    await vi.waitFor(() => expect(importLine().textContent).toBe("No new work orders."));
  });

  it("reports a failure through friendlyError and re-enables the button", async () => {
    await mountIntegrations();
    respond("post", "/work-orders/import", { detail: "Bad header row" }, { status: 400 });
    chooseFile(csv());
    await vi.waitFor(() => expect(importLine().textContent).toBe("Bad header row"));
    expect(importLine().className).toBe("error");
    expect(el("wo-import-btn").disabled).toBe(false);
  });

  it("chains straight into enrichment when a saved cloud session exists", async () => {
    await mountIntegrations({ session: capability({ has_saved_session: true }) });
    respond("post", "/work-orders/import", { created: 1, supervisors_matched: 0 });
    respond("post", "/integrations/netfacilities/work-orders/enrich",
      { job_id: "j1", state: "completed", counts: null });
    respond("get", "/integrations/netfacilities/work-orders/enrich/:jobId",
      { job_id: "j1", state: "completed", counts: null });
    chooseFile(csv());
    await vi.waitFor(() =>
      expect(requestFor("/work-orders/enrich", "POST")).not.toBeNull());
  });
});

describe("the exports", () => {
  function csvResponse(text, filename = "20260910_all.csv") {
    return new HttpResponse(text, {
      status: 200,
      headers: { "Content-Disposition": `attachment; filename="${filename}"` },
    });
  }

  it("sends the current filters and the full variant", async () => {
    const urls = stubObjectUrl();
    await mountIntegrations();
    el("work-orders-status-filter").value = "completed";
    el("work-orders-service-filter").innerHTML = '<option value="HVAC">HVAC</option>';
    el("work-orders-service-filter").value = "HVAC";
    server.use(http.get("/work-orders/export", () => csvResponse("a,b\n1,2")));
    el("wo-export-btn").click();
    await vi.waitFor(() => expect(exportLine().textContent)
      .toBe("Exported the current Work Orders filters to 20260910_all.csv."));
    expect(exportLine().className).toBe("success");
    const url = requestFor("/work-orders/export").url;
    expect(url).toContain("scope=completed");
    expect(url).toContain("variant=full");
    expect(url).toContain("service_type=HVAC");
    expect(urls.createObjectURL).toHaveBeenCalledTimes(1);
  });

  it("falls back to scope=all when no status filter is set", async () => {
    stubObjectUrl();
    await mountIntegrations();
    server.use(http.get("/work-orders/export", () => csvResponse("a,b\n1,2")));
    el("wo-export-btn").click();
    await vi.waitFor(() => expect(requestFor("/work-orders/export")).not.toBeNull());
    expect(requestFor("/work-orders/export").url).toContain("scope=all");
  });

  it("sends the client variant with the dropdown's scope, and no filters", async () => {
    stubObjectUrl();
    await mountIntegrations();
    el("work-orders-status-filter").value = "completed";
    el("wo-export-scope").value = "archived";
    server.use(http.get("/work-orders/export", () => csvResponse("a,b\n1,2")));
    el("wo-export-client-btn").click();
    await vi.waitFor(() => expect(importLine().textContent)
      .toBe("Exported Archived (closed) client receipts to 20260910_all.csv."));
    expect(requestFor("/work-orders/export").url)
      .toBe("/work-orders/export?scope=archived&variant=client");
  });

  it("names the anchor after the server's filename and clicks it", async () => {
    stubObjectUrl();
    await mountIntegrations();
    server.use(http.get("/work-orders/export", () => csvResponse("a,b\n1,2", "custom.csv")));
    const anchors = [];
    const create = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag) => {
      const node = create(tag);
      if (tag === "a") {
        node.click = vi.fn();
        anchors.push(node);
      }
      return node;
    });
    el("wo-export-btn").click();
    await vi.waitFor(() => expect(anchors).toHaveLength(1));
    expect(anchors[0].download).toBe("custom.csv");
    expect(anchors[0].href).toContain("blob:test/1");
    expect(anchors[0].click).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => expect(anchors[0].isConnected).toBe(false));
    vi.restoreAllMocks();
  });

  it("says a header-only file matched nothing, without the success class", async () => {
    stubObjectUrl();
    await mountIntegrations();
    server.use(http.get("/work-orders/export", () => csvResponse("number,task\n")));
    el("wo-export-btn").click();
    await vi.waitFor(() => expect(exportLine().textContent)
      .toBe("No work orders matched the current Work Orders filters — downloaded an empty file."));
    expect(exportLine().className).toBe("");
  });

  it("re-enables the button after a failure", async () => {
    stubObjectUrl();
    await mountIntegrations();
    server.use(http.get("/work-orders/export", () =>
      HttpResponse.json({ detail: "Admin only" }, { status: 403 })));
    el("wo-export-btn").click();
    await vi.waitFor(() => expect(exportLine().textContent)
      .toBe("Your account can't do that. Ask a supervisor if this seems wrong."));
    expect(el("wo-export-btn").disabled).toBe(false);
  });

  it("hides the filtered export below Admin+", async () => {
    await mountWorkOrders({ role: "supervisor" });
    expect(el("wo-export-btn").hidden).toBe(true);
  });
});

describe("the enrichment job", () => {
  const enrichUrl = "/integrations/netfacilities/work-orders/enrich";
  const counts = {
    candidates: 2, fetched: 2, descriptions_updated: 1, priorities_updated: 1,
    unchanged: 0, not_found: 0, permission_denied: 0, other_failures: 0,
  };

  async function ready() {
    return mountIntegrations({
      session: capability({ has_saved_session: true, status: cloudStatus() }),
    });
  }

  it("reports a completed job with its counts and reloads the list", async () => {
    await ready();
    respond("post", enrichUrl, { job_id: "j1", state: "queued" });
    respond("get", `${enrichUrl}/:jobId`, { job_id: "j1", state: "completed", counts });
    el("wo-netfacilities-enrich-btn").click();
    await vi.waitFor(() => expect(statusLine().textContent).toBe(
      "NetFacilities enrichment completed: checked 2 of 2 candidates · 1 Task/Symptom updated · "
      + "1 Priority updated · 0 unchanged · 0 not found · 0 permission denied · 0 other failures."));
    expect(statusLine().className).toBe("success");
    await vi.waitFor(() => expect(requestFor("/work-orders/?")).not.toBeNull());
  });

  it("narrates a running job, then stops polling once it settles", async () => {
    // Real timers: the poll waits a real second between reads, and the point
    // of the test is that it stops on its own.
    await ready();
    let poll = 0;
    server.use(http.post(enrichUrl, () =>
      HttpResponse.json({ job_id: "j1", state: "running", current_work_order_number: "4242" })));
    server.use(http.get(`${enrichUrl}/:jobId`, () => {
      poll += 1;
      return HttpResponse.json(poll < 2
        ? { job_id: "j1", state: "running", current_work_order_number: "4242" }
        : { job_id: "j1", state: "completed", counts });
    }));
    el("wo-netfacilities-enrich-btn").click();
    await vi.waitFor(() => expect(statusLine().textContent).toBe(
      "Seeking Task/Symptom and Priority in NetFacilities… Currently requesting work order 4242."));
    expect(el("wo-netfacilities-enrich-btn").disabled).toBe(true);
    await vi.waitFor(() => expect(statusLine().className).toBe("success"), { timeout: 4000 });
    const settled = poll;
    await new Promise((r) => setTimeout(r, 1200));
    expect(poll).toBe(settled);
    expect(el("wo-netfacilities-enrich-btn").disabled).toBe(false);
  }, 10000);

  it.each([
    ["authentication_required", "error",
      "NetFacilities authentication is missing or expired. Log in to NetFacilities, then click Import Tasks and Priority."],
    ["cancelled", "error", "NetFacilities enrichment stopped when the app shut down."],
    ["failed", "error",
      "NetFacilities enrichment failed without changing unapproved work-order fields. Try again or log in again."],
  ])("describes a %s job", async (jobState, kind, text) => {
    await ready();
    respond("post", enrichUrl, { job_id: "j1", state: jobState });
    respond("get", `${enrichUrl}/:jobId`, { job_id: "j1", state: jobState });
    el("wo-netfacilities-enrich-btn").click();
    await vi.waitFor(() => expect(statusLine().textContent).toBe(text));
    expect(statusLine().className).toBe(kind);
  });

  it("describes a timed-out job with its partial counts", async () => {
    await ready();
    respond("post", enrichUrl, { job_id: "j1", state: "timed_out", counts });
    respond("get", `${enrichUrl}/:jobId`, { job_id: "j1", state: "timed_out", counts });
    el("wo-netfacilities-enrich-btn").click();
    await vi.waitFor(() => expect(statusLine().textContent)
      .toContain("NetFacilities enrichment timed out with partial results:"));
    expect(statusLine().className).toBe("error");
  });

  it("says so when a finished job carried no counts", async () => {
    await ready();
    respond("post", enrichUrl, { job_id: "j1", state: "completed", counts: null });
    respond("get", `${enrichUrl}/:jobId`, { job_id: "j1", state: "completed", counts: null });
    el("wo-netfacilities-enrich-btn").click();
    await vi.waitFor(() => expect(statusLine().textContent)
      // Two full stops: the "no counts" sentence is a sentence, and the
      // caller appends its own period regardless.
      .toBe("NetFacilities enrichment completed: NetFacilities enrichment did not return result counts.."));
  });

  it("reports a failure to start", async () => {
    await ready();
    respond("post", enrichUrl, { detail: "Not signed in" }, { status: 400 });
    el("wo-netfacilities-enrich-btn").click();
    await vi.waitFor(() => expect(statusLine().textContent).toBe("Not signed in"));
    expect(statusLine().className).toBe("error");
  });
});

describe("the cloud sign-in controls", () => {
  const controls = () => ({
    signIn: el("wo-netfacilities-cloud-sign-in-btn").hidden,
    cancel: el("wo-netfacilities-cloud-cancel-btn").hidden,
    importDownload: el("wo-netfacilities-cloud-import-download-btn").hidden,
    enrichHidden: el("wo-netfacilities-enrich-btn").hidden,
    enrichDisabled: el("wo-netfacilities-enrich-btn").disabled,
  });

  it("hides everything when the capability is unavailable", async () => {
    await mountIntegrations({
      session: capability({ available: false, message: "Cloud sign-in is not configured." }),
    });
    expect(controls()).toEqual({
      signIn: true, cancel: true, importDownload: true,
      enrichHidden: true, enrichDisabled: true,
    });
    expect(statusLine().textContent).toBe("Cloud sign-in is not configured.");
  });

  it("offers sign-in, and a disabled Enrich, with no saved session", async () => {
    await mountIntegrations({ session: capability() });
    expect(controls()).toEqual({
      signIn: false, cancel: true, importDownload: true,
      enrichHidden: false, enrichDisabled: true,
    });
    expect(statusLine().textContent).toBe("Sign in to NetFacilities to import tasks.");
  });

  it("enables Enrich once a session is saved", async () => {
    await mountIntegrations({ session: capability({ has_saved_session: true }) });
    expect(controls().enrichDisabled).toBe(false);
    expect(statusLine().textContent).toContain("Saved NetFacilities login is ready.");
  });

  it("swaps sign-in for cancel while a sign-in is awaited", async () => {
    await mountIntegrations({
      session: capability({ status: cloudStatus({ state: "awaiting_sign_in" }) }),
    });
    expect(controls().signIn).toBe(true);
    expect(controls().cancel).toBe(false);
  });

  it("offers the download import only while a capture sits unconsumed", async () => {
    await mountIntegrations({
      session: capability({
        has_saved_session: true,
        status: cloudStatus({
          state: "signed_in", last_download_filename: "export.csv", capture_consumed: false,
        }),
      }),
    });
    expect(controls().importDownload).toBe(false);
    expect(statusLine().textContent)
      .toBe("Saved export.csv. Click Import downloaded CSV to import it and fill in Task/Symptom and Priority.");
  });

  it("hides it again once the chain consumed the capture", async () => {
    await mountIntegrations({
      session: capability({
        has_saved_session: true,
        status: cloudStatus({
          state: "signed_in", last_download_filename: "export.csv", capture_consumed: true,
        }),
      }),
    });
    expect(controls().importDownload).toBe(true);
    expect(statusLine().textContent)
      .toBe("NetFacilities is open and logged in. Export the work-order CSV in that window — it imports and enriches on its own.");
  });

  it.each([
    ["importing", "Importing export.csv…", ""],
    ["failed", "That import did not finish. You are still signed in — export the right CSV in the NetFacilities window and it will import automatically.", "error"],
  ])("narrates the %s chain stage", async (stage, text, kind) => {
    await mountIntegrations({
      session: capability({
        has_saved_session: true,
        status: cloudStatus({
          state: "signed_in", chain_stage: stage, last_download_filename: "export.csv",
        }),
      }),
    });
    expect(statusLine().textContent).toBe(text);
    expect(statusLine().className).toBe(kind);
  });

  it("narrates a finished chain and reloads the list once", async () => {
    await mountIntegrations({
      session: capability({
        has_saved_session: true,
        status: cloudStatus({
          state: "signed_in", chain_stage: "done", enrichment_job_id: null,
          import_result: { created: 3, supervisors_matched: 2 },
        }),
      }),
    });
    expect(statusLine().textContent).toBe(
      "3 new work orders · 2 with a supervisor name match. "
      + "Enrichment is busy — click Import Tasks and Priority when it frees up.");
    await vi.waitFor(() => expect(requestFor("/work-orders/?")).not.toBeNull());
    // The reload also invalidates the user cache, so let that settle too.
    await vi.waitFor(() => expect(requests().some((r) => r.url === "/users/")).toBe(true));
    const reloads = requests().filter((r) => r.url.startsWith("/work-orders/?")).length;
    // One-shot: a second observation of the same attempt does not replay it.
    await new Promise((r) => setTimeout(r, 30));
    expect(requests().filter((r) => r.url.startsWith("/work-orders/?")).length).toBe(reloads);
  });

  it("opens the live view in a new tab when a sign-in starts", async () => {
    const openSpy = stubWindowOpen();
    await mountIntegrations();
    respond("post", "/integrations/netfacilities/cloud/auth/start",
      { live_view_url: "https://cloud.example/live/1" });
    el("wo-netfacilities-cloud-sign-in-btn").click();
    await vi.waitFor(() => expect(openSpy).toHaveBeenCalledWith(
      "https://cloud.example/live/1", "_blank", "noopener"));
    // The session is re-read afterwards, whatever happened.
    await vi.waitFor(() =>
      expect(requests().filter((r) => r.url === SESSION).length).toBeGreaterThan(1));
    expect(el("wo-netfacilities-cloud-sign-in-btn").disabled).toBe(false);
  });

  it("reports a sign-in that could not start", async () => {
    await mountIntegrations();
    respond("post", "/integrations/netfacilities/cloud/auth/start", { detail: "No slots" }, { status: 503 });
    // The `finally` re-reads the session; an awaiting_sign_in state is the
    // one that leaves the error visible, because the control refresh only
    // writes the status line when no sign-in is pending.
    respond("get", SESSION, capability({ status: cloudStatus({ state: "awaiting_sign_in" }) }));
    el("wo-netfacilities-cloud-sign-in-btn").click();
    await vi.waitFor(() => expect(statusLine().textContent).toBe("No slots"));
    await vi.waitFor(() =>
      expect(requests().filter((r) => r.url === SESSION).length).toBeGreaterThan(1));
  });

  it("cancels a session and re-reads it", async () => {
    await mountIntegrations({
      session: capability({ status: cloudStatus({ state: "awaiting_sign_in" }) }),
    });
    respond("post", "/integrations/netfacilities/cloud/auth/cancel", { ok: true });
    el("wo-netfacilities-cloud-cancel-btn").click();
    await vi.waitFor(() =>
      expect(requestFor("/cloud/auth/cancel", "POST")).not.toBeNull());
    // Re-enabled in the `finally`, which also re-reads the session.
    await vi.waitFor(() =>
      expect(el("wo-netfacilities-cloud-cancel-btn").disabled).toBe(false));
    expect(requests().filter((r) => r.url === SESSION).length).toBeGreaterThan(1);
  });

  it("imports a captured download through the whole chain", async () => {
    await mountIntegrations({
      session: capability({
        has_saved_session: true,
        status: cloudStatus({
          state: "signed_in", last_download_filename: "export.csv", capture_consumed: false,
        }),
      }),
    });
    respond("post", "/integrations/netfacilities/cloud/downloads/import", {
      attempt_id: "a2", chain_stage: "done", enrichment_job_id: null,
      import_result: { created: 1, supervisors_matched: 0 },
    });
    el("wo-netfacilities-cloud-import-download-btn").click();
    await vi.waitFor(() => expect(importLine().textContent)
      .toBe("1 new work order · 0 with a supervisor name match."));
    // The chain owns enrichment, so this path must not start a second job.
    expect(requestFor("/work-orders/enrich", "POST")).toBeNull();
    expect(el("wo-netfacilities-cloud-import-download-btn").disabled).toBe(false);
  });

  it("reports a failed capture import", async () => {
    await mountIntegrations({
      session: capability({
        has_saved_session: true,
        status: cloudStatus({
          state: "signed_in", last_download_filename: "export.csv", capture_consumed: false,
        }),
      }),
    });
    respond("post", "/integrations/netfacilities/cloud/downloads/import", {
      attempt_id: "a3", chain_stage: "failed", import_error: "Wrong CSV.",
    });
    el("wo-netfacilities-cloud-import-download-btn").click();
    await vi.waitFor(() => expect(importLine().textContent).toBe("Wrong CSV."));
    expect(importLine().className).toBe("error");
  });

  it("polls the session while a sign-in is pending, and stops when it settles", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
    stubScroll();
    const { mod } = await mountWorkOrders({ role: "admin" });
    let polls = 0;
    // The server decides what is pending, not the poll count: `vi.waitFor`
    // drives the fake clock itself, so how many polls land before the state
    // flips is timing-dependent (and different again under --coverage).
    let pending = true;
    server.use(http.get(SESSION, () => {
      polls += 1;
      return HttpResponse.json(pending
        ? capability({ status: cloudStatus({ state: "awaiting_sign_in" }) })
        : capability({ status: cloudStatus({ state: "idle" }) }));
    }));
    await mod.loadIntegrationsPage();
    // The page kicks the first read off without awaiting it.
    await vi.waitFor(() => expect(polls).toBeGreaterThanOrEqual(1), { interval: 5 });
    const afterLoad = polls;
    // Pending: the interval keeps re-reading the session on its own.
    vi.advanceTimersByTime(3000);
    await vi.waitFor(() => expect(polls).toBeGreaterThan(afterLoad), { interval: 5 });
    // Settled: the interval is cleared, so polling goes quiet -- three
    // interval periods pass without another request.
    pending = false;
    await vi.waitFor(async () => {
      const before = polls;
      vi.advanceTimersByTime(9000);
      await Promise.resolve();
      expect(polls).toBe(before);
    }, { interval: 5 });
    vi.useRealTimers();
    expect(state).toBeTruthy();
  });
});
