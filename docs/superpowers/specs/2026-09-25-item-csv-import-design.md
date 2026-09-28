# Add Items CSV Import — Draft Specification

Date: 2026-09-25

Status: Draft; source compatibility reviewed; tuple meaning and opening quantity pending owner clarification.

Scope: Specify first, prove against local development PostgreSQL, then add the workflow to Add Items. No import or application implementation is authorized by this document alone.

## Purpose

Create many inventory items from a CSV. A same-name or same-barcode match must visibly skip the entire incoming row, preserve the existing item, and allow unrelated valid rows to continue. Never merge, overwrite, add quantity to an existing item, or silently discard a conflict.

## Evidence and compatibility status

Reviewed the item models, creation schema/service/router, Add Item JavaScript, upload limits, relevant Alembic definitions, repository current-state/open-work documentation, and the Obsidian current-state mirror.

Read-only inspection of the configured **local** PostgreSQL database confirmed the columns below and the barcode uniqueness constraints. Its Alembic revision was `c4a6e8b0d2f5`. No database records were changed. This does not establish the deployed database's migration state.

The supplied OneDrive URL required authentication; the subsequent local source `C:\Users\mcclu\Desktop\Hex_Bolt_Migration.csv` was successfully read and profiled. **The file is not directly import-compatible.** Its header has six fields while all 57 data records have five; its apparent quantity field contains a three-value tuple rather than a stock count. The source was not modified. The following table defines the canonical input contract; the source-specific mapping follows it.

| Proposed CSV field | Current database destination | Import rule |
| --- | --- | --- |
| `barcode` | `items.barcode`: required unique TEXT | Required nonblank text; trim outer whitespace; preserve leading zeros and case. Never parse as a number. |
| `name` | `items.name`: required TEXT, **not unique** | Required nonblank text; import must explicitly detect same-name matches. |
| `location` | `items.location`: required TEXT | Required after trimming. An explicit operator-selected default location may fill blanks; do not invent one. |
| `quantity` | `items.quantity`: required NUMERIC | Missing/blank becomes 0 with the default shown in preview. Otherwise finite nonnegative Decimal; fractional values allowed. |
| `price` | `items.price`: nullable NUMERIC | Missing/blank becomes NULL, not zero. Otherwise finite nonnegative Decimal. Preserve supplied precision. Confirm unit price versus package price from the actual file. |
| `product_link` | `items.product_link`: nullable TEXT | Missing/blank becomes NULL; nonblank input must be an absolute HTTP(S) URL. Do not fetch it. |
| No input | `items.id`, `created_at`, `archived_at` | Generate identity/time normally; create live items. Do not accept imported internal IDs or archive state. |
| No input in baseline | `items.notes`: JSONB; `low_stock_threshold`: INTEGER | Existing defaults: empty notes and threshold 6. |
| No input in baseline | `item_barcodes.code`: unique TEXT linked to item | Check incoming primary codes against this table too. Additional barcode import awaits evidence that the CSV needs it. |

Basic fields fit the existing schema without adding columns. For this source, preserving the complete tuple in the item name avoids losing distinguishing data and needs no notes support or new columns. The tuple's meaning remains unconfirmed; do not label its components as diameter, thread count, length, grade, or stock quantity without clarification. Existing scalar JSONB notes could hold confirmed attributes later, but the current create payload does not accept notes.

### Actual source profile

Read-only inspection on 2026-09-25:

| Check | Result |
| --- | --- |
| File size | 2,563 bytes |
| SHA-256 | `41dc930f3a388aae479809da63f330bf63209a1469d04344a67f15a7ceecb661` |
| Encoding | ASCII-only bytes, valid UTF-8, no BOM |
| Data records | 57; no blank records |
| Header, literally | `Barcode, Nam,e, Quantity, Location,` |
| Parsed header width | 6: `Barcode`, ` Nam`, `e`, ` Quantity`, ` Location`, empty |
| Every data record | 5 fields: barcode, `HexBolt`, tuple, `Tool Room`, empty |
| Barcode profile | 57 unique six-character codes; no duplicates or blanks |
| Raw name profile | One normalized name, `hexbolt`, repeated 57 times |
| Proposed name profile | 57 distinct names when the complete tuple is appended |
| Location | `Tool Room` in all 57 records |
| Trailing field | Empty in every data record |
| Prices / links / explicit stock counts | Not supplied as separate fields |

