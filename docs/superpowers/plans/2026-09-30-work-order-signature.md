# Work Order Witness Signature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Optional, lockable witness sign-off (drawn signature, printed name, phone) on every work order card.

**Architecture:** One new table + model; pure helpers in `domain/work_orders.py`; a sibling service `services/work_order_signature.py` (the main service is 3,130 lines); three routes in `routers/work_orders.py`; one new front-end module `views/workOrderSignature.js` plugged into the card builder, click delegation, and the offline-draft replay.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Postgres, pytest; vanilla ES modules, Vitest + MSW + jsdom.

**Spec:** `docs/superpowers/specs/2026-09-30-work-order-signature-design.md` (decisions S1–S15 are referenced by number below).

## Global Constraints

- Signature image ≤ 256 KB decoded; must start with the PNG magic `\x89PNG\r\n\x1a\n`; data URL prefix exactly `data:image/png;base64,`.
- Witness name trimmed, nonblank, ≤ 120 chars. Phone per S7, stored as 10 digits, shown `(555) 555-1234`.
- No inline `style=` anywhere (CSP drops it) — classes only.
- Router tests go through a real `TestClient`, never direct handler calls.
- Commands run from `backend/` with `venv/Scripts/python -m pytest …`; front end from repo root with `npx vitest run …`.
- The dev DB must be migrated (`venv/Scripts/python -m alembic upgrade head`) before DB tests; tests roll back per test.
- Commit on `main`; do **not** push (push = production deploy — ask first).

## Deviations from the spec (settled here)

| Spec says | Plan does | Why |
|---|---|---|
| "existing validation `DomainError` (→ 422)" | New `WorkOrderSignatureError` (422) and `WorkOrderAlreadySignedError` (409) in `domain/errors.py` | No generic 422 error exists; `_errors._STATUS_MAP` needs a type per status. |
| Service decodes the data URL | `decode_signature_png(data_url) -> bytes` lives in the domain beside the phone helpers | Pure function; unit-testable without a DB. |
| `WorkOrderSignatureOut` field list | Adds `captured_at_label` (server-formatted via `format_note_timestamp`) | Card shows `MM/DD/YY hh:mm AM/PM` in Central time; the server already owns that formatter. |
| `captured_by_id` FK | `ondelete="SET NULL"`, nullable; name falls back to "Name unavailable" | A hard user delete must not delete a sign-off. |
| Unspecified | `image_png` is `deferred()` on the model | Keeps bytes out of the detail load; only the PNG route reads them. |

## Review Focus

1. **Scrolling while signing on a phone** — the page must not scroll under the finger. Pinned by the CSS-class test in Task 5 (`touch-action: none` lives on `.wo-signature-pad` in `styles.css`).
2. **Double-tap Save / two devices signing at once** — exactly one row, the loser gets 409 and sees the winner. Pinned by the IntegrityError test in Task 3 and the 409-refresh test in Task 5.
3. **Oversized or non-PNG payload hitting the server directly** — rejected with 422 before decoding a giant string. Pinned by the schema `max_length` test in Task 4.
4. **Clear-then-resign shows the old image from browser cache** — `image_url` changes on every capture. Pinned by the `?v=` test in Task 4.
5. **Pad opened, card refreshed by a live event, pad re-mounted** — mounting twice must not double-bind listeners. Pinned by the idempotent-mount test in Task 5.

---

### Task 1: Table, model, error types

**Goal:** `work_order_signatures` exists in the DB and ORM; two new domain errors map to 409/422.

**Files:**
- Create: `backend/alembic/versions/a7c3e9f1b2d4_add_work_order_signatures.py` (`down_revision = "e7c9a1b3d5f7"`)
- Modify: `backend/app/models.py` (import `LargeBinary`, `String`; `from sqlalchemy.orm import deferred, relationship`; new class after `WorkOrderLaborSession`; one relationship on `WorkOrder` after `labor_sessions`)
- Modify: `backend/app/domain/errors.py` (two classes after `WorkOrderStateError`), `backend/app/routers/_errors.py` (import + `_STATUS_MAP` entries)
- Test: `backend/tests/test_work_order_signature.py` (new)

- [ ] **Step 1: Write the failing migration test** (pattern: `tests/test_catalogue_requests.py` ~L360)

```python
def _load_migration():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "a7c3e9f1b2d4_add_work_order_signatures.py"
    spec = importlib.util.spec_from_file_location("sig_rev", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_migration_drops_and_recreates_the_table(db):
    module = _load_migration()
    ctx = MigrationContext.configure(db.connection())
    exists = lambda: db.execute(text("SELECT to_regclass('work_order_signatures')")).scalar()
    assert exists() is not None          # dev DB is at head
    with Operations.context(ctx):
        module.downgrade()
    assert exists() is None
    with Operations.context(ctx):
        module.upgrade()
    assert exists() is not None
```

