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

const DOT_LABEL = "How this page works, you have not finished it yet";

export function repaintDots() {
  const role = getCurrentUser()?.role;
  const all = catalogue();
  for (const b of document.querySelectorAll(".tut-btn[data-tut-page]")) {
    const page = b.dataset.tutPage;
    const pending = all.some((e) => e.page === page && relevant(e, role) && !isDone(e.key));
    b.classList.toggle("tut-btn-dot", pending);
    if (pending) { b.setAttribute("aria-label", DOT_LABEL); b.title = DOT_LABEL; }
    else { b.removeAttribute("aria-label"); b.removeAttribute("title"); }
  }
}

export function installDots() {
  onChange(repaintDots);
  repaintDots();
}
