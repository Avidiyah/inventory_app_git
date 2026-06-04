"""Item-notes write service.

Layer: services. The only reason this is its own module (rather
than a function inside `services/items.py`) is that the JSONB
write path has a subtle SQLAlchemy requirement that is easy to
overlook: mutating a dict in place does not mark the column dirty,
so `flag_modified` must be called explicitly. Isolating that
detail here keeps it from being copy-pasted incorrectly.
"""

import uuid

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.domain.errors import ItemNotFoundError
from app.models import Item


def replace_notes(db: Session, item_id: uuid.UUID, notes: dict) -> Item:
    """Replace `item.notes` wholesale with the given dict.

    The caller is responsible for validating `notes` first — the
    router does so via `ItemNotesUpdate`. `flag_modified` is needed
    because SQLAlchemy's change tracker compares JSONB columns by
    identity, and assignment of a new dict that happens to equal
    the old one would otherwise be skipped on commit.
    """
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise ItemNotFoundError("Item not found.")
    item.notes = notes
    flag_modified(item, "notes")
    db.commit()
    db.refresh(item)
    return item
