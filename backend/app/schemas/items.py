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
from typing import Any

from pydantic import BaseModel, field_validator

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
    """

    id: UUID
    barcode: str
    name: str
    quantity: Decimal
    location: str
    notes: dict[str, Any] = {}
    created_at: datetime

    model_config = {"from_attributes": True}


class ItemNotesUpdate(BaseModel):
    """Payload for `PUT /items/{id}/notes` — a full replacement.

    The validator delegates to `domain.notes_validation.validate_notes`
    so the same whitelist (str / int / float / bool, non-blank keys)
    is enforced regardless of how notes arrive in the future.
    """

    notes: dict[str, Any]

    @field_validator("notes")
    @classmethod
    def _validate(cls, v):
        return validate_notes(v)
