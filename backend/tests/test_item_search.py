"""Focused integration coverage for the Find Item search contracts."""

from datetime import datetime, timezone
from decimal import Decimal
import uuid

import pytest

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


# --- normalization (pure, no database) -----------------------------------


@pytest.mark.parametrize(
    "raw, separated, squashed",
    [
        ('2"x4" Stud', "2x4 stud", "2x4stud"),
        ("Blinds (35...)", "blinds 35", "blinds35"),
        ("PL-C 26W Compact Fluorescent", "pl c 26w compact fluorescent",
         "plc26wcompactfluorescent"),
        ("Gel-Coat Products Tub & Shower Repair Kit",
         "gel coat products tub shower repair kit",
         "gelcoatproductstubshowerrepairkit"),
        # Quotes are deleted, not spaced -- that is what closes `2"x4"` up.
        ("6' Ladder", "6 ladder", "6ladder"),
        # Runs of punctuation collapse to a single separator, and the result
        # is trimmed at both ends.
        ("  ...Widget---  ", "widget", "widget"),
        # Nothing survivable at all.
        ('"""', "", ""),
    ],
)
def test_normalization_forms(raw, separated, squashed):
    assert items_service._separated(raw) == separated
    assert items_service._squashed(raw) == squashed


def test_search_tokens_distinguishes_absent_from_empty():
    # `None` means "no search requested" and must NOT be confused with a
    # query that normalized away to nothing -- the first loads the catalogue,
    # the second must return no rows.
    assert items_service._search_tokens(None) is None
    assert items_service._search_tokens("   ") == []
    assert items_service._search_tokens('"""') == []
    assert items_service._search_tokens("Blinds (35...)") == ["blinds", "35"]


# --- search behaviour (against the database) ------------------------------


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


@pytest.mark.parametrize(
    "stored_name, query",
    [
        # The four cases that drove this feature: punctuation in the stored
        # name must not decide whether a crew member can find it.
        ('2"x4" Stud {tok}', "2x4"),
        ('2"x4" Stud {tok}', '2"x4"'),
        ("Blinds (35...) {tok}", "Blinds 35"),
        ("Blinds (35...) {tok}", "blinds(35)"),
        # Omitting a hyphen is the whole promise; these fail without the
        # squashed form.
        ("PL-C 26W Compact Fluorescent {tok}", "PLC"),
        ("PL-C 26W Compact Fluorescent {tok}", "PL-C"),
        ("Gel-Coat Products Tub & Shower Kit {tok}", "gelcoat"),
        ("Gel-Coat Products Tub & Shower Kit {tok}", "gel coat"),
        # Word order and adjacency are deliberately not enforced.
        ("Copper Coupling Half Inch {tok}", "coupling copper"),
    ],
)
def test_punctuation_and_order_insensitive_matching(db, stored_name, query):
    tok = uuid.uuid4().hex
    item = _seed_item(
        db,
        barcode=f"PUNCT-{tok}",
        name=stored_name.format(tok=tok),
    )

    matches = items_service.list_items(db, search=f"{query} {tok}")

    assert [found.id for found in matches] == [item.id]


def test_every_token_must_match(db):
    token = uuid.uuid4().hex
    _seed_item(db, barcode=f"AND-{token}", name=f"Copper Coupling {token}")

    # "copper" hits, "blinds" does not -- AND semantics means no result.
    assert items_service.list_items(db, search=f"copper blinds {token}") == []


def test_barcode_matches_with_and_without_its_separators(db):
    token = uuid.uuid4().hex
    item = _seed_item(
        db,
        barcode=f"ZX-{token}-42",
        name=f"Separator Barcode {token}",
    )

    with_dashes = items_service.list_items(db, search=f"zx-{token}-42")
    without_dashes = items_service.list_items(db, search=f"zx{token}42")

    assert [found.id for found in with_dashes] == [item.id]
    assert [found.id for found in without_dashes] == [item.id]


def test_wildcards_are_normalized_away_and_blank_search_returns_nothing(db):
    # Supersedes the pre-normalization contract, which asserted that `%` and
    # `_` were escaped and matched *literally*. They are now stripped like any
    # other punctuation, so a wildcard cannot reach the LIKE pattern at all --
    # a stronger guarantee than escaping, but a different one: a query of
    # `50%_x` and one of `50 x` are now the same search.
    token = uuid.uuid4().hex
    literal = _seed_item(
        db,
        barcode=f"PERCENT-{token}",
        name=f"Discount 50%_\\{token}",
    )

    matches = items_service.list_items(db, search=f"50%_\\{token}")
    assert [item.id for item in matches] == [literal.id]

    # A bare wildcard must not behave as "match everything".
    assert items_service.list_items(db, search="%") == []
    assert items_service.list_items(db, search="   ") == []
    assert items_service.list_items(db, search='"""') == []


# --- relevance ordering ---------------------------------------------------


def test_results_are_ordered_exact_prefix_contiguous_then_scattered(db):
    token = uuid.uuid4().hex
    # Seeded worst-first, so passing cannot be an accident of insertion order.
    # They also share a creation instant, so only the rank can order them.
    scattered = _seed_item(
        db, barcode=f"D-{token}", name=f"Stud Bracket for 2x4 {token}"
    )
    contiguous = _seed_item(
        db, barcode=f"C-{token}", name=f"Oak 2x4 Stud Grade {token}"
    )
    prefix = _seed_item(
        db, barcode=f"B-{token}", name=f"2x4 Stud Premium {token}"
    )
    exact = _seed_item(db, barcode=f"A-{token}", name='2"x4" Stud')

    matches = items_service.list_items(db, search="2x4 stud")
    ranked = [item.id for item in matches]

    for item in (exact, prefix, contiguous, scattered):
        assert item.id in ranked, f"{item.name!r} should still be findable"
    assert ranked.index(exact.id) < ranked.index(prefix.id)
    assert ranked.index(prefix.id) < ranked.index(contiguous.id)
    assert ranked.index(contiguous.id) < ranked.index(scattered.id)


def test_exact_barcode_match_outranks_a_name_hit(db):
    token = uuid.uuid4().hex
    code = f"9{token[:11]}"
    by_barcode = _seed_item(db, barcode=code, name=f"Anonymous Part {token}")
    by_name = _seed_item(db, barcode=f"NM-{token}", name=f"Widget {code} {token}")

    matches = items_service.list_items(db, search=code)
    ranked = [item.id for item in matches]

    assert ranked.index(by_barcode.id) < ranked.index(by_name.id)


def test_unfiltered_list_keeps_plain_newest_first_ordering(db):
    # There is no query to be relevant to, so ranking must not disturb the
    # existing full-list contract that other views depend on.
    rows = items_service.list_items(db)
    created = [item.created_at for item in rows]
    assert created == sorted(created, reverse=True)


def test_search_excludes_archived_items_while_unfiltered_list_still_works(db):
    # Previously also covered `list_item_search_index`; that route, schema and
    # service function were deleted in X3 (zero callers anywhere), so only the
    # two surviving list paths are asserted here.
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

    assert live.id in unfiltered_ids
    assert archived.id not in unfiltered_ids
    assert search_ids == {live.id}
