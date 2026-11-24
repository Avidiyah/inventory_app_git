# WMR photo upload → export → Drive sort — design

Status: draft for review · 2026-11-24

## Goal

Crews attach photos to work orders in TechFM. Once a day, someone downloads every
photo not yet exported as one zip (`export_<date>_<HHMM>.zip`) laid out as `<Service-Type>/…`. A
double-click Python script on the office PC copies **only new files** into the
Google Drive desktop folder, which then syncs them to Drive. After checking Drive,
the Owner clicks **Clear exported**, which deletes those photos from the database.
The database only holds photos briefly, so it never fills up.

No Drive API, service account or OAuth: the Drive desktop app handles the upload.

## Settled decisions (don't re-open these)

| Topic | Decision |
|---|---|
| Transport | Zip download plus a local script. Drive desktop syncs the folder |
| Purge | Owner clicks **Clear exported** after confirming the files are in Drive |
| Photo date | Camera EXIF date; falls back to the upload date |
| Same order + same day | Add `_1`, `_2`, … The number is saved at upload, so re-exports give the same names |
| Folders | Built from the work order's `location` text when the zip is built. A missing folder is created by the script |
| Proof of concept | Full local run: upload real photos to local work orders → export → script → a fake Drive folder |
| Quality | Original stored as uploaded (never shrunk or re-encoded) **plus** a ~50 KB preview; the app only ever shows the preview; only the original is exported. Zip/re-pack compression was rejected (JPEG already compressed, ≤ 20% at best) |
| Disk | Production DB disk is 1 GB (52 MB used 2026-11-24); 60 originals a day ≈ 240 MB/day. The user raises the disk in Render (billing) before rollout |
| Disk warnings | Admin sign-in warning at 50% of the disk; uploads refused at 80% |

## Folder tree

One fixed tree in Drive (the date is only on the zip name, so re-downloads never duplicate): one folder per service type (`safe_name` of the free-text `service_type`; blank → `Unspecified`), created from the data so a new service type needs no code change. Below each service type the same community tree; community folders are fixed, folders below them come from the data.

| Location starts with | Folder | Rule |
|---|---|---|
| `Scholars Inn Apartments` | `Scholars/<bldg>/` | 3–4 digit unit, building = all digits except the last two (`1633` → `16`, `1333D` → `13`) |
| `Centennial Courts Apartments` | `Centennial/<bldg>/` | Same rule (`614` → `6`, `1133` → `11`) |
| `Commons Apartments` | `Commons/<bldg>/` | Number + letter, number = building (`13G` → `13`) |
| `Cimarron Gardens Apartments` | `Cimarron/<bldg>/` | Same as Commons (`Cimarron 12J` / `J12` → `12`) |
| `Young Hall` | `Young-Hall/Floor-<n>-Mens/` or `-Womens/` | Room `NNN` + `A` = men's, `C` = women's; floor = first digit |
| `Young Hall`, no A/C side | `Young-Hall/Misc/` | Lobby, lounges, `326 - Entire Area` |
| Any of the four apartment communities, no unit | `<Community>/Clubhouse/` or `<Community>/Exterior/` | Text contains "Clubhouse" → Clubhouse; everything else (exterior, basement, janitorial, "Buildings 3,9") → Exterior |
| Any other prefix | `Academics/<Hall-Name>/` | The text before the first `:` or `,` |
| Blank or no prefix | `_Unsorted/` | Nothing is dropped |

Production check (2026-11-24, read-only, 2,046 orders): Scholars 10–27, Centennial
1–11, Commons 2–19, Cimarron 1–12, Young Hall floors 1–3 both sides, 34 Academics
halls, 147 blank → `_Unsorted`. The separator can be `:` or `,`; the code accepts
both.

**Folder-name cleanup:** spaces → `-`; drop anything Windows forbids (`\/:*?"<>|`).
`University Women/Health Clinic` → `University-Women-Health-Clinic`. Trailing dots
and spaces are trimmed.

## Filename

```
<WO#>_<YYYY-MM-DD>_<Community>_<bldg>_<unit>[_<n>].jpg
```

