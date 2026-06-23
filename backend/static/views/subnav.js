// View helper: in-page sub-navigation (the "one feature visible, rest
// hidden" convention).
//
// Layer: views (no fetch, no state). The page-level twin of
// `nav.js::showPage`: where `showPage` swaps between top-level `.page`
// sections via the black header nav, this swaps between *features within
// one page* via a secondary `.sub-nav` bar.
//
// Convention (see docs/interfaces.md "In-page sub-navigation"):
//   <div class="page" id="x-page">
//     <nav class="sub-nav" aria-label="…">
//       <button class="sub-nav-btn active" data-feature="a">A</button>
//       <button class="sub-nav-btn"        data-feature="b">B</button>
//     </nav>
//     <section class="feature-panel" data-feature="a">…</section>
//     <section class="feature-panel" data-feature="b" hidden>…</section>
//   </div>
//
// Exactly one `.feature-panel` is shown at a time; its matching
// `.sub-nav-btn` carries `.active`. Contextual overlays (an item editor, a
// correction form) are NOT features — they are sub-flows reached from
// within a feature and stay as their own hidden sections; the host page
// closes them on a feature switch via the `onShow` hook.

// Wire a page's sub-nav and return a `{ showFeature }` handle.
//
// `pageEl`     — the `.page` element owning the sub-nav and panels.
// `onShow`     — optional `(feature, prevFeature) => void`, fired after each
//                switch (including the initial one, with `prevFeature = null`).
//                The host uses it for feature-specific lifecycle: stopping a
//                camera when leaving a Scan feature, closing overlays, etc.
// `fireInitialOnShow` — when false, the initial switch at init still sets the
//                DOM (active panel/button) but does NOT call `onShow`. Use this
//                when the host's `onShow` would do work that must not run at
//                module-load time — e.g. History's hook fetches a page, which
//                must wait until the user has logged in and opened the page.
//
// The active feature is recorded on `pageEl.dataset.activeFeature` so the
// host can read it and the switch is idempotent (re-selecting the current
// feature is a no-op).
export function initSubNav(pageEl, { onShow, fireInitialOnShow = true } = {}) {
  const nav = pageEl.querySelector(".sub-nav");
  const buttons = Array.from(pageEl.querySelectorAll(".sub-nav-btn"));
  const panels = Array.from(pageEl.querySelectorAll(".feature-panel"));

  // `silent` suppresses the onShow callback for the initial DOM sync only;
  // user-driven switches always notify.
  function showFeature(name, { silent = false } = {}) {
    const prev = pageEl.dataset.activeFeature || null;
    if (prev === name) return;

    panels.forEach(panel => { panel.hidden = panel.dataset.feature !== name; });
    buttons.forEach(btn => btn.classList.toggle("active", btn.dataset.feature === name));
    pageEl.dataset.activeFeature = name;

    if (!silent && typeof onShow === "function") onShow(name, prev);
  }

  if (nav) {
    nav.addEventListener("click", (event) => {
      const btn = event.target.closest(".sub-nav-btn");
      if (btn && btn.dataset.feature) showFeature(btn.dataset.feature);
    });
  }

  // Initialise to the button pre-marked `.active` in the markup, else the
  // first button — so the page boots showing exactly one feature even
  // before the user touches the sub-nav.
  const initial = buttons.find(b => b.classList.contains("active")) || buttons[0];
  if (initial && initial.dataset.feature) {
    showFeature(initial.dataset.feature, { silent: !fireInitialOnShow });
  }

  return { showFeature };
}