Example source record (physical line 2):

```csv
879168, HexBolt, (0.5125 17 4), Tool Room,
```

The `Nam,e` spelling appears to be an accidental extra delimiter, but that is an inference. Even changing it to `Name` leaves the tuple under `Quantity`, where it cannot be parsed as a Decimal. Standard header mapping would also misplace `Tool Room` under `Quantity` in the original file. Do not silently repair either problem inside the generic importer.

### Proposed source-specific preparation

Once the owner confirms the tuple is a variant descriptor and approves opening quantity 0, prepare a separate canonical CSV; retain the original unchanged. This is an explicit source-preparation step, not a permissive exception in the application parser.

| Source position | Example | Proposed mapping |
| --- | --- | --- |
| 1 | `879168` | `barcode`, trimmed text |
| 2 + 3 | `HexBolt` + `(0.5125 17 4)` | `name` = `HexBolt (0.5125 17 4)`; preserve tuple values verbatim |
| 4 | `Tool Room` | `location`, trimmed text |
| 5 | empty | Remove the verified-empty trailing field |
| No source position | — | `quantity` = 0 only after owner confirmation |
| No source position | — | `price` and `product_link` remain NULL |

Proposed prepared record, **not yet generated or imported**:

```csv
barcode,name,quantity,location
879168,HexBolt (0.5125 17 4),0,Tool Room
```

Preserve `0.5125`, `52`, `38`, and all other supplied values exactly; their presence does not authorize a correction or unit conversion. If any tuple component actually represents stock count, revise this mapping before preparing data. A name of only `HexBolt` would trigger the requested same-name skip rule: at most one row could be created and the remaining 56 would skip, assuming structural repair and no database conflicts. Keeping variant data only in notes would not solve that name collision.

### Local catalogue comparison

A read-only, repeatable-read database snapshot contained 15 existing items (including archived rows) and zero alternate barcode records. Comparing every source barcode to primary/alternate codes, and both raw and proposed names using the specified whitespace/case normalization, found **zero existing matches**.

Thus the proposed mapping yields **57 potential candidates, zero intra-file duplicate codes or proposed names, and zero current database matches**. This is a compatibility analysis, not an importer dry run or an import result. Eligibility still depends on confirming source meaning/default quantity and must be recomputed at apply time. The unmodified source must fail file-level validation with zero writes.

Current behavior to account for:

- `services/items.py::create_item` commits internally and translates **every** caught integrity error into a duplicate-barcode error. A bulk importer must not reuse that broad error classification or assume this function can participate in an outer savepoint transaction unchanged.
- Normal creation checks both primary and alternate barcodes. Archived holders currently support an explicit override; bulk import must never enable it.
- `ItemCreate` validates quantity/location but does not provide all required CSV boundary checks, including nonblank name/barcode.
- The current frontend coerces blank price to zero. CSV parsing must preserve missing price as NULL.
- Create Item is TechFM OA+ in the current router. The retrieved Obsidian mirror says Admin in one cost-redaction passage; current code uses TechFM OA+. Preserve current code's role policy.
- `docs/open-work.md`, SCL-001, records that separate barcode constraints do not prevent concurrent primary-versus-alternate claims. Name matching has no database uniqueness constraint at all.

## Stage 1: local development proof

1. Source read and fingerprint completed above. Keep the original unchanged outside committed application data.
2. Structural profile and read-only catalogue comparison completed above. Confirm tuple meaning and opening quantity; price is absent and remains NULL. Do not guess units or conversions.
3. Finalize the proposed mapping above after clarification, then prepare a separate canonical CSV. A fixed explicit preparation for this file is enough; a general mapping UI is outside this first version.
4. Implement one backend import service with Python's standard `csv` and `decimal` modules, plus a thin local command. Default to dry run; writing requires an explicit apply option and a verified local development target. Use an isolated development database or a recoverable snapshot; never seed production implicitly.
5. Dry run against the actual development catalogue. Print counts and every skip/error reason. Dry run performs no writes, including no temporary committed items or notifications.
6. Apply in local development, inspect saved values, then rerun the same file. The second run must create zero additional items and visibly report prior successes as duplicates.
7. Keep the compatibility/results report and pass the acceptance checks before adding the app interface. Import source data is not an Alembic data migration.

