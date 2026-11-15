// Work Orders: a save someone else beat you to (W3).
//
// Layer: beside workOrderActions.js. A protected save that the server refuses
// with 409 `field_conflict` lands here: the card's kept message line
// (`#wo-sec-msg`, `data-live-keep`, so a live patch leaves it alone) names who
// changed what and how long ago, and offers Keep theirs / Save mine. Each save
// path supplies what those two mean for its own fields.

const pending = new WeakMap();
const ages = new Intl.RelativeTimeFormat("en", { numeric: "always" });

export function isFieldConflict(err) {
  return err?.status === 409 && err.detail?.code === "field_conflict";
}

// The server sends the age (a phone's clock may be wrong); this only words it.
export function conflictAge(seconds) {
  if (seconds < 60) return ages.format(-seconds, "second");
  if (seconds < 3600) return ages.format(-Math.floor(seconds / 60), "minute");
  if (seconds < 86400) return ages.format(-Math.floor(seconds / 3600), "hour");
  return ages.format(-Math.floor(seconds / 86400), "day");
}

export function conflictSentence({ label, current_label: value, changed_by: who, seconds_ago: seconds }) {
  if (seconds === null || seconds === undefined) return `Someone else changed ${label} to ${value}.`;
  if (!who) return `${label} was changed to ${value} ${conflictAge(seconds)}.`;
  return `${who} changed ${label} to ${value} ${conflictAge(seconds)}.`;
}

// Static markup (no data in it): the action audit reads these data-action
// literals, and a live patch never touches the kept line they sit in.
const ACTIONS_HTML =
  `<button type="button" id="wo-act-keep-theirs" data-action="keep-theirs-wo">Keep theirs</button>` +
  `<button type="button" id="wo-act-save-mine" data-action="save-mine-wo">Save mine</button>`;

// `keep(conflicts)` / `retry(conflicts)` come from the save path. Without them
// (a draft replayed on reconnect) the sentence shows alone.
export function showConflict(cardEl, conflicts, { keep, retry } = {}) {
  const msg = cardEl.querySelector("#wo-sec-msg");
  if (!msg) return;
  const text = document.createElement("span");
  text.className = "wo-conflict-text";
  text.textContent = conflicts.map(conflictSentence).join(" ");
  msg.replaceChildren(text);
  msg.className = "error";
  if (!keep || !retry) {
    pending.delete(cardEl);
    return;
  }
  const actions = document.createElement("div");
  actions.className = "wo-conflict-actions";
  actions.innerHTML = ACTIONS_HTML;
  msg.append(actions);
  pending.set(cardEl, { conflicts, keep, retry });
}

// One choice per conflict message: the entry is taken on the first tap, so a
// double tap cannot send twice.
export async function resolveConflict(cardEl, choice) {
  const entry = pending.get(cardEl);
  if (!entry) return;
  pending.delete(cardEl);
  const msg = cardEl.querySelector("#wo-sec-msg");
  msg?.querySelectorAll("button").forEach((b) => { b.disabled = true; });
  if (msg) {
    msg.replaceChildren();
    msg.className = "";
  }
  if (choice === "keep") entry.keep(entry.conflicts);
  else await entry.retry(entry.conflicts);
}
