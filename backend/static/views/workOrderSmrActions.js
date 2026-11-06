// Work Orders: the ten `smr-*` branches of the card's click delegation and
// the worker search. workOrderActions.js routes every `smr-` action but the
// paper check here; errors propagate to its shared catch and land in
// `.wo-message`. The markup is built in workOrderSmrLines.js.

import {
  apiSmrAddLine,
  apiSmrAddReading,
  apiSmrAddWorker,
  apiSmrEditLine,
  apiSmrGenerateBlock,
  apiSmrMarkPasted,
  apiSmrSearchWorkers,
  apiSetSmrReady,
} from "../api.js";
import { escapeHtml } from "../format.js";
import { setMessage } from "../dom.js";
import { refreshCard } from "./workOrderList.js";
import { fillLineForm, readLineForm } from "./workOrderSmrLines.js";

const SECTION = ".wo-smr-section";

function pickWorker(form, id, name) {
  form.querySelector(".wo-smr-f-worker-id").value = id;
  form.querySelector(".wo-smr-worker-search").value = name;
  const results = form.querySelector(".wo-smr-worker-results");
  results.hidden = true;
  results.innerHTML = "";
}

export async function renderSmrWorkerSearch(input) {
  const form = input.closest(".wo-smr-line-form");
  const results = form.querySelector(".wo-smr-worker-results");
  form.querySelector(".wo-smr-f-worker-id").value = "";
  const q = input.value.trim();
  if (!q) {
    results.hidden = true;
    results.innerHTML = "";
    return;
  }
  const workers = await apiSmrSearchWorkers(q);
  if (input.value.trim() !== q) return; // a later keystroke owns the box now
  const exact = workers.some((w) => w.display_name.toLowerCase() === q.toLowerCase());
  results.innerHTML = workers
    .map((w) => `<button type="button" class="secondary-btn wo-smr-worker-result" data-action="smr-pick-worker" data-worker-id="${escapeHtml(w.id)}" data-worker-name="${escapeHtml(w.display_name)}">${escapeHtml(w.display_name)} <span class="hint">${escapeHtml(w.vendor)}</span></button>`)
    .join("") +
    (exact ? "" : `<button type="button" class="secondary-btn wo-smr-worker-result" data-action="smr-add-worker">Add "${escapeHtml(q)}" as a new worker</button>`);
  results.hidden = false;
}

// `msg` comes from the caller: setMessage clears the element's class, so it
// cannot be found by `.wo-message` once the delegation has reset it.
export async function handleSmrAction(action, btn, cardEl, msg) {
  const workOrderId = cardEl.dataset.id;
  const section = cardEl.querySelector(SECTION);
  const form = section.querySelector(".wo-smr-line-form");
  const lineOf = () => JSON.parse(btn.closest(".wo-smr-line").dataset.line);

  if (action === "smr-add-reading") {
    const v = (cls) => section.querySelector(`.${cls}`).value.trim();
    const printing = Number(v("wo-smr-r-printing"));
    if (!printing) {
      setMessage(msg, "Enter the printing number from the paper.", "error");
      return;
    }
    await apiSmrAddReading(workOrderId, {
      printing_no: printing,
      work_date: v("wo-smr-r-date") || null,
      hours_as_read: v("wo-smr-r-hours") || null,
      raw_note: v("wo-smr-r-note"),
    });
    await refreshCard(cardEl, SECTION);
  } else if (action === "smr-add-line") {
    fillLineForm(form, null);
    form.hidden = false;
  } else if (action === "smr-edit-line") {
    fillLineForm(form, lineOf());
    form.hidden = false;
  } else if (action === "smr-exclude-line") {
    fillLineForm(form, lineOf());
    form.querySelector(".wo-smr-f-status").value = "excluded";
    form.hidden = false;
    form.querySelector(".wo-smr-f-ground").focus();
  } else if (action === "smr-cancel-line") {
    form.hidden = true;
  } else if (action === "smr-save-line") {
    const payload = readLineForm(form);
    if (!payload.reason) {
      setMessage(msg, "Say why: the reason is kept with the line.", "error");
      return;
    }
    if (form.dataset.lineId) await apiSmrEditLine(form.dataset.lineId, payload);
    else await apiSmrAddLine(workOrderId, payload);
    await refreshCard(cardEl, SECTION);
  } else if (action === "smr-pick-worker") {
    pickWorker(form, btn.dataset.workerId, btn.dataset.workerName);
  } else if (action === "smr-add-worker") {
    const worker = await apiSmrAddWorker({
      display_name: form.querySelector(".wo-smr-worker-search").value.trim(),
      vendor: form.querySelector(".wo-smr-f-vendor").value,
    });
    pickWorker(form, worker.id, worker.display_name);
  } else if (action === "smr-generate-block") {
    await apiSmrGenerateBlock(workOrderId);
    await refreshCard(cardEl, SECTION);
  } else if (action === "smr-mark-pasted") {
    await apiSmrMarkPasted(btn.dataset.blockId);
    await refreshCard(cardEl, SECTION);
  } else if (action === "smr-ready" || action === "smr-not-ready") {
    // Reversible, so no confirm: Not ready clears the stamp the same way.
    await apiSetSmrReady(workOrderId, action === "smr-ready");
    await refreshCard(cardEl, SECTION);
  }
}
