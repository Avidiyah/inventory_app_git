# Design System

The TechFM front-end's visual language: palette, surface types, and the rules
for picking one, so new UI matches what's already shipped instead of
reinventing it per-page.

**This file is living.** A change that adds a new surface type, a new token,
or overturns a rule below updates this file in the same commit.

Sources of truth, in the order to trust them: `backend/static/styles.css`
`:root` (the actual token values), then this file (the *why* and *when*).
Don't duplicate hex values here — reference the token name and grep it.

---

## Brand

TechFM (Technological Facilities Maintenance), styled after Belfor Property
Restoration: **red / black / white**, with gray as the neutral connective
tissue between them. `--color-brand` (`#C8102E`) is the one red — don't
introduce a second brand red.

- **Red = primary / brand action** (Sign In, Save, Scan). Not "the delete
  color" — destructive actions are distinguished by *treatment*
  (outline/ghost, warning icon, confirmation step), never by hue.
- **Status accents** (`--status-stock` green, `--status-dispense` amber,
  `--status-adjust` blue) are a deliberate, narrow exception, kept only on
  `.type-badge.*` and stock/dispense affordances because inventory direction
  is operationally meaningful on a jobsite. Everywhere else stays
  red/black/white/gray.

## The canvas

The app background is dark: `--color-canvas` (`#1C1D20`), set on `body`, with
the logo ring at 9.5% alpha (`app-bg.png`) bled off the top-right corner. It was
`--gray-50` until the panels and the page were found to be the same value —
every screen read as one undifferentiated white sheet, and the black header
floated on it like an unrelated stripe. Dark gives the white panels a ground
to sit on and makes the header continuous with the page, which is the same
dark-field/lifted-panel logic the login screen already used.

**If you put something directly on the canvas, tone it for dark**: light text
(`--gray-400` or lighter — `--gray-700` and `--color-ink` disappear),
translucent-white hairlines rather than `--gray-200`, and never `--color-brand`
as *text* (it's ~2.6:1 on the canvas, under the 4.5:1 minimum — carry the red
in a rule or underline and keep the label white). The header nav's dark idiom
in `.nav-btn` is the reference. Better still: put it in a panel.

The watermark is `background-attachment: fixed` only under `@media (pointer:
fine)`. Fixed backgrounds force a full repaint per scroll frame in iOS Safari,
which is the device class that can least afford it.

## Two surface types

The app has exactly two ways to present a panel of content. Both are dark and
translucent; they differ in what they sit on, which changes the arithmetic.

### Frosted panel (default — nearly everything)

`--panel-bg` over the canvas, `--glass-blur`, `--panel-border` hairline,
`--text-panel` / `--text-panel-mute` text, `--shadow-panel` for lift. This is
every table, form, card, and modal in the working app.

