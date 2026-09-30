# Work Orders — Witness Signature Card

**Status:** Draft for review · **Date:** 2026-09-30 · **Scope:** new optional
collapsible card on the work-order card (list card + solo card page), one new
table, three endpoints.

## Goal

Let whoever is on site capture a witness sign-off on a work order: a drawn
signature, the witness's printed name, and their phone number. It is a
completion sign-off: one per work order, locked once saved. It is **optional**
and gates nothing: Complete, Hold, Archive, and every other flow behave
exactly as today.

## Decisions

| # | Decision |
|---|---|
| S1 | One signature per work order; locked after save. |
| S2 | Optional. Does not block Complete or any other status change. |
| S3 | Any user who can view the work order may capture it. |
| S4 | The card is shown at every status. |
| S5 | Supervisor+ may clear a saved signature; the card returns to blank. No confirm dialog — the note log records the clear. |
| S6 | Save requires all three: a drawn stroke, a nonblank printed name, a valid phone. |
| S7 | Phone is US 10-digit: strip non-digits, drop one leading `1` from 11 digits, then require exactly 10. Stored as 10 digits; displayed `(555) 555-1234`. |
| S8 | The phone is visible to every viewer of the work order (same visibility as the card). |
| S9 | Save and clear each append a server-authored note-log entry. No report, badge, or other surface. |
| S10 | Locked view shows image, name, phone, and "Captured by {user} on {date/time}". |
| S11 | A save interrupted by a dropped connection or session expiry joins the existing offline-draft replay. |
| S12 | Save and clear emit the live status-changed event so other open copies of the card refresh. |
| S13 | Pad controls: a single **Clear** (wipe pad). Black ink on white in both themes. |
| S14 | Archive and restore leave the signature untouched; deleting the work order deletes it. |
| S15 | Card title "Signature"; placed last: Notes, Materials, Request, Labor, Signature. |

## Data

New table `work_order_signatures` (Alembic migration, reversible):

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `work_order_id` | UUID FK → `work_orders.id`, `ON DELETE CASCADE`, **unique** | Uniqueness enforces S1 at the DB. |
| `image_png` | `bytea` not null | ≤ 256 KB, PNG signature bytes verified. |
| `witness_name` | `text` not null | Trimmed, nonblank, ≤ 120 chars. |
| `witness_phone` | `varchar(10)` not null | 10 digits only. |
| `captured_by_id` | UUID FK → `users.id` | Who was logged in when saved. |
| `captured_at` | `timestamptz` not null | Server time. |

A separate table (not columns on `work_orders`) keeps the image out of list
queries and reports; "unsigned" is simply no row. A `WorkOrderSignature` model
lives beside `WorkOrder` in `models.py` with a one-to-one relationship.

## Domain

In `domain/work_orders.py`:

- `normalize_witness_phone(raw: str) -> str` — S7; raises the existing
  validation `DomainError` (→ 422) on anything but a resulting 10 digits.
- `format_witness_phone(digits: str) -> str` — `(555) 555-1234`.
- Note-body constants beside `NOTE_BEGAN_WORK`:
  `NOTE_SIGNED_OFF = "captured witness sign-off from {name}"` and
  `NOTE_SIGNATURE_CLEARED = "cleared the witness sign-off"`. The log line's
  author and timestamp come from `append_note_log` as for every other entry.

## Service