## Duplicate policy

Proposed name key: trim outer whitespace, collapse internal whitespace runs to one space, and Unicode-casefold. Preserve punctuation and dimensions: `1/4`, `14`, and `1-4` must not collapse into one name. Do not reuse the fuzzy catalogue search normalizer for identity. Store the trimmed display name rather than its comparison key.

Proposed barcode key: outer-whitespace trim followed by exact case-sensitive text equality, consistent with existing barcode identity. Leading zeros remain significant. Numeric-looking codes and scientific notation must never be reconstructed automatically after spreadsheet damage.

Compare against **all items, including archived items**, and all alternate barcode records. This conservative archived-name policy is a proposed import rule, not an existing database constraint.

| Condition | Outcome |
| --- | --- |
| Same name, different barcode | Skip: `duplicate_name` |
| Same primary or alternate barcode, different name | Skip: `duplicate_barcode` |
| Both match one item | Skip with both reasons |
| Name matches item A, barcode matches item B | Skip with both reasons and both holders; never choose a winner |
| Archived holder | Skip, mark holder archived; never reclaim or delete it |
| Repeated name or barcode within the CSV | First otherwise-valid, successfully accepted row wins; later rows skip and reference that source record |
| Invalid earlier row | Reject it; it does not reserve a name/barcode against a later valid row |

Matching only one field is sufficient to skip. Location does not make an otherwise duplicate name eligible. Match identifiers must be reported without cost-sensitive data leaking to unauthorized roles.

## Parsing, validation, and outcomes

- Accept UTF-8, with or without BOM, and standard quoted comma-separated CSV, including quoted commas/newlines and CRLF. Reject invalid encoding and malformed CSV; never use `split(',')`.
- Trim/case-normalize headers for the documented mapping. Reject duplicate normalized headers, missing required columns, empty files, and unresolved unexpected columns before writing. Report unknown columns instead of silently ignoring them.
- Parse the entire bounded file before apply so structural file errors cannot leave a partially imported file. A row with the wrong column count is invalid, with its source position reported.
- Skip entirely blank records and count them separately. Preserve both logical record number and physical line span for diagnostics involving quoted newlines.
- Reject negative/nonfinite or unparseable numeric values. Do not interpret currency symbols, thousands separators, or locale decimal commas unless the actual CSV mapping explicitly defines that transformation.
- Proposed limits: reuse the existing 25 MiB CSV read cap and add a 10,000-data-record cap. Enforce both in local and HTTP entry points; tune only after profiling the source file. Existing `read_capped` bounds the handler read, not the entire multipart ingress.
- Per-row terminal states: `created`, `skipped`, or `invalid`; preview uses `would_create` instead of `created`. A row gets one state and may have multiple reasons.
- Report source record/line, name, barcode, outcome, reason codes, human explanation, and conflicting item IDs or earlier record numbers. Totals must reconcile with nonblank data records; report blank records separately.

## Transactions and concurrency

Use one transaction for the bounded apply operation, with per-row savepoints for expected insert conflicts. Commit valid nonconflicting rows together; duplicate/invalid rows must not poison the session. Unexpected database/storage failures roll back the batch and return a clear failure, not a fabricated duplicate report. Never announce creation before commit.

Reuse existing item creation invariants through a small flush-only insertion path if needed; preserve existing single-item callers' commit behavior. Known unique-constraint conflicts can become skips after rollback to the savepoint and a fresh lookup. Other integrity errors must remain errors. Inspect both existing callers (`routers/items.py` and `routers/user_requests.py`) before changing the shared creation function.

The local proof may run with all other catalogue writers stopped. Before app rollout, the implementation must protect the duplicate-check-and-insert window from **all** item/name/barcode writers, not just other imports. A short PostgreSQL table lock on `items` and `item_barcodes`, acquired before reading matches and held through commit, is a candidate minimal implementation; verify lock ordering, bounded lock timeout, and concurrent-write behavior against existing writers. An import-only advisory lock is insufficient. If lock latency is unacceptable, resolve the broader namespace/concurrency design before rollout.

