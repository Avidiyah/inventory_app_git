// Work Orders: integrations.
//
// Layer: the Integrations page -- the Admin+ CSV import, NetFacilities
// enrichment and its per-user cloud sign-in, and the two CSV exports. Owned
// alongside the work-order list rather than on its own because every one of
// these finishes by reloading the list and invalidating the reference data
// the cards read.

import {
  apiCancelNetFacilitiesCloudAuthentication,
  apiExportWorkOrders,
  apiGetNetFacilitiesCloudSession,
  apiGetNetFacilitiesEnrichment,
  apiImportNetFacilitiesCloudDownload,
  apiImportWorkOrders,
  apiStartNetFacilitiesCloudAuthentication,
  apiStartNetFacilitiesEnrichment,
} from "../api.js";
import { setMessage } from "../dom.js";
import { friendlyError } from "../format.js";
import { isAdminPlus } from "./workOrderPresenters.js";
import { invalidateUsers } from "./workOrderReferenceData.js";
import { currentFilters, invalidateFilterOptions } from "./workOrderFilters.js";
import { loadWorkOrders } from "./workOrderList.js";

const importSection = document.getElementById("integrations-import-section");
const importFile = document.getElementById("wo-import-file");
const importBtn = document.getElementById("wo-import-btn");
const importMessage = document.getElementById("wo-import-message");
const netFacilitiesStatus = document.getElementById("wo-netfacilities-status");
const netFacilitiesEnrichBtn = document.getElementById("wo-netfacilities-enrich-btn");
const netFacilitiesCloudSignInBtn = document.getElementById("wo-netfacilities-cloud-sign-in-btn");
const netFacilitiesCloudCancelBtn = document.getElementById("wo-netfacilities-cloud-cancel-btn");
const netFacilitiesCloudImportDownloadBtn = document.getElementById("wo-netfacilities-cloud-import-download-btn");
const exportScope = document.getElementById("wo-export-scope");
const exportBtn = document.getElementById("wo-export-btn");
const exportClientBtn = document.getElementById("wo-export-client-btn");
const exportMessage = document.getElementById("work-orders-export-message");

let netFacilitiesPollingJobId = null;

// Called by nav.js on entry to the Integrations page. Owns the role gate on
// the NetFacilities/Langston University card and refreshes its session state
// -- the counterpart of the importSection/netFacilities handling loadWorkOrders
// used to do when the card lived on the Work Orders page.
export async function loadIntegrationsPage() {
  if (importSection) importSection.hidden = !isAdminPlus();
  if (!isAdminPlus()) return;
  void refreshNetFacilitiesCloudSession();
}

// --- NetFacilities enrichment (Admin+) -----------------------------------
//
// One capability drives this card: the caller's own cloud session. The Enrich
// button below and the sign-in block that follows read the same
// `/cloud/session` response, so there is no second, parallel view of state.

const NETFACILITIES_SESSION_POLL_MS = 3000;

function netFacilitiesCountsMessage(job) {
  const counts = job && job.counts;
  if (!counts) return "NetFacilities enrichment did not return result counts.";
  return [
    `checked ${counts.fetched} of ${counts.candidates} candidate${counts.candidates === 1 ? "" : "s"}`,
    `${counts.descriptions_updated} Task/Symptom updated`,
    `${counts.priorities_updated} Priority updated`,
    `${counts.unchanged} unchanged`,
    `${counts.not_found} not found`,
    `${counts.permission_denied} permission denied`,
    `${counts.other_failures} other failure${counts.other_failures === 1 ? "" : "s"}`,
  ].join(" · ");
}