- [ ] **Step 2: Run** `venv/Scripts/python -m pytest tests/test_work_order_signature.py -v` → FAIL (file not found).

- [ ] **Step 3: Migration**

```python
def upgrade() -> None:
    op.create_table(
        "work_order_signatures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("work_order_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("image_png", sa.LargeBinary(), nullable=False),
        sa.Column("witness_name", sa.Text(), nullable=False),
        sa.Column("witness_phone", sa.String(10), nullable=False),
        sa.Column("captured_by_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
    )

def downgrade() -> None:
    op.drop_table("work_order_signatures")
```

- [ ] **Step 4: Model** (docstring: one per WO, S1; "unsigned" = no row)

```python
class WorkOrderSignature(Base):
    __tablename__ = "work_order_signatures"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_order_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id", ondelete="CASCADE"),
                           nullable=False, unique=True)
    # Deferred: the card detail reads the metadata; only the PNG route reads bytes.
    image_png = deferred(Column(LargeBinary, nullable=False))
    witness_name = Column(Text, nullable=False)
    witness_phone = Column(String(10), nullable=False)
    captured_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=False)

    work_order = relationship("WorkOrder", back_populates="signature")
    captured_by = relationship("User", foreign_keys=[captured_by_id], viewonly=True)
```

On `WorkOrder`: `signature = relationship("WorkOrderSignature", back_populates="work_order", uselist=False, cascade="all, delete-orphan", passive_deletes=True)`.

- [ ] **Step 5: Errors** — `WorkOrderSignatureError(DomainError)` ("bad image, name or phone on a witness sign-off. Maps to 422.") and `WorkOrderAlreadySignedError(DomainError)` ("a second save on a signed work order. Maps to 409."). Register both in `_errors.py` (`: 422`, `: 409`).

- [ ] **Step 6: Run** `venv/Scripts/python -m alembic upgrade head` then the test → PASS.

- [ ] **Step 7: Commit** `feat(work-orders): work_order_signatures table and model`

---

### Task 2: Domain helpers

**Goal:** Phone normalize/format, PNG decode, two note constants — all pure.

**Files:**
- Modify: `backend/app/domain/work_orders.py` (constants beside `NOTE_READY_TO_COMPLETE`; helpers in a new `# --- witness sign-off ---` block; add `import base64, binascii`; import the new error)
- Test: `backend/tests/test_work_orders_domain.py`

**Interfaces — Produces:**
`NOTE_SIGNED_OFF = "captured witness sign-off from {name}"`, `NOTE_SIGNATURE_CLEARED = "cleared the witness sign-off"`, `MAX_SIGNATURE_BYTES = 256 * 1024`, `MAX_WITNESS_NAME = 120`,
`normalize_witness_phone(raw: str) -> str`, `format_witness_phone(digits: str) -> str`, `normalize_witness_name(raw: str) -> str`, `decode_signature_png(data_url: str) -> bytes` — all raise `WorkOrderSignatureError`.

- [ ] **Step 1: Failing tests**

```python
@pytest.mark.parametrize("raw", ["(555) 555-1234", "555.555.1234", "1-555-555-1234", "+1 555 555 1234", "555-555-1234 ext"])
def test_phone_normalizes_to_ten_digits(raw):
    assert wo.normalize_witness_phone(raw) == "5555551234"

@pytest.mark.parametrize("raw", ["", "   ", "555-555-123", "25555551234", "555555512345", "abc"])
def test_phone_rejects_anything_not_ten_digits(raw):
    with pytest.raises(WorkOrderSignatureError):
        wo.normalize_witness_phone(raw)

def test_phone_format():
    assert wo.format_witness_phone("5555551234") == "(555) 555-1234"

def test_name_trimmed_and_bounded():
    assert wo.normalize_witness_name("  Pat Doe ") == "Pat Doe"
    for bad in ("", "   ", "x" * 121):
        with pytest.raises(WorkOrderSignatureError):
            wo.normalize_witness_name(bad)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

def test_decode_png_round_trip():
    url = "data:image/png;base64," + base64.b64encode(PNG).decode()
    assert wo.decode_signature_png(url) == PNG

@pytest.mark.parametrize("url", [
    "data:image/jpeg;base64," + base64.b64encode(PNG).decode(),     # wrong type
    "data:image/png;base64,@@@not-base64@@@",                         # malformed
    "data:image/png;base64," + base64.b64encode(b"GIF89a....").decode(),  # not PNG bytes
    "data:image/png;base64," + base64.b64encode(PNG + b"\x00" * (256 * 1024)).decode(),  # too big
])
def test_decode_png_rejects(url):
    with pytest.raises(WorkOrderSignatureError):
        wo.decode_signature_png(url)
```

