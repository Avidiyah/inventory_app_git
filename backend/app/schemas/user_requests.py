"""Request/response schemas for the Admin User Requests queue."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class UserRequestUpdate(BaseModel):
    """Resolve or reopen a request without deleting its audit record."""

    status: Literal["open", "resolved"]
    resolution_note: Optional[str] = None

    @field_validator("resolution_note")
    @classmethod
    def _trim_note(cls, value):
        if value is None:
            return None
        return value.strip() or None


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