- `<Community>` = the top-level folder name (`Scholars`, `Young-Hall`, `Academics`).
- `<bldg>` = the building folder (hall name for Academics, `Clubhouse`/`Exterior`/`Misc`
  when there's no unit).
- `<unit>` = the full unit as written, including any room letter (`1333D`, `13G`,
  `322C`); `NA` if there's none.
- `_<n>` only when an earlier photo has the same order + date; the first photo has no
  suffix.
- The same cleanup rule as folders applies to every part.

Example: `WMR27/Scholars/16/12345_2026-11-24_Scholars_16_1633.jpg`.

## Backend

**Table `work_order_photos`** (one Alembic migration):

| Column | Type | Note |
|---|---|---|
| id | UUID PK | |
| work_order_id | FK work_orders | |
| original | LargeBinary, `deferred` | The uploaded bytes, untouched (keeps EXIF, full resolution) |
| original_type | text | Always `image/jpeg` (HEIC is converted on upload) |
| preview_jpeg | LargeBinary, `deferred` | Long edge 800 px, JPEG q75, EXIF rotation applied, metadata stripped, ~50 KB |
| size_bytes | int | Length of `original`; summed for the warnings |
| taken_on | Date | EXIF `DateTimeOriginal`, or upload date |
| seq | int | 0 = no suffix; next = max(seq)+1 for (work order, taken_on) |
| uploaded_by_id | FK users | |
| uploaded_at | timestamptz | |
| exported_at | timestamptz null | Set when it's included in a downloaded zip |

Unique `(work_order_id, taken_on, seq)`.

**Upload** `POST /work-orders/{id}/photos` (multipart, one or more files):
- `read_capped` (existing `_uploads.py`) with a per-file cap of 20 MB.
- Pillow (already pinned): open it to validate (anything Pillow can't open → 400),
  read the EXIF date, build the preview. JPEG originals are saved as received.
- **HEIC/HEIF** (iPhone): accepted and converted once to JPEG quality 95 at full
  resolution, EXIF kept, so Windows and Drive open it everywhere. This is the one case
  where the stored "original" isn't the uploaded bytes. Needs the new dependency
  `pillow-heif` (prebuilt Linux/Windows wheels; registered with Pillow at startup).
- Refused with 507 "Photo storage is full — export and clear first" when the database
  is at or above 80% of the disk (see Disk capacity).
- Who can upload: anyone who can edit that work order (current edit permission).

**List / view** `GET /work-orders/{id}/photos` (ids + names) and
`GET /work-order-photos/{id}/preview` (the preview JPEG, `no-store`). There is no
route that serves the original; it only leaves through the export. No gallery,
editing or delete-per-photo in v1.

**Export** `GET /work-order-photos/export.zip` (Owner/Admin):
- All photos with `exported_at IS NULL` *or* exported and not yet cleared, so a lost
  zip can be downloaded again.
- Streams a zip of the **originals** (stdlib `zipfile`, `ZIP_STORED` since JPEGs don't
  compress, written one photo at a time so memory stays flat) under `<Service-Type>/…` (zip named `export_<date>_<HHMM>.zip`).
- Adds `manifest.csv` (path, WO#, location raw text, folder rule used) so `_Unsorted`
  rows are easy to look into.
- Stamps `exported_at` on every photo it included.

**Clear exported** `POST /work-order-photos/clear-exported` (Owner/Admin):
- Deletes rows with `exported_at` set. The confirm text shows the count.
- Then runs `VACUUM FULL work_order_photos` (outside the request transaction) so the
  freed space goes back to the disk and the usage figure drops right away. It locks
  only the photos table for the seconds it takes; uploads made during it wait.
- Deliberately a confirm, not an in-app undo: the bytes are gone afterwards, and the
  guard is "you checked Drive first". Recovery after a mistake goes through Render's
  database backups (restore a copy, copy the rows back) — a manual job, not a button.

**Disk capacity.** Postgres can't see its own disk size, so it's a setting:
`DB_DISK_BYTES` (env, default 1 GB; the user updates it when they resize the disk).
`GET /work-order-photos/storage` (Owner/Admin) returns
`{used: pg_database_size(), disk: DB_DISK_BYTES, waiting_photos, waiting_bytes}`.
Used = the whole database, not only photos, because that's what fills the disk.
Thresholds: **50% → sign-in warning**, **80% → uploads refused**.

**Folder rules** live in one pure function `photo_path(service_type, number, location, taken_on, seq) -> (folder, filename)` (`app/domain/photo_paths.py`)
in `app/domain/`, unit-tested against the production samples quoted above. The local
script doesn't re-parse anything; it trusts the zip paths.

## Front end

- Work order detail: a **Photos** section with an "Add photos" button
  (`<input type="file" accept="image/*" capture="environment" multiple>`), a
  thumbnail strip and a count.
- **Integrations page → new "Image export" section** (`pages/integrations.html`,
  anchor `#integrations-image-export`): **Download photos (N new)**,
  **Clear exported (N)**, a usage line ("Database 540 MB of 1 GB"), and one line on the
  order: download → run the script → check Drive → clear.
- **Sign-in storage warning (Owner/Admin):**
  - When: once per sign-in, right after the clock-in prompt is closed (clocked in or
    skipped). If the clock-in prompt doesn't show (already clocked in; the Owner is
    always skipped), it appears where that prompt would have. Hooked into the same
    `welcome.js` flow that calls `maybePromptClockIn`, after it.
  - Condition: `used / disk ≥ 50%` from the storage route. A failed lookup stays quiet.
  - Modal, same `.modal-overlay` / `.modal-box` chrome as `clockInPrompt.js`:
    title "Photo storage is half full"; body "The database is using 540 MB of 1 GB
    (54%). Export the photos and clear them to free space. Photo uploads stop at 80%.";
    buttons **Go to Image export** (routes to Integrations, scrolls to the section) and
    **Later** (closes; it comes back next sign-in).
  - At ≥ 80% the title becomes "Photo storage is full — uploads are stopped".
- Follows the CSP rules (no inline styles) and the no-horizontal-scroll rule.

## Sort script (`backend/scripts/photo_sort.py`)

Stdlib only (`zipfile`, `shutil`, `pathlib`), so the boss's PC needs no `pip install`.

1. Double-click → console window. Finds the newest `export_*.zip` in `Downloads` (or
   takes a zip dragged onto the script).
2. Extracts it into the folder the script lives in (e.g. `Desktop/Photo_Export`); with no zip it uses what is already extracted there.
3. Asks: *Paste the Google Drive folder path (e.g. `G:\My Drive`)*. Remembers the
   last answer in a small `.txt` next to the script; Enter reuses it.
4. Checks the path exists, then creates `<drive>\<Service-Type>\…` folders as needed.
5. For each file: if the target name exists → skip; otherwise copy. **It never
   overwrites or deletes anything in Drive.**
6. Prints `Copied N, skipped M (already there), unsorted K` and waits for Enter.
7. Leaves the zip and the extracted files in that folder.

## Proof of concept (first deliverable)

Run locally against the dev database on port 8124, and the user checks it by hand:

1. Pick about 6 local work orders covering Scholars, Centennial, Commons, Young Hall
   (A, C and Misc), one Academics hall and one blank location.
2. Upload photos from your own computer, including two on the same order and day to
   test `_1`.
3. Download the zip, run `photo_sort.py` against a fake folder
   (`Desktop\fake-drive`).
4. Run it a second time → everything shows as skipped.
5. Click Clear exported → photos are gone from the database and the Drive copies stay.

Production rollout comes after the proof of concept passes and you give the go-ahead.

## Tests

- `photo_path` table test: every row in the folder table, plus the comma separator,
  `1632-1`, `Buildings 3,9`, the `/` in a hall name, and blank.
- Upload: EXIF date used; no EXIF → upload date; seq increments; non-image → 400.
- Export: paths inside the zip; `exported_at` stamped; a re-download includes the same
  set until it's cleared.
- Clear: only removes exported rows.
- Original is byte-identical to the upload; preview long edge ≤ 800; no route serves
  the original.
- Storage: 507 at ≥ 80% (monkeypatched size); Vitest — warning shows at 50% for
  Admin/Owner only, after the clock-in prompt closes, not for a Technician, not below
  50%, quiet on a failed lookup; the button lands on `#integrations-image-export`.
- Script: a small `test_photo_sort.py` with a temporary zip and a fake Drive folder —
  copies new files, skips existing ones, never overwrites.

## Out of scope (v1)

Deleting or editing single photos, a gallery, Drive API upload, video, auto-purge,
reading Drive to confirm the sync.

## Open questions

None. Render restore window confirmed at 3 days (2026-11-24); a restore creates a
separate database, so only the photo rows are copied back and live field data is
untouched.

## Future: separate photo database

Move `work_order_photos` to its own small Postgres instance (second `PHOTOS_DATABASE_URL`,
own SQLAlchemy engine). Gains: photos filling a disk can never stop the main app, and
restores/vacuums stay fully separate. Do it if photo volume grows or the 80% guard
starts firing; v1 keeps one database because the table has no joins that need it to
be separate, so moving it later is a contained change.
