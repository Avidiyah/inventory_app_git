"""Item request/response schemas.

Layer: schemas. Consumed by `app/routers/items.py` for request
parsing (`ItemCreate`, `ItemNotesUpdate`) and response serialization
(`ItemResponse`). The notes-value whitelist is delegated to
`app.domain.notes_validation` so the rule lives in the domain and
can be unit-tested without Pydantic.
"""

from uuid import UUID
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, field_validator, model_validator

from app.domain.notes_validation import validate_notes


class ItemCreate(BaseModel):
    """Payload for `POST /items`.

    Field validators enforce the two boundary rules that are cheaper
    to catch here than in the service: non-negative starting quantity
    and a non-blank location string. Barcode/name uniqueness is a
    database concern and is surfaced via `DuplicateBarcodeError` from
    the service layer.
    """

    barcode: str
    name: str
    quantity: Decimal = Decimal("0")
    location: str
    price: Optional[Decimal] = None
    product_link: Optional[str] = None
    # When the barcode is held only by an archived (deleted) item, the
    # service raises a 409 the user can confirm; the retry sends this True to
    # free that archived holder and proceed. Defaults False (the first try).
    override_archived: bool = False

    @field_validator("quantity")
    @classmethod
    def quantity_must_not_be_negative(cls, v):
        if v < 0:
            raise ValueError("Quantity cannot be negative.")
        return v

    @field_validator("location")
    @classmethod
    def location_not_blank(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Location is required.")
        return v


class ItemResponse(BaseModel):
    """Outbound shape for any endpoint returning an item.

    `from_attributes=True` lets FastAPI build this directly from a
    SQLAlchemy `Item` ORM instance — the router never has to convert
    rows to dicts by hand.

    `price` and `product_link` are cost-sensitive and are surfaced ONLY
    to Admin/Owner. The router (`app/routers/items.py::_item_response`)
    nulls both for lower roles before serialising, so a Supervisor /
    Technician never receives them even though the field exists on the
    schema. The frontend additionally hides the columns, but the backend
    gate is the authoritative one.

    `barcode` is the canonical/display code. `barcodes` is the list of
    *additional* package codes (from the `item_barcodes` child table).
    Because the ORM exposes those as `Item.alt_barcodes` objects rather
    than strings, `from_attributes` cannot fill `barcodes` directly --
    `_item_response` sets it explicitly from `[b.code for b in
    item.alt_barcodes]`.
    """

    id: UUID
    barcode: str
    name: str
    quantity: Decimal
    location: str
    notes: dict[str, Any] = {}
    barcodes: list[str] = []
    price: Optional[Decimal] = None
    product_link: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ItemNotesUpdate(BaseModel):
    """Payload for `PATCH /items/{id}/notes` — a full replacement.

    The validator delegates to `domain.notes_validation.validate_notes`
    so the same whitelist (str / int / float / bool, non-blank keys)
    is enforced regardless of how notes arrive in the future.
    """

    notes: dict[str, Any]

    @field_validator("notes")
    @classmethod
    def _validate(cls, v):
        return validate_notes(v)


class ItemBarcodesUpdate(BaseModel):
    """Payload for `PATCH /items/{id}/barcodes` -- a full replacement of an
    item's *additional* barcodes (the canonical `barcode` is edited via
    `PATCH /items/{id}`).

    The validator normalises the list the same way the Notes editor
    normalises keys: each code is stripped, blanks are dropped, and an
    in-list duplicate is rejected (a duplicate is almost always a typo and
    would otherwise be silently collapsed). Cross-item / primary-vs-alt
    uniqueness is a database/service concern, surfaced as
    `DuplicateBarcodeError` by `services.items.replace_barcodes`.
    """

    barcodes: list[str]
    # See `ItemCreate.override_archived`: confirms reuse of a code currently
    # held by an archived item, freeing that holder. Only the *added* codes
    # are checked, so this matters when a newly-added code hits an archived
    # owner; retained codes are already known-valid.
    override_archived: bool = False

    @field_validator("barcodes")
    @classmethod
    def _clean(cls, v):
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in v:
            code = raw.strip()
            if not code:
                continue
            if code in seen:
                raise ValueError("Duplicate barcode in the list.")
            seen.add(code)
            cleaned.append(code)
        return cleaned


class ItemUpdate(BaseModel):
    """Payload for `PATCH /items/{id}` — a partial edit of any subset of
    barcode, name, location, price, or product_link.

    Partial-update semantics rely on Pydantic v2's `model_fields_set`,
    which distinguishes "field omitted" from "field explicitly sent"
    (including an explicit `null`). At least one field must be sent — an
    empty body is a client bug, not a no-op. The router forwards only the
    fields actually sent (`model_dump(exclude_unset=True)`), so an omitted
    field is never confused with "set to null".

    `barcode` / `name` / `location` back NOT NULL columns, so sending any
    of them as `null` or blank is rejected. `price` / `product_link` are
    nullable, so an explicit `null` clears the stored value (this is how a
    price or product link is removed). Quantity is deliberately not
    editable here — direct quantity changes go through
    `POST /transactions/adjust` so the audit trail is preserved. Barcode
    uniqueness is a database concern, surfaced as `DuplicateBarcodeError`
    by the service layer.
    """

    barcode: Optional[str] = None
    name: Optional[str] = None
    location: Optional[str] = None
    price: Optional[Decimal] = None
    product_link: Optional[str] = None
    # See `ItemCreate.override_archived`: confirms reuse of a new primary
    # barcode currently held by an archived item. Not one of the editable
    # columns -- it is a flag the router forwards to the service, so it is
    # excluded from the "at least one field" / NOT NULL checks below.
    override_archived: bool = False

    @field_validator("barcode", "name", "location")
    @classmethod
    def _strip_if_present(cls, v):
        # Trim non-null values; the not-null / not-blank rule for these
        # three NOT NULL columns is enforced in `_check`, where the
        # "explicitly sent" signal (`model_fields_set`) is available to
        # tell an explicit null apart from an omitted field.
        if v is None:
            return v
        return v.strip()

    @model_validator(mode="after")
    def _check(self):
        # `override_archived` is a control flag, not an edit, so it does not
        # by itself satisfy the "at least one field" rule.
        if not (self.model_fields_set - {"override_archived"}):
            raise ValueError("At least one field is required.")
        # NOT NULL columns: a field that was sent must be a non-blank
        # string (an explicit null or blank is rejected). An omitted field
        # is fine — it simply will not be forwarded to the service.
        for field in ("barcode", "name", "location"):
            if field in self.model_fields_set and not getattr(self, field):
                raise ValueError(f"{field} cannot be blank.")
        return self
