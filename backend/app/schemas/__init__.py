"""Pydantic schemas package — the HTTP boundary's type system.

Layer: schemas (Pydantic only). Imports allowed: standard library,
`pydantic`, and `app.domain` (for shared validation rules). Must not
import from `app.models` (SQLAlchemy), services, or routers — schemas
sit *above* the domain and *below* HTTP, and they are what FastAPI
uses to parse request bodies and serialize response bodies.

This `__init__` re-exports every schema used by routers so that call
sites can write `from app.schemas import ItemResponse` without
knowing which submodule it lives in. Submodules are split by
resource (items / transactions / users) to mirror the router layout.
"""

from app.schemas.barcodes import BarcodeMatch, BarcodeDecodeResponse
from app.schemas.items import ItemCreate, ItemResponse, ItemNotesUpdate
from app.schemas.transactions import (
    TransactionCreate,
    TransactionResponse,
    TransactionHistoryItem,
    TransactionHistoryPage,
)
from app.schemas.users import UserCreate, UserResponse

__all__ = [
    "BarcodeMatch",
    "BarcodeDecodeResponse",
    "ItemCreate",
    "ItemResponse",
    "ItemNotesUpdate",
    "TransactionCreate",
    "TransactionResponse",
    "TransactionHistoryItem",
    "TransactionHistoryPage",
    "UserCreate",
    "UserResponse",
]
