# WMR photo export — implementation plan

Spec: `docs/superpowers/specs/2026-11-24-wmr-photo-export-design.md` (don't restate it
here). Status 2026-11-24: not started.

**Phases and gates**

| Phase | Tasks | Gate before the next phase |
|---|---|---|
| A. Proof of concept (local) | 1–8 | User runs the PoC checklist (Task 9) on local port 8124 and approves |
| B. Production | 10–11 | User approves the push (push = deploy); disk resized; end-to-end run in production with the script working on the boss's PC |
| C. Safety: separate photo DB | 12 | Starts only after B passes |

Rules for every task: targeted tests only (bounded diffs); Vitest runs from PowerShell
at `C:\...`; stage explicit paths (peer sessions share this checkout); no push without
asking. Commit after each task once its tests pass.

---

## Phase A — proof of concept

### Task 1 — Folder rules (`photo_path`)
- **Goal:** pure function turning a work order into `(folder, filename_stem)`.
- **Files:** `backend/app/domain/photo_paths.py` (new), `backend/tests/test_photo_paths.py` (new). Done 2026-11-24.
- **Steps:**
  1. `photo_path(service_type, number, location, taken_on, seq) -> (folder, filename)`; folder starts with the service-type folder.
  2. Prefix = text before the first `:` or `,`; map the four apartment communities +
     Young Hall; everything else → `Academics/<hall>`; blank → `_Unsorted`.
  3. Unit regexes as the spec table: digits (Scholars/Centennial: building = all but
     last two), number+letter (Commons/Cimarron), Young Hall `NNN[AC]` → floor + side,
     no side → `Misc`; apartment rows without a unit → `Clubhouse` if the text contains
     "clubhouse" (any case), else `Exterior`.
  4. `safe_name()`: spaces → `-`, strip `\/:*?"<>|`, trim dots and spaces.
  5. Filename `<WO>_<date>_<Community>_<bldg>_<unit|NA>[_<seq>].jpg` (seq 0 = no suffix).
- **Test:** parametrized table using the real production strings quoted in the spec
  (both separators, `1632-1`, `1333D`, `13G`, `J12`, `208A-A`, `315C- A`,
  `326 - Entire Area`, `Buildings 3,9`, `University Women/Health Clinic`, blank).

### Task 2 — Table + migration
- **Goal:** `work_order_photos` exactly as the spec's column table.
- **Files:** `backend/app/models.py`, `backend/alembic/versions/<rev>_add_work_order_photos.py`.
- **Steps:** model `WorkOrderPhoto` (`original`, `preview_jpeg` deferred), unique
  `(work_order_id, taken_on, seq)`, index on `exported_at`; FK `ON DELETE CASCADE`
  from work order. Migration revises the current head (`alembic heads` first).
- **Test:** `alembic upgrade head` + `downgrade -1` + `upgrade head` on the local DB.

### Task 3 — Image handling
- **Goal:** validate, date, HEIC-convert, preview.
- **Files:** `backend/app/domain/photos.py` (new), `backend/requirements.txt`
  (`pillow-heif`), `backend/tests/test_photos.py` (new).
- **Steps:**
  1. `register_heif_opener()` at import.
  2. `prepare(raw: bytes, today) -> (original, preview, taken_on)`: open with Pillow
     (failure → `ValueError`); `taken_on` from EXIF 36867 `DateTimeOriginal`, fallback
     `today`; JPEG → original = raw bytes; HEIC → `exif_transpose` not applied, save
     JPEG q95 keeping `exif`; preview = `exif_transpose` → `thumbnail((800, 800))` →
     JPEG q75, no EXIF.
- **Test:** generated JPEG with EXIF date → that date and byte-identical original;
  without EXIF → today; preview long edge ≤ 800; garbage bytes → `ValueError`; one small
  HEIC fixture (generated with pillow-heif inside the test) → JPEG original.

### Task 4 — Storage figures
- **Goal:** usage numbers + thresholds shared by upload, route and warning.
- **Files:** `backend/app/domain/photos.py`, `backend/app/config.py` (or the existing
  settings module — use whatever already reads env), `backend/tests/test_photos.py`.
- **Steps:** `DB_DISK_BYTES` env (default `1_073_741_824`); `storage_status(db)` →
  `{used, disk, ratio, waiting_photos, waiting_bytes, warn: ratio>=0.5, full: ratio>=0.8}`
  with `used = pg_database_size(current_database())`.
