// Work Orders: the `smr-*` branches of the card's click delegation.
// workOrderActions.js routes every `smr-` action but the paper check here; errors propagate to its shared catch and land in
// `.wo-message`. The markup is built in workOrderSmrLines.js.

import {
  apiSmrAddLine,
  apiSmrAddReading,
  apiSmrEditLine,
  apiSmrGenerateBlock,
  apiSmrMarkPasted,
  apiSetSmrReady,
} from "../api.js";
import { setMessage } from "../dom.js";
import { refreshCard } from "./workOrderList.js";
import { fillLineForm, readAddLineRow, readLineForm } from "./workOrderSmrLines.js";

const SECTION = ".wo-smr-section";

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
    const payload = readAddLineRow(section);
    if (!payload.hours_each) {
      setMessage(msg, "Enter the hours each person worked.", "error");
      return;
    }
    await apiSmrAddLine(workOrderId, payload);
    await refreshCard(cardEl, SECTION);
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