// Pure: one job snapshot -> the line the card shows and its message kind.
function describeNetFacilitiesJob(job) {
  if (job.state === "queued" || job.state === "running") {
    const currentRequest = job.current_work_order_number
      ? ` Currently requesting work order ${job.current_work_order_number}.`
      : "";
    return { text: `Seeking Task/Symptom and Priority in NetFacilities…${currentRequest}`, kind: "" };
  }
  if (job.state === "completed") {
    return { text: `NetFacilities enrichment completed: ${netFacilitiesCountsMessage(job)}.`, kind: "success" };
  }
  if (job.state === "authentication_required") {
    return {
      text: "NetFacilities authentication is missing or expired. Log in to NetFacilities, then click Import Tasks and Priority.",
      kind: "error",
    };
  }
  if (job.state === "timed_out") {
    return { text: `NetFacilities enrichment timed out with partial results: ${netFacilitiesCountsMessage(job)}.`, kind: "error" };
  }
  if (job.state === "cancelled") {
    return { text: "NetFacilities enrichment stopped when the app shut down.", kind: "error" };
  }
  return {
    text: "NetFacilities enrichment failed without changing unapproved work-order fields. Try again or log in again.",
    kind: "error",
  };
}

function renderNetFacilitiesJob(job) {
  if (!job || !netFacilitiesStatus) return;
  const described = describeNetFacilitiesJob(job);
  setMessage(netFacilitiesStatus, described.text, described.kind);
}

