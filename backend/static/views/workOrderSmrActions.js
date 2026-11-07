// Work Orders: the `smr-*` branches of the card's click delegation.
// workOrderActions.js routes every `smr-` action but the paper check here; errors propagate to its shared catch and land in
// `.wo-message`. The markup is built in workOrderSmrLines.js.

import {
  apiSmrAddLine,
  apiSmrAddReading,
  apiSmrEditLine,
  apiSmrEditReading,
  apiSmrGenerateBlock,
  apiSmrMarkPasted,
  apiSetSmrReady,
} from "../api.js";
import { setMessage } from "../dom.js";
import { refreshCard } from "./workOrderList.js";
import { fillLineForm, fillReadingForm, readAddLineRow, readLineForm } from "./workOrderSmrLines.js";

const SECTION = ".wo-smr-section";

// `msg` comes from the caller: setMessage clears the element's class, so it
// cannot be found by `.wo-message` once the delegation has reset it.
export async function handleSmrAction(action, btn, cardEl, msg) {
  const workOrderId = cardEl.dataset.id;
  const section = cardEl.querySelector(SECTION);
  const form = section.querySelector(".wo-smr-line-form");
  const lineOf = () => JSON.parse(btn.closest(".wo-smr-line").dataset.line);

  if (action === "smr-add-reading") {
    const readingForm = section.querySelector(".wo-smr-reading-form");
    const v = (cls) => section.querySelector(`.${cls}`).value.trim();
    const printing = Number(v("wo-smr-r-printing"));
    if (!printing) {
      setMessage(msg, "Enter the printing number from the paper.", "error");
      return;
    }
    const payload = {
      printing_no: printing,
      work_date: v("wo-smr-r-date") || null,
      hours_as_read: v("wo-smr-r-hours") || null,
      raw_note: v("wo-smr-r-note"),
    };
    if (readingForm.dataset.readingId) await apiSmrEditReading(readingForm.dataset.readingId, payload);
    else await apiSmrAddReading(workOrderId, payload);
    await refreshCard(cardEl, SECTION);
  } else if (action === "smr-edit-reading") {
    const readingForm = section.querySelector(".wo-smr-reading-form");
    fillReadingForm(readingForm, JSON.parse(btn.closest(".wo-smr-reading").dataset.reading));
    readingForm.querySelector(".wo-smr-r-printing").focus();
  } else if (action === "smr-cancel-reading") {
    fillReadingForm(section.querySelector(".wo-smr-reading-form"), null);
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
  } else if (action === "smr-exclude-line" || action === "smr-charge-line") {
    // One tap each way, no ground and no confirm: Charge undoes Exclude and
    // the history row names the tap (user, 2026-11-06).
    const charge = action === "smr-charge-line";
    await apiSmrEditLine(lineOf().id, charge
      ? { status: "charged", exclusion_ground: null, reason: "charged on the card" }
      : { status: "excluded", reason: "excluded on the card" });
    await refreshCard(cardEl, SECTION);
  } else if (action === "smr-cancel-line") {
    form.hidden = true;
  } else if (action === "smr-save-line") {
    const payload = readLineForm(form);
    if (!payload.reason) {
      setMessage(msg, "Say why: the reason is kept with the line.", "error");
      // The card message sits above a long form, off-screen: flag the field too.
      form.querySelector(".wo-smr-f-reason").reportValidity();
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