This feature does not retroactively deduplicate existing rows or impose global name uniqueness on manual creation. It guarantees that each incoming row is skipped if a matching holder exists when its protected apply check runs. Any stronger application-wide identity rule is separate scope.

New items receive their opening quantity directly, consistent with current item creation. Import does not restock or adjust existing items and must not fabricate stock transactions. After commit, preserve the current low-stock list refresh behavior; creating an item below threshold is not a stock-crossing push notification.

## Stage 2: Add Items interface

Add an **Import CSV** section to the existing Item entry page, available to TechFM OA+ and enforced server-side. Tools remain a separate workflow.

1. Select file and, if needed, an explicit default location.
2. Preview parsed values, proposed defaults, valid candidates, skips, and invalid rows.
3. Show an explicit **Import N eligible items** action. Disable while running to prevent duplicate submissions.
4. Revalidate the same file bytes and options against current database state when applying. Replacing the file/options clears the preview. Preview does not reserve names or barcodes.
5. Show a persistent summary such as **Imported 82 · Skipped 12 · Invalid 3**, clearly marked as completed with issues when applicable. Example counts are illustrative.
6. Show an accessible row-results table and downloadable report. Skips must not disappear into a brief toast or be labeled unqualified success. Render CSV values as text, and neutralize spreadsheet formulas in CSV report exports.

Proposed HTTP contract: authenticated `POST /items/import` multipart upload with `dry_run` defaulting to true and optional `default_location`. Use the same parser/service as the local command. Return HTTP 200 for a completed preview/import report, including mixed row outcomes; file-level validation failures use 422, size violations 413, and existing authentication/authorization conventions apply. Infrastructure failure means no successful batch commit and uses the normal server error path.

No import history table, background queue, spreadsheet dependency, remote file fetching, upsert mode, or arbitrary mapping builder is required for the initial bounded workflow. Keep a downloadable operation report with filename/hash, timestamp, operator, counts, and created item IDs for review.

## Acceptance checks

Use the existing test infrastructure and focused PostgreSQL integration checks:

1. Dry run writes nothing; apply creates valid rows with exact leading-zero barcode strings, Decimal values, NULL missing prices, and ordinary defaults.
2. Same-name and primary/alternate-barcode collisions, including archived holders, visibly skip without changing existing items or quantities.
3. Conflicting name/barcode owners report both; intra-file duplicates follow deterministic first-valid-row behavior.
4. A duplicate between two valid rows does not abort either valid insert; an invalid early row does not block a later valid row.
5. A repeat import creates zero new items. Changed database state after preview produces fresh apply-time skips.
6. BOM, quoted commas/newlines, CRLF, blank rows, bad encoding, missing/duplicate/unknown headers, invalid decimals, and row/byte limits yield the specified outcomes.
7. A known uniqueness conflict is a skip; an unrelated integrity failure is not mislabeled and rolls back the batch.
8. Concurrent imports and concurrent manual primary/alternate/name writes cannot bypass the import's protected check; lock timeout is reported without false success.
9. Lower roles cannot preview/apply; output escapes source text; exported reports do not execute spreadsheet formulas.
10. UI counts equal row outcomes; skipped/invalid rows remain visible; only committed creations refresh inventory/low-stock views.
11. This source's original six-field header/five-field records fail preflight with zero writes. After the proposed mapping is confirmed, the 57 distinct barcode/name pairs survive preparation without changed tuple values. A deliberately raw-name-only fixture reports one eligible row and 56 same-name skips against an empty catalogue.

## Outstanding evidence

- Confirm what each tuple value means, whether the tuple belongs in the item name as proposed, and whether missing opening stock should become 0. Source profiling is complete; no notes or alternate-barcode import is needed for the proposed mapping.
- Confirm proposed case/whitespace name matching and archived-name skipping against the actual catalogue and intended workflow.
- Verification completed: strict standard-library CSV parsing, full-file counts, hash, unique barcode/proposed-name assertions, row-width assertions, and a read-only local catalogue comparison. Execute import tests only after implementation; no importer exists from this work and no data was imported.
- Obsidian context consulted: `4. Notes/Repository-Docs/inventory-app-git/reviews/current-state.md`. Its indexed revision was older than the exact read, so the live source was used. No Obsidian notes were updated in this specification-only pass.
