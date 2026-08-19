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

## Two surface types

The app has exactly two ways to present a panel of content. Pick by asking
"is this sitting on the working app chrome, or on a full-bleed brand image?"

### Flat panel (default — nearly everything)

Opaque `--color-white` (or `--gray-50`) background, `--color-ink` text,
`--shadow-sm`/`--shadow-card`/`--shadow-md` for lift, `--border`/
`--border-input` hairlines. This is every table, form, card, and modal in the
working app. Use it unless you have a specific reason not to.

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
low opacity. Don't ship `--glass-bg` without `--glass-blur` beside it.

**Don't use dark glass for working UI** (tables, forms, the main app shell).
It exists specifically for moments where a brand image is the point and the
UI is a light overlay on top of it. Reach for a flat panel otherwise.

### Text on dark glass

`--color-ink`, the default `label` color, and `.password-toggle-btn`'s
`--gray-500` all assume dark text on a light flat panel — they read as
invisible on dark glass. When you add a dark-glass surface, **scope
overrides to that surface's container**, don't touch the global rules (which
are correct for every flat panel elsewhere):

```css
#login-section label { color: var(--color-white); }
#login-section h1    { color: var(--color-white); }
#login-section h2    { color: var(--gray-200); }
```

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

`ffmpeg` (already on this machine) handles both: `crop`/`pad` for icon
framing, `scale` + `-q:v` for background recompression.