In `services/work_orders.py` (or a sibling `work_order_signature.py` if the
service file's size calls for it — decided in the plan):

- `save_signature(db, work_order_id, *, user, image_data_url, witness_name, witness_phone)`
  - Loads the work order through the same visibility-scoped lookup
    `get_work_order` uses (not visible → the existing not-found error).
  - Decodes the `data:image/png;base64,...` URL; rejects a non-PNG payload,
    a malformed data URL, or > 256 KB decoded (→ 422).
  - Validates name (S6) and normalizes phone (S7).
  - Existing row → conflict error (→ 409). The unique constraint is the
    backstop for a concurrent double save.
  - Inserts the row and appends `NOTE_SIGNED_OFF` to `work_order.notes`.
- `clear_signature(db, work_order_id, *, user)` — Supervisor+; no row → not
  found (→ 404); deletes the row and appends `NOTE_SIGNATURE_CLEARED`.
- `get_signature_png(db, work_order_id, *, user)` — visibility-scoped; returns
  bytes or not found.

## API

In `routers/work_orders.py`:

| Route | Guard | Success | Errors |
|---|---|---|---|
| `POST /work-orders/{id}/signature` | viewer of the WO | `WorkOrderDetail` (201) | 404 not visible · 409 already signed · 422 bad image/name/phone |
| `DELETE /work-orders/{id}/signature` | `require_min_role` Supervisor | `WorkOrderDetail` | 403 · 404 no signature |
| `GET /work-orders/{id}/signature.png` | viewer of the WO | `image/png`, `Cache-Control: no-store` | 404 not visible or unsigned |

POST body (`schemas/work_orders.py`): `{ image: str, witness_name: str,
witness_phone: str }`. Both writes call `_emit_status_changed(work_order.id)`
(S12).

`WorkOrderDetail` gains `signature: Optional[WorkOrderSignatureOut]`:
`{ witness_name, witness_phone_display, captured_by_name, captured_at,
image_url }`. `image_url` carries a `?v={captured_at epoch}` suffix so a
clear-then-resign never shows a stale image. The existing CSP
(`img-src 'self' data: blob:`) already allows the `<img>`.

## Front end

### Card (`views/workOrderSignature.js`, new, ~200 lines)

Exports `signatureSectionHtml(detail)`, `mountSignaturePad(sectionEl)`, and the
save/clear handlers. `workOrderCardHtml.js` appends
`signatureSectionHtml(detail)` after the Labor section (S15), for every viewer
(S3, S4):

```
<details class="wo-section-card wo-signature-section">
  <summary class="wo-section-summary">Signature</summary>
  <div class="wo-section-content">…</div>
</details>
```

Collapsed by default, same classes as its siblings — no new presentation for
the collapsed state.

**Unsigned content**

- `<canvas class="wo-signature-pad">` plus `<button data-action="clear-signature-pad">Clear</button>`.
- `Witness Printed Name:` — `<input type="text" class="wo-signature-name" maxlength="120">`.
- `Phone number:` — `<input type="tel" class="wo-signature-phone" autocomplete="tel">`.
- `<button data-action="save-signature">Save signature</button>`, disabled
  until a stroke exists, the name is nonblank, and the phone passes the
  client mirror of S7.
- `<p class="wo-signature-message" aria-live="polite">` for errors.

**Signed (locked) content** (S10)

- `<img class="wo-signature-image" alt="Witness signature">` from `image_url`.
- Name, formatted phone, "Captured by {user} on {MM/DD/YY hh:mm AM/PM}".
- Supervisor+ only: `<button class="btn-danger" data-action="clear-signature">Clear signature</button>` (S5).

### Pad

- Initialized on the section's first `toggle` to open, so collapsed cards
  create no canvas context or listeners.
- Pointer Events (`pointerdown/move/up/cancel`, `setPointerCapture`) — finger,
  stylus, mouse alike.
- `touch-action: none` via the `.wo-signature-pad` CSS class; no inline
  `style=` (CSP drops it).
- Backing store sized to `clientWidth × devicePixelRatio`; filled white
  before drawing; black round-cap strokes (S13).
- Export: `canvas.toDataURL("image/png")`.
- **Clear** wipes the pad back to white and re-disables Save.

### Wiring

- `workOrderActions.js`: route `save-signature`, `clear-signature`,
  `clear-signature-pad` to the new module's handlers (dispatch entries only).
- `api.js`: `apiSaveWorkOrderSignature(id, payload)`,
  `apiClearWorkOrderSignature(id)`.
- On success both re-render the card via the existing refresh path.
- `styles.css`: `.wo-signature-pad` (full width, fixed height, white
  background, border, `touch-action: none`), `.wo-signature-image`
  (max-width 100%, white background so it reads in dark mode), field rows
  matching the Notes section.

### Offline recovery (S11)

- `workOrderDrafts.js`: `SECTION_SELECTOR.signature = ".wo-signature-section"`.
- `workOrderRetry.js`: `RETRY_ACTIONS["save-signature"]` →
  `apiSaveWorkOrderSignature`.
- The save handler writes the draft (image data URL, name, phone) before the
  request, exactly as labor/materials do, and clears it on success.
- On replay, a 409 marks the draft errored (`markDraftError`), and the card
  shows the signature that won. A 422 does the same. Resume-after-login
  restores the name and phone and redraws the image onto the pad.

## Testing

| Level | File | Covers |
|---|---|---|
| Domain | `test_work_orders_domain.py` | Phone: punctuation stripped; `1` + 10 accepted; 9 and 11-not-leading-1 rejected; letters ignored; blank rejected. Formatting. |
| Service | `test_work_order_signature.py` (new) | Save inserts one row + note line; second save → conflict; clear deletes + note line; WO delete cascades; archive/restore keep the row; non-PNG, > 256 KB, blank name rejected. |
| Router | same file, real `TestClient` | Technician viewer can save; non-visible → 404; clear → 403 for Technician, 200 for Supervisor+; PNG route content type and 404 when unsigned; `signature` present/absent on `WorkOrderDetail`. |
| Migration | existing Alembic up/down check | Table created and dropped cleanly. |

Manual (the user's check): drawing on a phone and a desktop, no page scroll
while drawing, dark-mode legibility, offline save and replay, live refresh in
a second tab, Supervisor clear.

## Out of scope

Weekly closed report / xlsx columns, a "Signed" badge on the collapsed card,
requiring a signature to complete, undo of the last stroke, multiple
signatures per work order, international phone numbers.