async function pollNetFacilitiesJob(jobId) {
  if (!jobId || netFacilitiesPollingJobId === jobId) return;
  netFacilitiesPollingJobId = jobId;
  if (netFacilitiesEnrichBtn) netFacilitiesEnrichBtn.disabled = true;
  try {
    while (netFacilitiesPollingJobId === jobId) {
      const job = await apiGetNetFacilitiesEnrichment(jobId);
      renderNetFacilitiesJob(job);
      if (job.state !== "queued" && job.state !== "running") {
        if (job.state === "completed" || job.state === "timed_out") {
          invalidateUsers();
          invalidateFilterOptions();
          await loadWorkOrders();
        }
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  } catch (err) {
    if (netFacilitiesStatus) {
      setMessage(netFacilitiesStatus, friendlyError(err, "Could not check NetFacilities enrichment progress."), "error");
    }
  } finally {
    if (netFacilitiesPollingJobId === jobId) netFacilitiesPollingJobId = null;
    // Re-enable the button directly rather than through a cloud-session
    // refresh, which would overwrite the result line the user just earned.
    if (netFacilitiesEnrichBtn) netFacilitiesEnrichBtn.disabled = false;
  }
}

async function runNetFacilitiesEnrichment() {
  if (netFacilitiesEnrichBtn) netFacilitiesEnrichBtn.disabled = true;
  try {
    const job = await apiStartNetFacilitiesEnrichment();
    renderNetFacilitiesJob(job);
    await pollNetFacilitiesJob(job.job_id);
  } catch (err) {
    if (netFacilitiesStatus) {
      setMessage(netFacilitiesStatus, friendlyError(err, "Could not start NetFacilities enrichment. Log in to NetFacilities, then try again."), "error");
    }
  }
}

if (netFacilitiesEnrichBtn) {
  netFacilitiesEnrichBtn.addEventListener("click", runNetFacilitiesEnrichment);
}


// --- Per-user NetFacilities cloud sign-in (Admin+, spec D2, D3, D7) -------
//
// Independent of the local flow above: any authorized user, on any device,
// signs into NetFacilities through a Steel cloud browser instead of the
// owner's Windows machine. Only rendered when the backend reports the
// capability as available (NETFACILITIES_CLOUD_AUTH_ENABLED and its
// prerequisites -- see cloud_config.py).

let netFacilitiesCloudPollTimer = null;

async function refreshNetFacilitiesCloudSession() {
  let capability;
  try {
    capability = await apiGetNetFacilitiesCloudSession();
  } catch {
    capability = null;
  }
  updateNetFacilitiesCloudControls(capability);
  return capability;
}

function updateNetFacilitiesCloudControls(capability) {
  const available = Boolean(capability && capability.available);
  const cloudStatus = capability && capability.status;
  const awaitingSignIn = Boolean(cloudStatus && cloudStatus.state === "awaiting_sign_in");
  const signedIn = Boolean(cloudStatus && cloudStatus.state === "signed_in");
  // E8: the fallback appears only when a capture is sitting unconsumed --
  // the chain normally consumes it before the next poll lands.
  const hasUnconsumedCsv = signedIn
    && Boolean(cloudStatus.last_download_filename)
    && !cloudStatus.capture_consumed;
  const chainStage = cloudStatus ? cloudStatus.chain_stage : null;

  if (netFacilitiesCloudSignInBtn) {
    netFacilitiesCloudSignInBtn.hidden = !available || awaitingSignIn || signedIn;
  }
  if (netFacilitiesCloudCancelBtn) {
    netFacilitiesCloudCancelBtn.hidden = !(awaitingSignIn || signedIn);
  }
  if (netFacilitiesCloudImportDownloadBtn) {
    netFacilitiesCloudImportDownloadBtn.hidden = !hasUnconsumedCsv;
  }
  // The Enrich button is driven by this one capability: enrichment runs
  // through the caller's own saved cloud session or not at all.
  if (netFacilitiesEnrichBtn) {
    netFacilitiesEnrichBtn.hidden = !available;
    netFacilitiesEnrichBtn.disabled = !(available && capability.has_saved_session)
      || Boolean(netFacilitiesPollingJobId);
  }
  // A job's own result line owns the status while it is polling.
  if (netFacilitiesStatus && !awaitingSignIn && !netFacilitiesPollingJobId) {
    if (!available) {
      setMessage(netFacilitiesStatus, capability ? capability.message : "NetFacilities status is unavailable. CSV import still works normally.", "");
    } else if (chainStage === "importing") {
      setMessage(netFacilitiesStatus, `Importing ${cloudStatus.last_download_filename}…`, "");
    } else if (chainStage === "imported" || chainStage === "enriching") {
      setMessage(netFacilitiesStatus, `${importSummary(cloudStatus.import_result)} Starting Task/Symptom and Priority…`, "success");
    } else if (chainStage === "done") {
      // The reconcile counts ride along in import_result, so this line and a
      // clicked import's line can never tell two different stories.
      setMessage(netFacilitiesStatus, `${importSummary(cloudStatus.import_result)} ${cloudStatus.enrichment_job_id ? "Enrichment is running." : "Enrichment is busy — click Import Tasks and Priority when it frees up."}`, "success");
    } else if (chainStage === "failed") {
      setMessage(netFacilitiesStatus, `${cloudStatus.import_error || "That import did not finish."} You are still signed in — export the right CSV in the NetFacilities window and it will import automatically.`, "error");
    } else if (signedIn) {
      if (hasUnconsumedCsv) {
        setMessage(netFacilitiesStatus, `Saved ${cloudStatus.last_download_filename}. Click Import downloaded CSV to import it and fill in Task/Symptom and Priority.`, "success");
      } else {
        setMessage(netFacilitiesStatus, "NetFacilities is open and logged in. Export the work-order CSV in that window — it imports and enriches on its own.", "success");
      }
    } else if (capability.has_saved_session) {
      setMessage(netFacilitiesStatus, "Saved NetFacilities login is ready. Choose a downloaded CSV to import it and seek Task/Symptom and Priority, or log in to export a fresh one.", "success");
    } else {
      setMessage(netFacilitiesStatus, capability.message, "");
    }
  }

  const chainRunning = Boolean(cloudStatus && ["importing", "imported", "enriching"].includes(cloudStatus.chain_stage));
  const shouldPoll = available && (awaitingSignIn || signedIn || chainRunning);
  if (shouldPoll && !netFacilitiesCloudPollTimer) {
    netFacilitiesCloudPollTimer = setInterval(
      refreshNetFacilitiesCloudSession,
      NETFACILITIES_SESSION_POLL_MS,
    );
  } else if (!shouldPoll && netFacilitiesCloudPollTimer) {
    clearInterval(netFacilitiesCloudPollTimer);
    netFacilitiesCloudPollTimer = null;
  }

  maybeHandleChainCompletion(cloudStatus).catch(() => {});
}

// One-shot handling of a finished chain observed through the session poll:
// reload the list the import changed, then hand the status line to the
// enrichment job's own poller. Keyed by attempt and stage so the poll (or a
// page re-entry) does not replay it, and set eagerly by the manual button,
// which already did both itself.
let handledChainCompletion = null;

async function maybeHandleChainCompletion(cloudStatus) {
  if (!cloudStatus || !["done", "failed"].includes(cloudStatus.chain_stage)) return;
  const key = `${cloudStatus.attempt_id}:${cloudStatus.chain_stage}`;
  if (handledChainCompletion === key) return;
  handledChainCompletion = key;
  if (cloudStatus.chain_stage !== "done") return;
  invalidateUsers();
  invalidateFilterOptions();
  await loadWorkOrders();
  if (cloudStatus.enrichment_job_id) {
    await pollNetFacilitiesJob(cloudStatus.enrichment_job_id);
  }
}

async function startNetFacilitiesCloudAuthentication() {
  if (netFacilitiesCloudSignInBtn) netFacilitiesCloudSignInBtn.disabled = true;
  try {
    const status = await apiStartNetFacilitiesCloudAuthentication();
    if (status && status.live_view_url) {
      window.open(status.live_view_url, "_blank", "noopener");
    }
  } catch (err) {
    setMessage(netFacilitiesStatus, friendlyError(err, "Could not open a NetFacilities cloud session."), "error");
  } finally {
    if (netFacilitiesCloudSignInBtn) netFacilitiesCloudSignInBtn.disabled = false;
    await refreshNetFacilitiesCloudSession();
  }
}

async function cancelNetFacilitiesCloudAuthentication() {
  if (netFacilitiesCloudCancelBtn) netFacilitiesCloudCancelBtn.disabled = true;
  try {
    await apiCancelNetFacilitiesCloudAuthentication();
  } catch (err) {
    setMessage(netFacilitiesStatus, friendlyError(err, "Could not close the NetFacilities cloud session."), "error");
  } finally {
    if (netFacilitiesCloudCancelBtn) netFacilitiesCloudCancelBtn.disabled = false;
    await refreshNetFacilitiesCloudSession();
  }
}

async function importNetFacilitiesCloudDownload() {
  if (netFacilitiesCloudImportDownloadBtn) netFacilitiesCloudImportDownloadBtn.disabled = true;
  setMessage(importMessage, "Importing…", "");
  try {
    // The route now runs the whole chain the automatic path does (E8) --
    // import, session close, enrichment -- and returns the ceremony status,
    // not a bare import summary.
    const status = await apiImportNetFacilitiesCloudDownload();
    handledChainCompletion = `${status.attempt_id}:${status.chain_stage}`;
    if (status.chain_stage === "failed") {
      setMessage(importMessage, status.import_error || "Could not import the downloaded CSV.", "error");
    } else {
      await afterWorkOrderImport(status.import_result, { chainOwnsEnrichment: true });
      if (status.enrichment_job_id) {
        await pollNetFacilitiesJob(status.enrichment_job_id);
      }
    }
  } catch (err) {
    setMessage(importMessage, friendlyError(err, "Could not import the downloaded CSV."), "error");
  } finally {
    if (netFacilitiesCloudImportDownloadBtn) netFacilitiesCloudImportDownloadBtn.disabled = false;
    await refreshNetFacilitiesCloudSession();
  }
}

if (netFacilitiesCloudSignInBtn) {
  netFacilitiesCloudSignInBtn.addEventListener("click", startNetFacilitiesCloudAuthentication);
}
if (netFacilitiesCloudCancelBtn) {
  netFacilitiesCloudCancelBtn.addEventListener("click", cancelNetFacilitiesCloudAuthentication);
}
if (netFacilitiesCloudImportDownloadBtn) {
  netFacilitiesCloudImportDownloadBtn.addEventListener("click", importNetFacilitiesCloudDownload);
}

// --- CSV import (Admin+) --------------------------------------------------

// What one import did, as clauses joined by " · ", each appearing only when its
// count is non-zero. `supervisors_matched` counts new work orders only, so the
// match count never exceeds `created`.
function importSummary(r) {
  const clauses = [];
  if (r.created) {
    const noun = r.created === 1 ? "new work order" : "new work orders";
    clauses.push(`${r.created} ${noun}`);
    clauses.push(`${r.supervisors_matched} with a supervisor name match`);
  }
  if (!clauses.length) return "No new work orders.";
  return `${clauses.join(" · ")}.`;
}

// Everything that follows a successful import, whether the CSV was uploaded
// or captured from the cloud window: summary, list reload, then enrichment
// through the caller's own cloud session when they have one.
// `chainOwnsEnrichment` is true for the cloud path, where the server's
// capture chain starts enrichment itself (E8). Enriching again here would
// collide with that job, burn the chain's retry budget, and narrate a
// queue that is really our own duplicate.
async function afterWorkOrderImport(r, { chainOwnsEnrichment = false } = {}) {
  // Only the new work orders are worth reporting: re-imported numbers keep
  // their own routing, and rows the import passed over changed nothing.
  setMessage(importMessage, importSummary(r), "success");
  // Reset caches so a re-import reflects fresh data, then reload the list.
  invalidateUsers();
  invalidateFilterOptions();
  await loadWorkOrders();
  const capability = await refreshNetFacilitiesCloudSession();
  const cloudStatus = capability && capability.status;
  if (
    !chainOwnsEnrichment
    && capability
    && capability.available
    && (capability.has_saved_session || (cloudStatus && cloudStatus.state === "signed_in"))
  ) {
    await runNetFacilitiesEnrichment();
  }
}

async function handleImport() {
  const file = importFile.files && importFile.files[0];
  if (!file) return;
  setMessage(importMessage, "Importing…", "");
  importBtn.disabled = true;
  try {
    const r = await apiImportWorkOrders(file);
    await afterWorkOrderImport(r);
  } catch (err) {
    setMessage(importMessage, friendlyError(err, "Could not import that file."), "error");
  } finally {
    importBtn.disabled = false;
    importFile.value = "";  // allow re-selecting the same file
  }
}

if (importBtn) importBtn.addEventListener("click", () => importFile && importFile.click());
if (importFile) importFile.addEventListener("change", handleImport);

// --- CSV export (Admin+) --------------------------------------------------

// Label for the status the export dropdown is set to, for the result message.
function exportScopeLabel(scope) {
  const option = exportScope && [...exportScope.options].find(o => o.value === scope);
  return option ? option.textContent : scope;
}

async function downloadExport({ scope, variant, filters = {}, button, messageEl, label }) {
  setMessage(messageEl, "Preparing export…", "");
  if (button) button.disabled = true;
  try {
    const { blob, filename } = await apiExportWorkOrders(scope, { variant, filters });
    // An empty scope still returns a header-only file; say so rather than
    // handing over a CSV that looks broken.
    const headerOnly = blob.size > 0 && (await blob.text()).trim().split("\n").length <= 1;
    // Anchor + object URL is the only way to name a downloaded blob; revoke on
    // the next tick so the click has already consumed the URL.
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    setMessage(
      messageEl,
      headerOnly
        ? `No work orders matched ${label} — downloaded an empty file.`
        : `Exported ${label} to ${filename}.`,
      headerOnly ? "" : "success",
    );
  } catch (err) {
    setMessage(messageEl, friendlyError(err, "Could not export work orders."), "error");
  } finally {
    if (button) button.disabled = false;
  }
}

async function handleFilteredExport() {
  const filters = currentFilters();
  await downloadExport({
    scope: filters.status || "all",
    variant: "full",
    filters,
    button: exportBtn,
    messageEl: exportMessage,
    label: "the current Work Orders filters",
  });
}

async function handleClientExport() {
  const scope = exportScope ? exportScope.value : "all";
  await downloadExport({
    scope,
    variant: "client",
    button: exportClientBtn,
    messageEl: importMessage,
    label: `${exportScopeLabel(scope)} client receipts`,
  });
}

if (exportBtn) exportBtn.addEventListener("click", handleFilteredExport);
if (exportClientBtn) exportClientBtn.addEventListener("click", handleClientExport);
