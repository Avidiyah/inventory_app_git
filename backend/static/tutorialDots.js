// Red dot on the "How this page works" buttons (0b spec 5.5). Layer: shared
// helper; reads the progress cache and the catalogue, writes only a class and
// two attributes on buttons tutorial.js already placed (no inline style: CSP).
//
// A button is dotted while any script on its page that is relevant to the
// signed-in role is not completed. With nobody signed in nothing is relevant,
// so a signed-out (or cleared) screen shows no dot. A "starter" has no page
// button, so it never counts here.

import { getCurrentUser } from "./state.js";
import { isDone, onChange } from "./tutorialProgress.js";
import { catalogue } from "./tutorials/catalogue.js";
import { relevant } from "./tutorials/relevance.js";
import { TUTORIALS } from "./tutorials/index.js";
import { isTutorialRunning, pickScript } from "./tutorial.js";

const DOT_LABEL = "How this page works, you have not finished it yet";

export function repaintDots() {
  const role = getCurrentUser()?.role;
  const all = catalogue();
  for (const b of document.querySelectorAll(".tut-btn[data-tut-page]")) {
    const page = b.dataset.tutPage;
    const pending = all.some((e) => e.page === page && relevant(e, role) && !isDone(e.key));
    // Finished = out of sight on that tab; replay lives in Hub → Tutorials → Completed.
    const scripts = TUTORIALS[page]?.scripts;
    b.hidden = Boolean(role && scripts?.length && isDone(pickScript(scripts, role).key));
    b.classList.toggle("tut-btn-dot", pending);
    if (pending) { b.setAttribute("aria-label", DOT_LABEL); b.title = DOT_LABEL; }
    else { b.removeAttribute("aria-label"); b.removeAttribute("title"); }
  }
}

export function installDots() {
  onChange(repaintDots);
  // Tab switches and page changes are clicks: repaint once they have landed.
  // ponytail: repaints on every click (a few querySelectors); hook tab changes directly if it ever shows up in a profile.
  // Not mid-tour: a tour's own taps must not reshuffle the page under it.
  // One listener per document: a re-install (tests reload modules) replaces the old one.
  const onClick = () => setTimeout(() => { if (!isTutorialRunning()) repaintDots(); });
  document.__tutDotsOff?.();
  document.addEventListener("click", onClick, true);
  document.__tutDotsOff = () => document.removeEventListener("click", onClick, true);
  repaintDots();
}