- [ ] **Step 2: Run** `venv/Scripts/python -m pytest tests/test_work_orders_domain.py -k "phone or name_trimmed or decode_png" -v` → FAIL.

- [ ] **Step 3: Implement**

```python
_PNG_PREFIX = "data:image/png;base64,"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

def normalize_witness_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise WorkOrderSignatureError("Enter a 10-digit phone number.")
    return digits

def format_witness_phone(digits: str) -> str:
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"

def normalize_witness_name(raw: str) -> str:
    name = (raw or "").strip()
    if not name or len(name) > MAX_WITNESS_NAME:
        raise WorkOrderSignatureError("Enter the witness's printed name (120 characters max).")
    return name

def decode_signature_png(data_url: str) -> bytes:
    if not (data_url or "").startswith(_PNG_PREFIX):
        raise WorkOrderSignatureError("Signature must be a PNG image.")
    try:
        png = base64.b64decode(data_url[len(_PNG_PREFIX):], validate=True)
    except (binascii.Error, ValueError):
        raise WorkOrderSignatureError("Signature image is unreadable.")
    if not png.startswith(_PNG_MAGIC):
        raise WorkOrderSignatureError("Signature must be a PNG image.")
    if len(png) > MAX_SIGNATURE_BYTES:
        raise WorkOrderSignatureError("Signature image is too large.")
    return png
```

Note on "555-555-1234 ext": letters are ignored (S7 strips non-digits), so it passes.

- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat(work-orders): witness sign-off domain helpers`

---

### Task 3: Service

**Goal:** save / clear / read-PNG with visibility scoping, row lock for the note append, and the unique constraint as the race backstop.

**Files:**
- Create: `backend/app/services/work_order_signature.py`
- Test: `backend/tests/test_work_order_signature.py`

**Interfaces:**
- Consumes: Task 2 helpers; `work_orders.get_visible_work_order(db, id, user)`; `wo.append_note_log`.
- Produces: `save_signature(db, work_order_id, *, user, image_data_url, witness_name, witness_phone) -> WorkOrder`, `clear_signature(db, work_order_id, *, user) -> WorkOrder`, `get_signature_png(db, work_order_id, *, user) -> bytes`.

- [ ] **Step 1: Failing tests** (seed users like `test_work_orders_router._seed_user`; create WOs with `wos.get_or_create_work_order(db, number=f"WO-SIG-{uuid4().hex[:8]}", created_by_id=admin.id, assigned_to_id=tech.id)`; `PNG_URL` = data URL of `_PNG_MAGIC + b"\0"*16`)

```python
def test_save_inserts_one_row_and_a_note_line(db): ...
    # assert row fields, phone stored "5555551234", notes ends with "captured witness sign-off from Pat Doe"
def test_second_save_conflicts(db): ...                  # pytest.raises(WorkOrderAlreadySignedError)
def test_concurrent_insert_maps_to_conflict(db, monkeypatch): ...
    # insert a WorkOrderSignature row directly, then
    # monkeypatch.setattr(signature_service, "_already_signed", lambda *a: False)
    # so the unique constraint is what fires -> WorkOrderAlreadySignedError, not IntegrityError
def test_save_on_invisible_work_order_is_not_found(db): ...   # unassigned technician
def test_bad_payloads_rejected_and_nothing_written(db): ...   # non-PNG, oversize, blank name -> WorkOrderSignatureError; no row
def test_clear_deletes_row_and_appends_note(db): ...          # supervisor; notes ends with "cleared the witness sign-off"
def test_clear_when_unsigned_is_not_found(db): ...
def test_archive_and_restore_keep_the_row(db): ...            # wos.archive_work_order / restore_work_order
def test_work_order_delete_cascades(db): ...
    # db.execute(delete(WorkOrder).where(WorkOrder.id == wid)); count rows == 0  (proves ON DELETE CASCADE)
def test_get_png_returns_bytes_and_404s_when_unsigned(db): ...
```

- [ ] **Step 2: Run** `venv/Scripts/python -m pytest tests/test_work_order_signature.py -v` → new tests FAIL (import error).

- [ ] **Step 3: Implement**

```python
"""Witness sign-off on a work order (spec 2026-09-30). One row per work order,
locked once saved; Supervisor+ may clear it. Sibling of `work_orders.py`,
which is past its size budget."""

def _locked_visible(db, work_order_id, user) -> WorkOrder:
    get_visible_work_order(db, work_order_id, user)  # 404 if archived / not visible
    # Row lock: `notes` is read-modify-write, same as every other note append.
    return (db.query(WorkOrder).populate_existing()
              .filter(WorkOrder.id == work_order_id).with_for_update().one())