- **Test:** monkeypatch the size query → warn/full flags at 0.49/0.5/0.79/0.8.

### Task 5 — Routes
- **Goal:** upload, list, preview, storage, export, clear.
- **Files:** `backend/app/routers/work_order_photos.py` (new), `backend/app/main.py`
  (include router), `backend/tests/test_work_order_photos.py` (new); memprobe route
  catalogue (it needs every new route — see CI notes).
- **Steps:**
  1. `POST /work-orders/{id}/photos` — same edit permission as the work order edit
     route; `read_capped(limit=20 MB)` per file; `full` → 507; `prepare()`;
     `seq = coalesce(max(seq)+1, 0)` for (wo, taken_on) inside the transaction, retry
     once on unique violation.
  2. `GET /work-orders/{id}/photos` → `[{id, filename, taken_on}]`.
  3. `GET /work-order-photos/{id}/preview` → JPEG, `Cache-Control: no-store`.
  4. `GET /work-order-photos/storage` — `require_min_role("admin")`.
  5. `GET /work-order-photos/export.zip` — admin; `StreamingResponse` writing a
     `zipfile.ZipFile` (`ZIP_STORED`) into a spooled temp file one row at a time
     (`yield_per`, load `original` per row); path = `export_<YYYY-MM-DD>/<folder>/<filename>`;
     `manifest.csv`; stamp `exported_at` for the included ids after the zip is written;
     filename `export_<YYYY-MM-DD_HHMM>.zip`.
  6. `POST /work-order-photos/clear-exported` — admin; delete where `exported_at` is set,
     commit, then `VACUUM FULL work_order_photos` on an autocommit connection; return
     `{deleted, storage}`.
- **Test:** real `TestClient` (not direct handler calls): upload 2 same-day → seq 0/1;
  non-image → 400; technician without edit rights → 403; full → 507; export contains
  the expected paths + manifest and stamps; a second export includes the same set;
  clear removes only exported rows; storage/export/clear 403 for technician.

### Task 6 — Work order Photos section
- **Goal:** add/view photos on a work order.
- **Files:** `backend/static/views/workOrderPhotos.js` (new, modelled on
  `workOrderSignature.js`), `backend/static/views/workOrderCardHtml.js` (section
  slot), `backend/static/api.js`, `backend/static/styles.css`,
  `tests/frontend/views/workOrderPhotos.test.js` (new).
- **Steps:** "Add photos" button →
  `<input type=file accept="image/*,.heic,.heif" multiple>`; upload with progress text
  ("Uploading 2 of 5"); thumbnail strip of previews (wraps, no sideways scroll); count
  in the section title; 507 shows the server message. Classes only (CSP).
- **Test:** Vitest — renders the strip from the list API; upload calls the API per
  file; 507 message shown. Load the view via `importView` inside the test.

### Task 7 — Integrations "Image export" section
- **Goal:** download, clear, usage line.
- **Files:** `backend/static/pages/integrations.html`,
  `backend/static/views/imageExport.js` (new), `backend/static/api.js`,
  `backend/static/styles.css`, `tests/frontend/views/imageExport.test.js` (new).
- **Steps:** section `#integrations-image-export`, visible to Admin/Owner; usage line
  "Database 540 MB of 1 GB (54%) · 12 photos waiting"; **Download photos (N)** →
  navigates to `export.zip` (browser download); **Clear exported (N)** → confirm with
  the count → POST → refresh the line; one hint line with the order of steps.
- **Test:** Vitest — line renders; buttons disabled at N = 0; clear asks before posting.

### Task 8 — Sign-in storage warning
- **Goal:** the 50% / 80% modal after the clock-in prompt.
- **Files:** `backend/static/views/storageWarning.js` (new),
  `backend/static/views/clockInPrompt.js` (resolve when closed),
  `backend/static/views/welcome.js`, `backend/static/views/auth.js` (close on sign-out),
  `tests/frontend/views/storageWarning.test.js` (new).
