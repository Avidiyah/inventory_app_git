# Message bubble — design

Approved by the user 2026-11-24 from a clickable preview. Covers the floating
bubble only; the message panel, the data model and the feature set are a
separate spec (live messaging), still being worked out.

## Intent

A way into messages that is always one tap away on every TechFM page, in the
style of a chat head. A true over-other-apps bubble is impossible for a web
app (Android-native permission, never on iOS), so the bubble lives inside
TechFM. Push notifications cover the app-closed case.

## Behaviour

| Part | Rule |
|---|---|
| Where | Fixed over every page once signed in. Hidden while a tutorial is playing. |
| Drag | Pointer drag anywhere on screen. Under 6 px of movement is a tap, not a drag. |
| Snap | On release it slides to the nearest left or right edge, keeping its height. |
| Tap | Opens the message panel (other spec). |
| Trashcan | Appears bottom-centre only while dragging; grows and turns red when the bubble is over it. Dropping there hides the bubble until the next sign-in. |
| Fallback | A Messages tab in the User Hub, always present, bubble or not. |
| Position | Side + height remembered per device (assistant's call). |
| Resize / rotate | Re-snaps to the remembered side, clamped on screen. |

## Look

| Part | Value |
|---|---|
| Size | 56 px circle, 8 px gap from the edge, same on phone and desktop |
| Fill | See-through with a faint dark tint (`rgba(20,20,20,.18)`, 2 px blur) so it holds up over white cards |
| Outline | 2 px white |
| Inside | `logo-mark.png` at 68% |
| Glow, nothing unread | Dark red: `0 0 10px 2px rgba(110,8,24,.85), 0 0 22px 6px rgba(110,8,24,.45)` |
| Glow, unread | Bright red: `0 0 12px 3px rgba(255,40,70,.95), 0 0 28px 10px rgba(255,40,70,.6)`, slow 2.4 s pulse; no pulse under reduced-motion |
| Badge | Count of distinct people with unopened messages to you; brand-red pill, white 2 px ring; hidden at 0; "9+" past nine (assistant's call) |
| Badge corner | Top corner on the side facing away from the edge the bubble sits on |
| Trashcan | 64 px dark-glass circle, white bin icon, 24 px above the bottom safe area |

## Constraints

- CSP drops `style=` attributes: position goes through CSSOM
  (`element.style.transform`), states through classes.
- The bubble is a `<button>` with an aria-label that reads the unread count;
  keyboard users reach messages through it or the Hub tab.
- Must never cover a tutorial, and must not sit above modal pop-ups.

## Approaches

| Option | Trade-off | Verdict |
|---|---|---|
| In-app bubble + push | Works today on every device | **Picked** |
| Native Android wrapper for a real chat head | Separate app, store release, nothing on iOS | Rejected by the user |
| Hub tab only | No always-there entry point | Kept as the fallback, not the main door |

## Left to the builder

- Which storage holds the remembered position and the "put away" flag (the
  flag must clear on sign-in).
- How "a tutorial is playing" is read from the existing tutorial player.
- Stacking order against the nav bar, pop-ups and toasts.
