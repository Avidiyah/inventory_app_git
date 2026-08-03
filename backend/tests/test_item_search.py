"""Focused integration coverage for the Find Item search contracts."""

from datetime import datetime, timezone
from decimal import Decimal
import uuid

from app.models import Item
from app.services import items as items_service


def _seed_item(db, *, barcode, name, archived=False):
    item = Item(
        barcode=barcode,
        name=name,
        quantity=Decimal("1"),
        location="Search test shelf",
    )
    if archived:
        item.archived_at = datetime.now(timezone.utc)
    db.add(item)
    db.flush()
    return item


def test_search_pattern_escapes_sql_wildcards():
    assert items_service._search_pattern(None) is None
    assert items_service._search_pattern("   ") == ""
    assert items_service._search_pattern(r"  50%_off\tag  ") == r"%50\%\_off\\tag%"


def test_list_items_searches_name_and_primary_barcode_case_insensitively(db):
    token = uuid.uuid4().hex
    by_name = _seed_item(
        db,
        barcode=f"SEARCH-NAME-{token}",
        name=f"Copper Coupling {token}",
    )
    by_barcode = _seed_item(
        db,
        barcode=f"ZX-{token}-42",
        name=f"Unrelated {uuid.uuid4().hex}",
    )

    name_matches = items_service.list_items(db, search=f"cOpPeR cOuPlInG {token}")
    barcode_matches = items_service.list_items(db, search=f"zx-{token}-42")

    assert [item.id for item in name_matches] == [by_name.id]
    assert [item.id for item in barcode_matches] == [by_barcode.id]


def test_list_items_treats_wildcards_literally_and_rejects_blank_search(db):
    token = uuid.uuid4().hex
    literal = _seed_item(
        db,
        barcode=f"PERCENT-{token}",
        name=f"Discount 50%_\\{token}",
    )
    _seed_item(
        db,
        barcode=f"CONTROL-{token}",
        name=f"Discount 50X{token}",
    )

    matches = items_service.list_items(db, search=f"50%_\\{token}")

    assert [item.id for item in matches] == [literal.id]
    assert items_service.list_items(db, search="   ") == []


def test_search_and_index_exclude_archived_items_while_unfiltered_list_still_works(db):
    token = uuid.uuid4().hex
    live = _seed_item(
        db,
        barcode=f"LIVE-{token}",
        name=f"A Live Search Item {token}",
    )
    archived = _seed_item(
        db,
        barcode=f"ARCHIVED-{token}",
        name=f"Z Archived Search Item {token}",
        archived=True,
    )

    unfiltered_ids = {item.id for item in items_service.list_items(db)}
    search_ids = {item.id for item in items_service.list_items(db, search=token)}
    index_rows = items_service.list_item_search_index(db)
    index_pairs = {(row.name, row.barcode) for row in index_rows}

    assert live.id in unfiltered_ids
    assert archived.id not in unfiltered_ids
    assert search_ids == {live.id}
    assert (live.name, live.barcode) in index_pairs
    assert (archived.name, archived.barcode) not in index_pairs
    assert all(row._fields == ("name", "barcode") for row in index_rows)
