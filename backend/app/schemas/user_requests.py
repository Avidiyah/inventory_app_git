"""Request/response schemas for the User Requests queue."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class UserRequestUpdate(BaseModel):
    """Resolve, reopen, or correct the wording of a request.

    All three fields are optional so one PATCH shape serves both jobs: sending
    `status` moves the request through the queue, while sending `message` /
    `details` corrects how it reads. `details` is whitelisted per request type
    in the service -- a recount's frozen shortage numbers are not editable.
    """

    status: Optional[Literal["open", "resolved"]] = None
    resolution_note: Optional[str] = None
    message: Optional[str] = None
    details: Optional[dict[str, Any]] = None

    @field_validator("resolution_note", "message")
    @classmethod
    def _trim_note(cls, value):
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def _something_to_do(self):
        if self.status is None and self.message is None and self.details is None:
            raise ValueError("Provide a status, a message, or details to update.")
        return self


class CatalogueRequestCreate(BaseModel):
    """File a request for a material that has no catalogue row at all.

    Deliberately not for an in-app item at zero quantity -- that is findable
    and belongs to `inventory_recount`.
    """

    searched_text: str = Field(min_length=1, max_length=200)
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    note: Optional[str] = Field(default=None, max_length=500)
    work_order_id: Optional[UUID] = None
    source: Literal["work_orders", "find_item", "request_card"]

    @field_validator("searched_text", "note")
    @classmethod
    def _trim(cls, value):
        if value is None:
            return None
        return value.strip() or None


class MaterialRequestCreate(BaseModel):
    """File a request for a catalogue item the shelf does not have.

    The item exists (`item_id` is required); a search that found nothing is a
    `CatalogueRequestCreate`. On-hand is never checked here -- counts are
    sometimes wrong, so a request on an item with alleged stock still files
    and the staff verify.
    """

    item_id: UUID
    work_order_id: UUID
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    product_link: Optional[str] = Field(default=None, max_length=2000)
    note: Optional[str] = Field(default=None, max_length=500)

    @field_validator("product_link", "note")
    @classmethod
    def _trim(cls, value):
        if value is None:
            return None
        return value.strip() or None

    @field_validator("product_link")
    @classmethod
    def _http_only(cls, value):
        if value is None:
            return None
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("Product link must start with http:// or https://.")
        return value


class NewItemPayload(BaseModel):
    """The Add Item fields, for creating the catalogue row inline on close."""

    barcode: str = Field(min_length=1)
    name: str = Field(min_length=1)
    quantity: Decimal = Field(default=Decimal("0"), ge=0)
    location: str = Field(min_length=1)
    price: Optional[Decimal] = None
    product_link: Optional[str] = None
    override_archived: bool = False


class CatalogueRequestFulfill(BaseModel):
    """Point a request at a real item, and cascade to confirmed siblings.

    Exactly one of `item_id` / `new_item`. Linking an existing row matters as
    much as creating one: "I can't find it" is very often a misspelling of
    something already in the catalogue, and forcing a create would mean a
    duplicate row every time.

    `sibling_ids` are the other open requests the reviewer CONFIRMED name the same
    material. The server proposes that set via `GET /{id}/siblings`; it never
    acts on the proposal unsupervised, because a wrong match would retroactively
    bill material to another customer's work order.
    """

    item_id: Optional[UUID] = None
    new_item: Optional[NewItemPayload] = None
    sibling_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def _exactly_one_item_source(self):
        if (self.item_id is None) == (self.new_item is None):
            raise ValueError("Provide exactly one of item_id or new_item.")
        return self


class UserRequestResponse(BaseModel):
    id: UUID
    request_type: str
    status: str
    message: str
    item_id: Optional[UUID] = None
    item_name: Optional[str] = None
    item_barcode: Optional[str] = None
    item_price: Optional[Decimal] = None
    item_product_link: Optional[str] = None
    # The item's on-hand right now. Lets the card say "3 on hand -- staff will
    # verify" and the Materials line say "on hand 4". None for a catalogue
    # request that has not been linked to an item yet.
    item_quantity: Optional[Decimal] = None
    transaction_id: Optional[UUID] = None
    work_order_id: Optional[UUID] = None
    work_order_number: Optional[str] = None
    created_by_id: Optional[UUID] = None
    created_by_name: Optional[str] = None
    details: dict[str, Any]
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by_id: Optional[UUID] = None
    resolved_by_name: Optional[str] = None
    resolution_note: Optional[str] = None
    # True when the linked work order has been closed, so the card can warn
    # that fulfilment will create the item but skip the retroactive add.
    work_order_archived: bool = False
    # Skip notes produced by a fulfilment, surfaced once on its response.
    skipped: list[str] = Field(default_factory=list)
    # True when a material-request filing matched an existing open/stocked
    # request for the same (work order, item) and updated it instead.
    updated: bool = False
