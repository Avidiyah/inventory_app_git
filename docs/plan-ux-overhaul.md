# Plan: Frontend UX Overhaul

Status: **Deferred — not in active development.** Captured here so
the constraints and ideas aren't lost while the team focuses on
live-capture barcode scanning. Revisit after live capture ships and
stabilises.

---

## User context

The primary users of this app are **construction workers on jobsites**.
Assume:

- Limited fluency with electronic devices.
- Phones used one-handed, often with gloves, often in poor lighting.
- Workflow interruptions are frequent — anything that requires
  multi-step focus is going to fail in the field.
- Errors must be recoverable without understanding *why* they happened.

The current UI was designed without this constraint front-of-mind.
It works, but it asks more of the user than this audience can
reliably give.

---

## Principles for the overhaul

1. **One obvious action per screen.** Whatever the user is most
   likely to do should be the largest, highest-contrast element. No
   hunting.
2. **Plain-language messages.** Replace developer-speak with
   instructions:
   - "Permission denied" → "Tap allow when your phone asks to use the
     camera."
   - "Could not connect to the server." → keep, but pair with "Check
     your signal and try again."
   - "No barcode found in that image." → "Couldn't read that
     barcode. Try moving closer or holding steadier."
3. **Large hit targets.** Minimum 44×44 px (Apple HIG) — bigger is
   better with gloves. Spacing between adjacent buttons matters as
   much as size.
4. **Autofocus the next field.** If the user just scanned an item,
   the quantity field should already have keyboard focus when the
   transaction bar opens.
5. **Defaults over choices.** "Stock (add)" vs "Dispense (remove)"
   should preselect the most common action for the page. If we don't
   know which is more common, instrument it and find out.
6. **No silent failures.** Every error path produces a visible
   message in the same place the user was looking.
7. **No multi-step modals.** A transaction is one screen, not a wizard.

---

## Concrete ideas surfaced during live-capture discussion

These are starting points for the overhaul, not commitments.

- **Camera-default on Transaction page.** "Use Camera" is the
  visible affordance; upload is the fallback for the rare desktop
  case, not a co-equal option.
- **Aim-box overlay must be unambiguous.** Thick high-contrast
  border, no clever styling, sized to typical 1D-barcode aspect.
- **Transaction bar that pops up post-scan** should:
  - Cover most of the screen so it's clearly the active surface.
  - Have the quantity field already focused.
  - Have a Save button that is obviously the primary action, and a
    Cancel that is obviously secondary (size, position, colour all
    contribute).
  - Close cleanly back to the live camera view so the next scan is
    one motion away.
- **Permission-denied recovery.** A button or link that opens a
  short visual guide for re-enabling camera access in iOS Safari and
  Android Chrome — the two browsers that actually matter for this
  audience.
- **No-camera fallback** is the existing upload flow, unchanged.
- **Empty/error states need illustrations or icons**, not just text.
  Construction workers reading dense paragraphs on a phone in
  sunlight isn't realistic.

---

## Not in scope here

- Live camera capture itself — tracked in
  [docs/plan-live-capture.md](docs/plan-live-capture.md).
- Additional barcode formats.
- Backend changes of any kind (auth, schema, services, routes).
- New roles or permission model changes.
- Internationalisation.

---

## When to revisit

- After live capture ships and has been used in the field for at
  least a few weeks.
- When concrete UX failure reports come in from supervisors (those
  reports should be logged into this doc as they arrive, so the
  overhaul has real data to design against rather than guesses).
- Before any major audience expansion (new role, new site, new
  workflow).