- **Steps:**
  1. `maybePromptClockIn` currently returns once the modal is built; make it return a
     promise that resolves when the modal closes (or right away when not shown).
  2. `runWelcomeThenClockIn`: after `await maybePromptClockIn(user)` →
     `await maybeWarnStorage(user)`.
  3. `maybeWarnStorage`: Admin/Owner only; fetch storage; quiet on failure; `warn` →
     modal (spec wording); **Go to Image export** routes to Integrations and scrolls
     to `#integrations-image-export`; **Later** closes. `full` → the "uploads are
     stopped" title. Close it on sign-out like `closeClockInPrompt`.
- **Test:** shows at 50% for admin + owner; not for technician; not at 49%; quiet on
  fetch error; appears only after the clock-in modal closes; button lands on the section.

### Task 9 — Sort script + PoC run
- **Goal:** the double-click script, then the full local proof of concept.
- **Files:** `scripts/wmr_sort.py` (new), `backend/tests/test_wmr_sort.py` (new).
- **Steps:**
  1. Stdlib only. Zip = argv[1] (dragged on) or newest `export_*.zip` in
     `~/Downloads`; extract to `tempfile.mkdtemp()`.
  2. Prompt for the Drive path; remember it in `wmr_sort_last_path.txt` next to the
     script; Enter reuses it; refuse a path that doesn't exist.
  3. Walk `export_*/`; `mkdir(parents=True, exist_ok=True)`; copy with `shutil.copy2`
     only if the target doesn't exist; never overwrite/delete.
  4. Print `Copied N, skipped M (already there), unsorted K`; remove the temp folder;
     `input("Press Enter to close")`. Any exception → print it and wait (the window
     must not vanish).
- **Test:** temp zip + temp "drive": first run copies all; second run skips all; a
  pre-existing file with the same name is left untouched.
- **PoC checklist (user, manual, local 8124):**
  1. Upload your own photos to ~6 local work orders: Scholars, Centennial, Commons,
     Young Hall (A, C, Misc), one Academics hall, one blank location; include two
     same-day photos on one order and one iPhone HEIC if available.
  2. Check the thumbnails, then download the zip.
  3. Run `wmr_sort.py` against `Desktop\fake-drive` → check folders and names.
  4. Run it again → all skipped.
  5. Clear exported → usage line drops; `fake-drive` files untouched.
  6. Set `DB_DISK_BYTES` low (e.g. 100 MB) and sign in as Admin → warning shows and
     the button lands on Image export; set it lower still → uploads refused.

---

## Phase B — production

### Task 10 — Rollout prep (user + me)
- **Goal:** production can hold the photos.
- **Steps:** user resizes the `inventory-db-copy` disk in Render; set `DB_DISK_BYTES`
  to match on the web service; update `docs/current-state.md` (feature row) and
  `docs/open-work.md` (remove the item / add Phase C) within their word budgets.
- **Test:** none (config); usage line shows the new disk size after deploy.

### Task 11 — Deploy + first real run
- **Goal:** working end to end in production, script on the boss's PC.
- **Steps:**
  1. Ask, then push main (push = deploy); migration runs on deploy.
  2. User uploads a few real photos, downloads the zip.
  3. On the boss's PC: copy `wmr_sort.py` to the Desktop; check that double-clicking
     a `.py` opens Python (if not: right-click → Open with → Python, "always"); run it;
     paste the Drive path (e.g. `G:\My Drive`); confirm Drive syncs `export_<date>/`.
  4. Clear exported in production; usage line drops.
- **Test:** the user's in-app check + the files showing on drive.google.com.

---

## Phase C — safety: separate photo database (after B passes)

### Task 12 — Move photos to their own Postgres
- **Goal:** photo disk and restores fully separate from field data.
- **Files:** `backend/app/db.py` (second engine/session from `PHOTOS_DATABASE_URL`,
  falling back to the main DB when unset), `backend/app/routers/work_order_photos.py`
  (use the photo session), the model (drop the FK to `work_orders`; keep
  `work_order_id` as a plain UUID, checked in the route), a separate small Alembic
  setup or a create-table script for the photo DB, `render.yaml`/service env.
- **Steps:** create the Render instance (user, billing); copy existing photo rows;
  switch the env var; `storage_status` reports the photo DB's size against its own disk
  setting (`PHOTOS_DB_DISK_BYTES`); main-DB migration drops the old table once the copy
  is verified.
- **Test:** the Task 5 suite runs against both settings (unset = one DB, set = two);
  manual export/clear in production.

Write a separate short spec for Phase C before starting it; the details above are
direction, not decisions.