def _already_signed(db, work_order_id) -> bool:
    return db.query(WorkOrderSignature.id).filter_by(work_order_id=work_order_id).first() is not None

def save_signature(db, work_order_id, *, user, image_data_url, witness_name, witness_phone):
    png = wo.decode_signature_png(image_data_url)
    name = wo.normalize_witness_name(witness_name)
    phone = wo.normalize_witness_phone(witness_phone)
    work_order = _locked_visible(db, work_order_id, user)
    if _already_signed(db, work_order.id):
        raise WorkOrderAlreadySignedError("This work order is already signed.")
    now = datetime.now(timezone.utc)
    db.add(WorkOrderSignature(work_order_id=work_order.id, image_png=png, witness_name=name,
                              witness_phone=phone, captured_by_id=user.id, captured_at=now))
    work_order.notes = wo.append_note_log(work_order.notes, wo.NOTE_SIGNED_OFF.format(name=name),
                                          author_name=user.full_name, occurred_at=now)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise WorkOrderAlreadySignedError("This work order is already signed.")
    return work_order

def clear_signature(db, work_order_id, *, user):
    work_order = _locked_visible(db, work_order_id, user)
    row = db.query(WorkOrderSignature).filter_by(work_order_id=work_order.id).first()
    if row is None:
        raise WorkOrderNotFoundError("This work order has no signature.")
    db.delete(row)
    work_order.notes = wo.append_note_log(work_order.notes, wo.NOTE_SIGNATURE_CLEARED,
                                          author_name=user.full_name,
                                          occurred_at=datetime.now(timezone.utc))
    db.commit()
    return work_order

def get_signature_png(db, work_order_id, *, user) -> bytes:
    get_visible_work_order(db, work_order_id, user)
    png = (db.query(WorkOrderSignature.image_png)
             .filter_by(work_order_id=work_order_id).scalar())
    if png is None:
        raise WorkOrderNotFoundError("This work order has no signature.")
    return png
```

The Supervisor+ gate for clear is the router's `require_min_role` (Task 4); the service trusts it, like `restore_work_order`.

- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat(work-orders): witness sign-off service`

---

### Task 4: Schemas + routes

**Goal:** POST / DELETE / GET-PNG routes; `WorkOrderDetail.signature`.

**Files:**
- Modify: `backend/app/schemas/work_orders.py` (two classes before `WorkOrderDetail`; one field on it)
- Modify: `backend/app/routers/work_orders.py` (`_signature_out` helper after `_labor_detail`; `signature=` in `_detail`; three routes after `list_work_order_requests`)
- Modify: `tests/frontend/helpers/factories.js` (`signature: null` in `workOrderDetail` — keeps the drift test green)
- Test: `backend/tests/test_work_order_signature.py`

**Interfaces — Produces (JSON):**
`POST /work-orders/{id}/signature` body `{image, witness_name, witness_phone}` → 201 `WorkOrderDetail`;
`WorkOrderDetail.signature: {witness_name, witness_phone_display, captured_by_name, captured_at, captured_at_label, image_url} | null`.

- [ ] **Step 1: Failing router tests** (real `TestClient`, cookie `session`, `app.dependency_overrides[get_db] = lambda: db` exactly as `test_work_orders_router._numbers`)

```python
def test_assigned_technician_saves_and_detail_carries_signature(db): ...
    # POST -> 201; body["signature"]["witness_phone_display"] == "(555) 555-1234"
    # image_url == f"/work-orders/{id}/signature.png?v={int(captured_at.timestamp())}"
    # GET /work-orders/{id} -> signature present
def test_unsigned_detail_has_null_signature(db): ...
def test_unassigned_technician_gets_404(db): ...
def test_second_save_is_409(db): ...
def test_bad_phone_is_422(db): ...
def test_oversized_image_string_is_422_before_the_service(db): ...
    # image = "data:image/png;base64," + "A" * 400_000  -> 422 from Pydantic max_length
def test_clear_is_403_for_technician_and_200_for_supervisor(db): ...   # 200 body has signature null
def test_png_route_content_type_and_no_store(db): ...
    # 200, image/png, Cache-Control no-store, body == PNG bytes; unsigned -> 404
```

- [ ] **Step 2: Run** → FAIL (404/405 on the new paths).

- [ ] **Step 3: Schemas**

```python
class WorkOrderSignatureCreate(BaseModel):
    # ~350 KB of base64 is the 256 KB decoded cap plus the prefix; rejects a
    # giant body before the service decodes it.
    image: str = Field(max_length=360_000)
    witness_name: str = Field(max_length=500)
    witness_phone: str = Field(max_length=40)

class WorkOrderSignatureOut(BaseModel):
    witness_name: str
    witness_phone_display: str
    captured_by_name: str
    captured_at: datetime
    captured_at_label: str
    image_url: str
```

