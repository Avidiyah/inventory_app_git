"""Database integration tests for reusing a barcode held by an archived item.

Deleting an item soft-archives it, so its barcode(s) stay claimed. Applying
one of those codes to a live item (on create, primary-barcode edit, or
additional-barcode add) used to be a flat duplicate. Now it is a recoverable
`ArchivedBarcodeConflictError` (409) the caller can confirm and retry with
`override_archived=True`, which frees the archived holder:

- a clean archived item (no history) is purged outright;
- one with transaction history keeps its archived shell (so the History join
  still resolves) but has the conflicting code released.

A *live* holder is never bypassed, even with the override. These skip if no
DB (the `db` fixture).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.errors import ArchivedBarcodeConflictError, DuplicateBarcodeError
from app.models import Item, Transaction
from app.services import items as items_service


def _seed_item(db, *, barcode, name="Widget", location="Bay 1", archived=False):
    item = Item(
        barcode=barcode,
        name=name,
        quantity=Decimal("5"),
        location=location,
    )
    if archived:
        item.archived_at = datetime.now(timezone.utc)
    db.add(item)
    db.flush()
    return item


def _seed_history(db, item):
    """Give `item` a single ledger row so it counts as having history."""
    db.add(
        Transaction(
            item_id=item.id,
            transaction_type="stock",
            quantity=Decimal("1"),
        )
    )
    db.flush()


def _create(db, barcode, **kwargs):
    return items_service.create_item(
        db,
        barcode=barcode,
        name=kwargs.pop("name", "New Item"),
        quantity=Decimal("0"),
        location=kwargs.pop("location", "Bay 2"),
        **kwargs,
    )


# --- create_item -----------------------------------------------------

def test_archived_code_blocks_create_without_override(db):
    _seed_item(db, barcode="ARCH-1", archived=True)
    with pytest.raises(ArchivedBarcodeConflictError):
        _create(db, "ARCH-1")


def test_override_purges_clean_archived_item(db):
    archived = _seed_item(db, barcode="ARCH-2", archived=True)
    archived_id = archived.id

    new = _create(db, "ARCH-2", override_archived=True)

    assert new.barcode == "ARCH-2"
    # No history -> the archived clutter is removed entirely.
    assert db.query(Item).filter(Item.id == archived_id).first() is None


def test_override_keeps_shell_and_retires_code_when_history_exists(db):
    archived = _seed_item(db, barcode="ARCH-3", archived=True)
    _seed_history(db, archived)
    archived_id = archived.id

    new = _create(db, "ARCH-3", override_archived=True)

    assert new.barcode == "ARCH-3"
    shell = db.query(Item).filter(Item.id == archived_id).first()
    assert shell is not None                  # kept for the audit trail
    assert shell.archived_at is not None      # still archived
    assert shell.barcode != "ARCH-3"          # code released to the new item
    assert "ARCH-3" in shell.barcode          # original kept up front for History


def test_live_duplicate_is_never_bypassed_by_override(db):
    _seed_item(db, barcode="LIVE-1")  # live, not archived
    with pytest.raises(DuplicateBarcodeError):
        _create(db, "LIVE-1", override_archived=True)


def test_archived_alternate_code_also_conflicts(db):
    # The conflicting code is an archived item's *additional* barcode, not its
    # primary -- the holder lookup must still find it.
    archived = _seed_item(db, barcode="ARCH-4", archived=True)
    items_service.replace_barcodes(db, archived.id, ["ALT-4"])
    with pytest.raises(ArchivedBarcodeConflictError):
        _create(db, "ALT-4")


# --- replace_barcodes (add an additional code) -----------------------

def test_add_alt_barcode_reusing_archived_primary(db):
    live = _seed_item(db, barcode="LIVE-2")
    archived = _seed_item(db, barcode="ARCH-5", archived=True)
    archived_id = archived.id

    with pytest.raises(ArchivedBarcodeConflictError):
        items_service.replace_barcodes(db, live.id, ["ARCH-5"])

    updated = items_service.replace_barcodes(
        db, live.id, ["ARCH-5"], override_archived=True
    )
    assert [bc.code for bc in updated.alt_barcodes] == ["ARCH-5"]
    assert db.query(Item).filter(Item.id == archived_id).first() is None


# --- update_item (move the primary barcode) --------------------------

def test_update_primary_to_archived_code(db):
    live = _seed_item(db, barcode="LIVE-3")
    _seed_item(db, barcode="ARCH-6", archived=True)

    with pytest.raises(ArchivedBarcodeConflictError):
        items_service.update_item(db, live.id, barcode="ARCH-6")

    updated = items_service.update_item(
        db, live.id, barcode="ARCH-6", override_archived=True
    )
    assert updated.barcode == "ARCH-6"
