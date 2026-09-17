// Foundation: local persistence for a work-order edit interrupted by a
// dropped connection or a forced session-expiry login.
//
// Layer: foundation (no DOM, no api.js import) -- callers own how a stored
// action is replayed. A draft is written at the moment a save is attempted,
// not on every keystroke, so it captures exactly the payload that failed.
// It survives a page reload or a trip through the login screen (both just
// localStorage, not memory), which is what lets a reconnect or a re-login
// finish the save without the operator retyping anything.

const PREFIX = "wo-draft:";
const RESUME_KEY = "wo-draft-resume";

// The draft-eligible editor sections and the selector each lives at. A
// string constant rather than DOM access, so it's safe for this no-DOM
// module to own -- both workOrderRetry.js and workOrderRouting.js need the
// same mapping and must not import each other (see workOrderRouting.js's
// header on the list/routing import cycle).
export const SECTION_SELECTOR = {
  details: ".wo-edit-card",
  notes: ".wo-notes-section",
  materials: ".wo-materials-section",
  labor: ".wo-labor-section",
};

function draftKey(workOrderId, section) {
  return `${PREFIX}${workOrderId}:${section}`;
}

function readJson(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    // Private browsing, quota, or a corrupt value -- treat it as "nothing
    // saved" rather than let storage trouble break the save flow itself.
    return null;
  }
}

function writeJson(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Best-effort. The in-memory save the caller is making still goes
    // through; only the offline-recovery path is degraded.
  }
}

// `action` names an entry in workOrderRetry.js's own replay table, so this
// module never has to import api.js. `targetId` is the labor/item row being
// edited, or null when the action creates one.
export function saveDraft(workOrderId, section, { number, action, targetId = null, payload }) {
  writeJson(draftKey(workOrderId, section), { number, action, targetId, payload, savedAt: Date.now() });
}

export function readDraft(workOrderId, section) {
  return readJson(draftKey(workOrderId, section));
}

export function clearDraft(workOrderId, section) {
  writeJson(draftKey(workOrderId, section), null);
}

// A retry that reached the server and was actively rejected (not just
// unreachable) stops auto-retrying -- otherwise a permanent 4xx would replay
// forever on every reconnect. The draft itself is kept, so its section still
// shows what was attempted next time it's opened.
export function markDraftError(workOrderId, section, err) {
  const key = draftKey(workOrderId, section);
  const draft = readJson(key);
  if (!draft) return;
  writeJson(key, { ...draft, lastError: { status: err?.status ?? null, detail: err?.detail ?? null } });
}

// Every stored draft, for the reconnect/boot replay sweep.
export function allDrafts() {
  const out = [];
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key || !key.startsWith(PREFIX)) continue;
      const [, workOrderId, section] = key.split(":");
      const draft = readJson(key);
      if (draft) out.push({ workOrderId, section, ...draft });
    }
  } catch {
    // Storage unavailable -- nothing to replay this pass.
  }
  return out;
}

// One-shot: which work order + section to reopen after a forced re-login.
export function setPendingResume(resume) {
  writeJson(RESUME_KEY, resume);
}

// Read-only peek used by the boot deep-link check, which only needs the
// number and must not consume the resume before the card page it opens has
// had a chance to apply the section + drafted fields.
export function peekPendingResumeNumber() {
  return readJson(RESUME_KEY)?.number ?? null;
}

export function takePendingResume() {
  const resume = readJson(RESUME_KEY);
  writeJson(RESUME_KEY, null);
  return resume;
}