`WorkOrderDetail`: `signature: Optional[WorkOrderSignatureOut] = None`.

- [ ] **Step 4: Router**

```python
def _signature_out(work_order: WorkOrder) -> Optional[WorkOrderSignatureOut]:
    sig = getattr(work_order, "signature", None)
    if sig is None:
        return None
    return WorkOrderSignatureOut(
        witness_name=sig.witness_name,
        witness_phone_display=wo.format_witness_phone(sig.witness_phone),
        captured_by_name=sig.captured_by.full_name if sig.captured_by else "Name unavailable",
        captured_at=sig.captured_at,
        captured_at_label=wo.format_note_timestamp(sig.captured_at),
        # Cache-buster: a clear-then-resign must never show the old image.
        image_url=f"/work-orders/{work_order.id}/signature.png?v={int(sig.captured_at.timestamp())}",
    )
```

Add `signature=_signature_out(work_order),` to the `WorkOrderDetail(...)` call in `_detail`.

Routes (import `work_order_signature as signature_service`, the two schemas):

```python
@router.post("/{work_order_id}/signature", response_model=WorkOrderDetail, status_code=201)
def save_work_order_signature(work_order_id: uuid.UUID, payload: WorkOrderSignatureCreate,
                              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Capture the witness sign-off (S1–S3). 404 not visible, 409 already signed, 422 bad input."""
    try:
        signature_service.save_signature(db, work_order_id, user=user, image_data_url=payload.image,
                                         witness_name=payload.witness_name, witness_phone=payload.witness_phone)
        _emit_status_changed(work_order_id)
        return _detail(wo_service.get_work_order(db, work_order_id, user=user),
                       include_price=_can_see_price(user), viewer_id=user.id)
    except DomainError as exc:
        raise to_http(exc)

@router.delete("/{work_order_id}/signature", response_model=WorkOrderDetail,
               responses=_forbidden(roles.ROLE_SUPERVISOR))
def clear_work_order_signature(work_order_id: uuid.UUID,
                               user: User = Depends(require_min_role(roles.ROLE_SUPERVISOR)),
                               db: Session = Depends(get_db)):
    """Clear the sign-off so it can be recaptured (S5). 404 when unsigned."""
    ...same shape: clear_signature, _emit_status_changed, return _detail(...)

@router.get("/{work_order_id}/signature.png")
def get_work_order_signature_png(work_order_id: uuid.UUID,
                                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        png = signature_service.get_signature_png(db, work_order_id, user=user)
    except DomainError as exc:
        raise to_http(exc)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})
```

- [ ] **Step 5: Run** `venv/Scripts/python -m pytest tests/test_work_order_signature.py tests/test_work_orders_router.py -v` → PASS; `npx vitest run tests/frontend/unit/api.endpoints.test.js` → PASS (factory field added).

- [ ] **Step 6: Commit** `feat(work-orders): witness sign-off routes`

---

### Task 5: Card, pad, wiring, styles

**Goal:** The Signature section renders last on every card (S15), draws, saves, locks, and clears.

**Files:**
- Create: `backend/static/views/workOrderSignature.js`
- Modify: `backend/static/views/workOrderCardHtml.js` (import; append `signatureSectionHtml(detail)` after the Labor term in `renderBody`)
- Modify: `backend/static/views/workOrderActions.js` (three branches in the `try` chain; one capture-phase `toggle` listener; imports)
- Modify: `backend/static/api.js` (two wrappers after `apiDeleteWorkOrderLabor`)
- Modify: `backend/static/styles.css` (after `.wo-notes-message`)
- Modify: `tests/frontend/helpers/endpointTable.js` (two rows), `tests/frontend/views/workOrders/actionCoverage.test.js` (`ACTIONS` += `"clear-signature"`, `"clear-signature-pad"`, `"save-signature"`, kept alphabetical)
- Test: `tests/frontend/views/workOrders/signature.test.js` (new)

**Interfaces — Produces:**
- `api.js`: `apiSaveWorkOrderSignature(workOrderId, { image, witnessName, witnessPhone })` → POST snake_case body; `apiClearWorkOrderSignature(workOrderId)` → DELETE, returns detail JSON.
- `workOrderSignature.js`: `normalizePhone(raw) -> string|null`, `signatureSectionHtml(detail) -> string`, `mountSignaturePad(sectionEl) -> void` (idempotent via `sectionEl.dataset.padMounted`), `clearSignaturePad(sectionEl)`, `signaturePayload(sectionEl) -> {image, witnessName, witnessPhone}`, `restoreSignatureDraft(sectionEl, payload) -> void` (Task 6).

