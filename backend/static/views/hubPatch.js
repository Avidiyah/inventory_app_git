// View helper: the one way a User Hub tab paints (W7 rule 1).
//
// Layer: views. Builds the new markup detached and patches the mount in place
// with morph.js, so what the user has open, focused or typed survives a live
// update (rule 2) and a changed tile glows once (rule 8). Skeleton and error
// panels may still replace a mount outright when nothing good is on screen.

import { isDirty, keepPlace, morphInto } from "../morph.js";

const ALWAYS_SKIP = ".punch-editor, [data-live-skip]";

export function patchHub(mount, html, { flashSelector = null, flashKey, skipSelector = null } = {}) {
  const fresh = document.createElement("div");
  fresh.innerHTML = html;
  const skip = (old) => old === document.activeElement
    || (old.matches("input, select, textarea") && isDirty(old))
    || old.matches(ALWAYS_SKIP)
    || Boolean(skipSelector && old.matches(skipSelector));
  const restore = keepPlace(mount);
  morphInto(mount, fresh.childNodes, { flashSelector, skip, ...(flashKey ? { flashKey } : {}) });
  restore();
}