> **Rule change (owner decision, superseding "don't use dark glass for working
> UI").** This file previously reserved translucent dark surfaces for brand and
> photo moments and required flat white panels for the working app, on the
> grounds that dense inventory data is more legible dark-on-light in jobsite
> glare. That concern still stands and is worth revisiting if the field reports
> trouble — but the owner chose the frosted treatment app-wide for visual
> consistency with the login screen, so frosted is now the default.

**Frost on a dark ground is a *light* film, not a dark one.** This is the trap:
`--glass-bg` is `rgba(20,20,20,.75)`, which is *darker* than `--color-canvas`.
Composited over the canvas it lands on ~`#191A1C` — the canvas — and the panel
vanishes. It works on the login screen only because that sits over a bright
logo. Never reuse the `--glass-*` tokens for a panel on the canvas; use the
`--panel-*` set, which is white at low alpha.

Nesting has its own tokens, since each layer composites onto the last:
`--panel-nested` for a card inside a panel, `--panel-well` for an inset fill or
zebra row, `--panel-hover`, and `--panel-rule` / `--panel-rule-soft` for
hairlines. `--border` resolves to `--panel-rule`; `--border-input` stays an
opaque gray because it is drawn against a white input.

**Inputs stay white with dark text** on every surface (see below) — so
`--color-ink`, `--gray-50` and friends are still correct *inside* a control.
They are no longer correct for a panel. `--gray-50` in particular no longer
means "page"; nothing uses it as a page background.

### Dark glass (brand/photo moments only)

Translucent dark panel over a full-bleed photo or brand-art background —
currently just the login screen. Tokens: `--glass-bg`, `--glass-blur`,
`--glass-border`, `--glass-shadow`. Example (`#login-section` in
`styles.css`):

```css
background-color: var(--glass-bg);
backdrop-filter: blur(var(--glass-blur));
-webkit-backdrop-filter: blur(var(--glass-blur));
border: 1px solid var(--glass-border);
box-shadow: var(--glass-shadow);
```

**The blur is load-bearing, not decorative.** Opacity alone over a busy image
leaves text illegible — the backdrop blur is what buys the legibility back at
low opacity. Don't ship `--glass-bg` without `--glass-blur` beside it. The same
applies to the frosted panel, for a different reason: the blur settles the
watermark showing through so text sits on an even field rather than a moving
edge.

## Color on a dark surface

Contrast is measured against the *composited* panel (`#2A2B2D`), not the
canvas. Three colors could not survive the flip as text and have lifted
variants; the originals are kept for fills, where white-on-color is unaffected:

| Used as text | Original | On panel | Lifted variant | On panel |
|---|---|---|---|---|
| Brand red | `--color-brand` `#C8102E` | 2.4:1 | `--color-brand-light` `#FF7585` | 5.5:1 |
| Amber | `--status-dispense` `#D97706` | 3.8:1 (nested) | `--status-dispense-text` `#F5A524` | 5.9:1 |
| Blue | `--status-adjust` `#2563EB` | 2.3:1 | `--status-adjust-text` `#7DA6FF` | 5.1:1 |

`--color-brand-light` is **not a second brand red** — same hue, lifted
lightness, for red text and outlines only. Solid red fills keep `--color-brand`.

`--color-success` and `--color-error` are only ever text or a left-accent rule,
never a fill, so those two tokens moved wholesale (`#45D07E`, `#FF7585`) rather
than gaining variants. The `.type-badge.*` hues are untouched: they are
backgrounds carrying white text, which the dark canvas does not affect.

### Text on dark glass

`#login-section` is itself a `<section>`, so it now inherits the frosted
panel's `color: var(--text-panel)` — which is why the overrides below stopped
being load-bearing. They were written when the global `label` / `h1` / `h2`
rules set near-black text for light panels; the global default is light now, so
the white ones are near-no-ops. `h2`'s `--gray-200` still does something real,
holding the subtitle a step dimmer than `--text-panel`. All three are kept:
they cost nothing and keep the login card self-describing if the panel defaults
move again.

```css
#login-section label { color: var(--color-white); }
#login-section h1    { color: var(--color-white); }
#login-section h2    { color: var(--gray-200); }
```

The technique still matters even though this instance no longer needs it: when
a surface disagrees with the global default, **scope the override to that
surface's container** rather than editing the global rule.

If a shared dynamic-message pattern (`.error`/`.success` classes set via
`setMessage()`) needs a neutral-state color on a dark surface, scope with
`:not()` rather than a bare `#id` selector — an ID's specificity otherwise
silently wins over `.error`/`.success` even when those classes are present,
which would strip the red/green color coding:

```css
#login-section #login-message:not(.error):not(.success) { color: var(--gray-200); }
```

Inputs (`input`, `select`) keep their normal white background + dark text on
*any* surface, glass included — that's the standard convention for a form on
a dark card, and it's what keeps typed text legible without a parallel
dark-input variant.

## Brand art assets

Source art (logo lockups, background photography) gets dropped at the repo
root by the owner as reference/raw material — it is **not served** by the
app. Only files under `backend/static/` are served; the root copy is
disposable once the derived asset is generated. When generating a derived
asset from it:

- Favicon / touch icons: crop tight to the mark's bounding box with a small
  margin, pad to square on the source's own background color (not a fixed
  color), then downscale per target (`favicon.ico` browser tab,
  `icon-180.png` iOS home screen, `icon-512.png` other install surfaces).
  iOS caches the touch icon at install time — an already-installed user needs
  to remove and re-add the home-screen icon to see a new one; there's no way
  to push it remotely.
- Full-bleed backgrounds (e.g. `login-bg.jpg`): downscale to roughly the
  largest viewport size actually needed (~1600px) and recompress — source
  photography lands at multi-MB, which is wasted weight on a login screen.
- Washed watermarks (`app-bg.png`): bake the opacity into the alpha channel
  (`colorchannelmixer=aa=0.0945`) and keep the PNG at the source's own
  resolution — do **not** pre-upscale. Upscaling a smooth shape multiplies the
  file size roughly tenfold (256px → 28 KB, 1024px → 333 KB) to buy edge
  detail that is invisible at 7% alpha anyway. Let CSS `background-size` do
  the enlarging.

`ffmpeg` (already on this machine) handles both: `crop`/`pad` for icon
framing, `scale` + `-q:v` for background recompression.