- [ ] **Step 1: Failing tests** in `signature.test.js`. Mount with the same local `open({role, status, detail})` helper as `actions.test.js` (copy it). Stub canvas with a local mock (jsdom has none):

```js
function stubPad() {
  const ctx = { fillRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(),
    stroke: vi.fn(), drawImage: vi.fn(), setTransform: vi.fn() };
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);
  HTMLCanvasElement.prototype.toDataURL = vi.fn(() => "data:image/png;base64,iVBORw0KGgo=");
  return ctx;
}
const stroke = (canvas) => ["pointerdown", "pointermove", "pointerup"]
  .forEach((t) => canvas.dispatchEvent(new MouseEvent(t, { bubbles: true, clientX: 5, clientY: 5 })));
```

Tests (each `describe` names the quoted action so the audit sees it):
- `normalizePhone`: `"(555) 555-1234"`→`"5555551234"`, `"15555551234"`→ten digits, `"555-5555"`→`null`, `"25555551234"`→`null`.
- Renders a `.wo-signature-section` as the **last** `.wo-section-card`, for a Technician too (S3/S4).
- `"save-signature"`: disabled until stroke + name + valid phone; click → POST `/work-orders/:id/signature` with `{image, witness_name, witness_phone}`, then refresh (detail GET count), section reopened.
- `"save-signature"` 409: respond 409 → card refreshed and `.wo-signature-message` shows the server detail.
- Locked view (detail with `signature` set): `<img class="wo-signature-image">` `src` equals `image_url`; name, phone display, `Captured by … on …` text; no canvas.
- `"clear-signature"`: button present for `supervisor`, absent for `technician`; click → DELETE and refresh; **no** confirm overlay.
- `"clear-signature-pad"`: after a stroke, click → `fillRect` called again and Save disabled.
- Mounting twice (toggle open, refresh, toggle open) → one stroke produces one `beginPath` per pointerdown (no double listeners).
- `styles.css` contains `.wo-signature-pad` with `touch-action: none` (read the file with `node:fs`, as `visualClarity.test.js` does).

- [ ] **Step 2: Run** `npx vitest run tests/frontend/views/workOrders/signature.test.js tests/frontend/views/workOrders/actionCoverage.test.js` → FAIL.

- [ ] **Step 3: `api.js`**

```js
export async function apiSaveWorkOrderSignature(workOrderId, { image, witnessName, witnessPhone }) {
  return jsonRequest(`/work-orders/${workOrderId}/signature`, "POST", {
    image, witness_name: witnessName, witness_phone: witnessPhone,
  });
}

export async function apiClearWorkOrderSignature(workOrderId) {
  return parseResponse(await rawFetch(`/work-orders/${workOrderId}/signature`, {
    method: "DELETE", credentials: "include",
  }));
}
```

Endpoint rows: `{ fn: "apiSaveWorkOrderSignature", args: [12, { image: "data:x", witnessName: "Pat", witnessPhone: "5555551234" }], method: "POST", url: "/work-orders/12/signature", body: { image: "data:x", witness_name: "Pat", witness_phone: "5555551234" } }` and `{ fn: "apiClearWorkOrderSignature", args: [12], method: "DELETE", url: "/work-orders/12/signature" }`.

- [ ] **Step 4: `workOrderSignature.js`** (header comment: layer = builders + pad; handlers live in workOrderActions.js; imports only `format.js`, `workOrderPresenters.js`)

