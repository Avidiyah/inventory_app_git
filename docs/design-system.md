# Design System

The TechFM front-end's visual language. Living file: a change that adds a surface type or token, or overturns a rule, updates it in the same commit.

Sources of truth: `backend/static/styles.css` `:root` (token values), then this file (the why and when). Don't duplicate hex values here beyond the contrast table.

## Brand

TechFM, styled after Belfor: **red / black / white**, gray as neutral. `--color-brand` is the one red; no second brand red.

- **Red = primary action** (Sign In, Save, Scan), not "delete". Destructive actions differ by treatment (outline/ghost, warning icon, confirm step), never hue.
- **Status accents** (`--status-stock` green, `--status-dispense` amber, `--status-adjust` blue) live only on `.type-badge.*` and stock/dispense affordances. The SMR27 tiles' stage outlines (red / amber / neutral / green / muted) are the one other exception.

## The canvas

App background is dark: `--color-canvas` on `body`, logo watermark (`app-bg.png`) bled off the top-right. The watermark is `background-attachment: fixed` only under `@media (pointer: fine)`; fixed backgrounds force a repaint per scroll frame on iOS Safari.

Anything placed directly on the canvas must be toned for dark: light text (`--gray-400` or lighter), translucent-white hairlines, and never `--color-brand` as text (about 2.6:1). Carry red in a rule or underline. Better: put it in a panel. Reference idiom: `.nav-btn`.

## Two surface types

### Frosted panel (default)

`--panel-bg` over the canvas, `--glass-blur`, `--panel-border`, `--text-panel` / `--text-panel-mute`, `--shadow-panel`. Every table, form, card, modal. Inputs use `--input-bg` and `--text-panel` too.

**Trap: frost on a dark ground is a light film.** `--glass-bg` is darker than the canvas, so a panel built from it vanishes. Never use `--glass-*` for a panel on the canvas; use the `--panel-*` set (white at low alpha).

Nesting tokens: `--panel-nested` (card in a panel), `--panel-well` (inset fill, zebra row), `--panel-hover`, `--panel-rule` / `--panel-rule-soft` (hairlines).

- `input:-webkit-autofill` needs the inset box-shadow override in `styles.css`; no background rule beats the forced light fill.
- Native `<select>` popups are OS-drawn and can ignore page CSS. Use `static/menus.js` for any new dropdown: `actionMenuHtml()` (fire-and-close command menu) or `comboHtml()` (value picker, hidden real `<select>` holds the value). Every `.menu-*` rule must out-specify the global `button` style (solid brand red).

### Dark glass (brand/photo moments only)

Translucent dark panel over a full-bleed photo; currently only `#login-section`. Tokens `--glass-bg`, `--glass-blur`, `--glass-border`, `--glass-shadow`. The blur is load-bearing: opacity alone over a busy image is illegible, so never ship `--glass-bg` without `--glass-blur`. The frosted panel blurs for a related reason: it settles the watermark into an even field.

When a surface disagrees with a global color default, scope the override to that surface's container rather than editing the global rule. For neutral message color on a dark surface, use `:not(.error):not(.success)`; a bare `#id` selector out-specifies `.error`/`.success` and strips the coding.

## Color on a dark surface

Contrast is measured against the composited panel (`#2A2B2D`). Three colors fail as text and have lifted variants; originals stay for fills (white-on-color is unaffected):

| Used as text | Original | On panel | Lifted variant | On panel |
|---|---|---|---|---|
| Brand red | `--color-brand` `#C8102E` | 2.4:1 | `--color-brand-light` `#FF7585` | 5.5:1 |
| Amber | `--status-dispense` `#D97706` | 3.8:1 | `--status-dispense-text` `#F5A524` | 5.9:1 |
| Blue | `--status-adjust` `#2563EB` | 2.3:1 | `--status-adjust-text` `#7DA6FF` | 5.1:1 |

`backend/tests/test_menu_parity.py` computes these from the `:root` tokens; a token under 4.5:1 fails the suite. `--color-brand-light` is the same red lifted, for text and outlines only; solid fills keep `--color-brand`. `--color-success` / `--color-error` are text or left-accent rules only, never fills.

### Work-order status charts

The User Hub Graphs tab is the sole categorical-color exception; it may reuse the seven `--wo-status-*` tokens. A pie tile shows its total under one shared status key; in the pop-up the pie needs an adjacent text legend (status, count, percentage). Color, hover, and a pointer are never required to read a value. Other charts stay single-series or text-first unless this policy is amended.

Each chart is a tile opening a pop-up (`.modal-overlay.hub-graph-sheet`): full-screen on phone, centred panel otherwise, page behind locked. Only the red X (or Esc / Back) closes it.

### Work-order cards

Status pills fill from `--wo-status-*`, always carry a glyph (`views/workOrderGlyphs.js`), never color alone, and clear 4.5:1 (`tests/frontend/unit/workOrderContrast.test.js`).

## Mobile layout

At 600px and below, UserHub Home splits attendance and work-order tracking into separate labeled cards and shows counts in two columns.

## Field-help tooltips

A `?` tooltip is for a non-obvious domain rule people need mainly while learning. Keep a visible `.hint` when the guidance is needed every time or prevents a costly mistake. Tooltips supplement labels, never replace them.

Static markup: `.tip-btn[data-tip="<key>"]` inside the label or heading; JS: `tipHtml("<key>")`. Copy lives in `backend/static/tips.js`, plain text, one to three short sentences. Never nest a trigger inside a `<button>` or `<summary>`, or add a second interactive descendant to a label that wraps a control; use a scoped wrapper keeping label and trigger as siblings, or omit it.

## Loading states

A DB-backed view shows shape-matched skeletons while its fetch is in flight, never bare "Loading...". Use the helpers in `backend/static/skeleton.js` (`skeletonTableRows`, `skeletonCard`, `skeletonList`); never hand-write `.skel-*` HTML. Colors reuse panel tokens. The pulse is removed outright under `prefers-reduced-motion: reduce`. Each block carries an `.sr-only` "Loading..." and `aria-hidden` bars.

Skeletons are for a fetch, not for in-memory filtering or sorting; transient `setMessage(el, "Loading...")` beside rendered content stays text.

## Brand art assets

Source art dropped at the repo root is raw material, not served; only `backend/static/` is served. Derive with `ffmpeg`:

- Favicon / touch icons: crop to the mark with a small margin, pad to square on the source's own background, downscale per target (`favicon.ico`, `icon-180.png`, `icon-512.png`). iOS caches the touch icon at install; users must remove and re-add it to see a change.
- Full-bleed backgrounds (`login-bg.jpg`): downscale to about 1600px and recompress.
- Watermarks (`app-bg.png`): bake opacity into alpha (`colorchannelmixer=aa=0.0945`) at the source's own resolution. Do not pre-upscale (about tenfold file size for detail invisible at that alpha); let CSS `background-size` enlarge.