```js
export function normalizePhone(raw) {
  let digits = String(raw ?? "").replace(/\D/g, "");
  if (digits.length === 11 && digits.startsWith("1")) digits = digits.slice(1);
  return digits.length === 10 ? digits : null;   // mirror of domain S7
}

export function signatureSectionHtml(detail) {
  const sig = detail.signature;
  const body = sig
    ? `<img class="wo-signature-image" alt="Witness signature" src="${escapeHtml(sig.image_url)}">
       <p><strong>${escapeHtml(sig.witness_name)}</strong> · ${escapeHtml(sig.witness_phone_display)}</p>
       <p class="hint">Captured by ${escapeHtml(sig.captured_by_name)} on ${escapeHtml(sig.captured_at_label)}</p>
       ${isSupervisorPlus() ? `<button type="button" class="btn-danger" data-action="clear-signature">Clear signature</button>` : ""}`
    : `<canvas class="wo-signature-pad" aria-label="Signature pad"></canvas>
       <div class="wo-signature-pad-actions"><button type="button" class="secondary-btn" data-action="clear-signature-pad">Clear</button></div>
       <label class="wo-signature-field"><span>Witness Printed Name:</span><input type="text" class="wo-signature-name" maxlength="120"></label>
       <label class="wo-signature-field"><span>Phone number:</span><input type="tel" class="wo-signature-phone" autocomplete="tel"></label>
       <div class="wo-notes-actions"><button type="button" data-action="save-signature" disabled>Save signature</button></div>`;
  return `<details class="wo-section-card wo-signature-section">
            <summary class="wo-section-summary">Signature</summary>
            <div class="wo-section-content">${body}<p class="wo-signature-message" aria-live="polite"></p></div>
          </details>`;
}

function updateSaveEnabled(section) {
  const save = section.querySelector('[data-action="save-signature"]');
  if (!save) return;
  save.disabled = !(section.dataset.hasStroke === "1"
    && section.querySelector(".wo-signature-name")?.value.trim()
    && normalizePhone(section.querySelector(".wo-signature-phone")?.value));
}

function wipe(canvas) {
  const ctx = canvas.getContext("2d");
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
}

export function mountSignaturePad(section) {
  const canvas = section.querySelector(".wo-signature-pad");
  if (!canvas || section.dataset.padMounted) return;
  section.dataset.padMounted = "1";
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(canvas.clientWidth * ratio);
  canvas.height = Math.round(canvas.clientHeight * ratio);
  // ponytail: a rotate/resize after mount keeps the old backing size (strokes
  // stay correct, just scaled); re-size on resize only if field users hit it.
  wipe(canvas);
  const ctx = canvas.getContext("2d");
  const point = (e) => {
    const r = canvas.getBoundingClientRect();
    return [(e.clientX - r.left) * (canvas.width / (r.width || 1)),
            (e.clientY - r.top) * (canvas.height / (r.height || 1))];
  };
  let drawing = false;
  canvas.addEventListener("pointerdown", (e) => {
    drawing = true;
    canvas.setPointerCapture?.(e.pointerId);
    Object.assign(ctx, { strokeStyle: "#000", lineWidth: 2.5 * ratio, lineCap: "round", lineJoin: "round" });
    ctx.beginPath();
    ctx.moveTo(...point(e));
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!drawing) return;
    ctx.lineTo(...point(e));
    ctx.stroke();
    section.dataset.hasStroke = "1";
    updateSaveEnabled(section);
  });
  const end = () => { drawing = false; };
  canvas.addEventListener("pointerup", end);
  canvas.addEventListener("pointercancel", end);
  section.addEventListener("input", () => updateSaveEnabled(section));
}

export function clearSignaturePad(section) {
  const canvas = section.querySelector(".wo-signature-pad");
  if (canvas) wipe(canvas);
  delete section.dataset.hasStroke;
  updateSaveEnabled(section);
}

export function signaturePayload(section) {
  return {
    image: section.querySelector(".wo-signature-pad").toDataURL("image/png"),
    witnessName: section.querySelector(".wo-signature-name").value.trim(),
    witnessPhone: normalizePhone(section.querySelector(".wo-signature-phone").value),
  };
}
```

- [ ] **Step 5: Card + actions wiring**

`workOrderCardHtml.js` `renderBody`: `(sup || assignedToCurrentUser ? laborSectionHtml(detail) : "") + signatureSectionHtml(detail) +`.

`workOrderActions.js`:

```js
// `toggle` does not bubble; capture it so a collapsed card never builds a pad.
listEl.addEventListener("toggle", (event) => {
  const section = event.target;
  if (section.matches?.(".wo-signature-section") && section.open) mountSignaturePad(section);
}, true);
```

In the `try` chain:

```js
} else if (action === "clear-signature-pad") {
  clearSignaturePad(btn.closest(".wo-signature-section"));
} else if (action === "save-signature") {
  const section = btn.closest(".wo-signature-section");
  const payload = signaturePayload(section);
  saveDraft(workOrderId, "signature", { number: cardEl.dataset.number, action: "save-signature", payload });
  try {
    await apiSaveWorkOrderSignature(workOrderId, payload);
  } catch (err) {
    if (err?.status !== 409) throw err;
    // Someone else signed first: show the winner, keep the draft marked.
    markDraftError(workOrderId, "signature", err);
    await refreshCard(cardEl, ".wo-signature-section");
    setMessage(cardEl.querySelector(".wo-signature-message"), friendlyError(err, "Already signed."), "error");
    return;
  }
  clearDraft(workOrderId, "signature");
  await refreshCard(cardEl, ".wo-signature-section");
} else if (action === "clear-signature") {
  await apiClearWorkOrderSignature(workOrderId);
  await refreshCard(cardEl, ".wo-signature-section");
}
```

(`markDraftError` joins the existing `workOrderDrafts.js` import. `refreshCard(..., ".wo-signature-section")` sets `open = true`, which fires `toggle` and mounts the fresh pad.)

- [ ] **Step 6: CSS**

```css
.wo-signature-pad {
    display: block;
    width: 100%;
    height: 180px;
    background-color: #fff;     /* black ink on white in both themes (S13) */
    border: 1px solid var(--panel-rule);
    border-radius: var(--radius-sm);
    touch-action: none;         /* the finger draws; the page does not scroll */
}
.wo-signature-pad-actions { display: flex; justify-content: flex-end; margin: var(--space-2) 0; }
.wo-signature-field { display: block; margin-bottom: var(--space-2); }
.wo-signature-field input { width: 100%; }
.wo-signature-image { display: block; max-width: 100%; background-color: #fff; border-radius: var(--radius-sm); }
.wo-signature-message { margin-bottom: 0; }
```

- [ ] **Step 7: Run** `npx vitest run tests/frontend` → PASS (whole suite: the render/roles/visualClarity suites count sections).

- [ ] **Step 8: Commit** `feat(work-orders): signature card and pad`

---

### Task 6: Offline replay and resume (S11)

**Goal:** A dropped save replays on reconnect; a forced re-login restores name, phone, and the drawn image.

**Files:**
- Modify: `backend/static/workOrderDrafts.js` (`SECTION_SELECTOR.signature = ".wo-signature-section"`)
- Modify: `backend/static/views/workOrderRetry.js` (`RETRY_ACTIONS["save-signature"]`, import)
- Modify: `backend/static/views/workOrderSignature.js` (`restoreSignatureDraft`)
- Modify: `backend/static/views/workOrderRouting.js` (`fillDraftFields` branch)
- Test: `tests/frontend/views/workOrders/offlineRecovery.test.js`

- [ ] **Step 1: Failing tests** (follow the file's existing add-labor replay/resume tests)
- A stored `save-signature` draft replays as POST `/work-orders/:id/signature` on reconnect and is cleared on 201.
- Replay answered 409 → draft kept with `lastError.status === 409`, no further retry.
- Resume after login with a `signature` draft: section open, `.wo-signature-name` / `.wo-signature-phone` filled, `drawImage` called on the pad context, Save enabled.

- [ ] **Step 2: Run** `npx vitest run tests/frontend/views/workOrders/offlineRecovery.test.js` → FAIL.

- [ ] **Step 3: Implement**

```js
// workOrderRetry.js
"save-signature": (workOrderId, payload) => apiSaveWorkOrderSignature(workOrderId, payload),

// workOrderSignature.js
export function restoreSignatureDraft(section, { image, witnessName, witnessPhone }) {
  mountSignaturePad(section);
  section.querySelector(".wo-signature-name").value = witnessName ?? "";
  section.querySelector(".wo-signature-phone").value = witnessPhone ?? "";
  const canvas = section.querySelector(".wo-signature-pad");
  const img = new Image();
  img.onload = () => {
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    section.dataset.hasStroke = "1";
    section.dispatchEvent(new Event("input"));   // re-run the Save gate
  };
  img.src = image;
}

// workOrderRouting.js fillDraftFields
} else if (action === "save-signature") {
  if (section.querySelector(".wo-signature-pad")) restoreSignatureDraft(section, payload);
}
```

The locked view has no pad, so a resume onto an already-signed card is a no-op. In jsdom `Image.onload` never fires — the test triggers it by stubbing `global.Image` with a class whose `src` setter calls `onload()`.

- [ ] **Step 4: Run** `npx vitest run tests/frontend` → PASS. **Step 5: Commit** `feat(work-orders): signature joins offline draft replay`

---

### Task 7: Docs and full verification

**Goal:** Living docs describe the feature; everything green.

**Files:**
- Modify: `docs/endpoint-map.md` — three rows after the last work-order route (auth, `work_orders.py` → `work_order_signature.*`, tables `work_order_signatures (r/w), work_orders (r/w notes)`, wrappers `apiSaveWorkOrderSignature` / `apiClearWorkOrderSignature`, `workOrderActions.js`); schema line for `WorkOrderSignatureCreate` / `WorkOrderSignatureOut`. The api test requires both wrapper names here.
- Modify: `docs/current-state.md` — one clipped bullet under Work Orders: optional Signature card, locked after save, Supervisor+ clear, note-log lines. Stay in budget; delete anything stale you touch.

- [ ] **Step 1:** Edit both docs.
- [ ] **Step 2:** `cd backend && venv/Scripts/python -m pytest -q` → all pass (known env flake: `test_cascade_deletes_with_user` on a dev DB with real cloud-session rows — not a regression).
- [ ] **Step 3:** `npx vitest run` from repo root → all pass.
- [ ] **Step 4: Commit** `docs: witness signature card`. Stop — the user runs the manual checks from the spec's Testing section and decides when to push.
