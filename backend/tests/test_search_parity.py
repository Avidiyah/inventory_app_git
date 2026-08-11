"""Pin the two search normalizers together.

The punctuation-insensitive search rule is implemented twice on purpose:
in Postgres/Python (`app/services/items.py`, for Find Item) and in the
browser (`static/format.js`, for the six views that filter a
client-side list and never call the backend). Two implementations of one
rule drift silently -- a crew member would get different results for the
same query depending on which screen they were standing on.

This test runs the REAL `format.js` under node and asserts it agrees with
the Python functions character-for-character. It is deliberately a
normalization test, not a matching test: `matchesSearch` and
`list_items` both build on these two functions, so pinning the functions
pins the behaviour.

Skipped (not failed) where node is unavailable, so the suite still runs
on a machine without it; CI has node and will enforce it.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import items as items_service

FORMAT_JS = Path(__file__).resolve().parents[1] / "static" / "format.js"

# One corpus, both directions. Mixes the real catalogue names that drove
# the feature with the edge cases most likely to expose a regex or
# trim/collapse difference between the two engines.
CORPUS = [
    '2"x4" Stud',
    "Blinds (35...)",
    "PL-C 26W Compact Fluorescent",
    "Gel-Coat Products Tub & Shower Repair Kit",
    "Philips Indoor Flood and Landscape 35W Bulb",
    "6' Ladder",
    "046677419325",
    "ZX-abc-42",
    "  leading and trailing  ",
    "multiple   internal   spaces",
    "...only punctuation...",
    '"""',
    "",
    "   ",
    "MiXeD CaSe",
    "under_score and %percent% and back\\slash",
    "tab\tand\nnewline",
    "50%_\\x",
    "a",
    "-",
]


# (name, barcode, query) triples for the ranking parity check -- one per
# tier, plus the ties that decide ordering in practice.
RANK_CASES = [
    ('2"x4" Stud', "ZX-1", "2x4 stud"),          # exact, via squashed form
    ("2x4 stud", "ZX-1", "2x4 stud"),            # exact, via separated form
    ("2x4 Stud Premium", "ZX-1", "2x4 stud"),    # prefix
    ("Oak 2x4 Stud Grade A", "ZX-1", "2x4 stud"),  # contiguous, not prefix
    ("Stud Bracket for 2x4", "ZX-1", "2x4 stud"),  # scattered tokens
    ("Unrelated", "046677419325", "046677419325"),  # exact on barcode
    ("Unrelated", "ZX-abc-42", "zxabc"),         # prefix on squashed barcode
    ("PL-C 26W Compact Fluorescent", "B1", "PLC"),
    ("Gel-Coat Products Tub & Shower Kit", "B2", "gelcoat"),
    ("Anything", "B3", ""),                      # empty query -> no signal
]


def _node_results():
    script = f"""
import {{ separatedForSearch, squashedForSearch, searchTokens, searchRank }}
  from {json.dumps(FORMAT_JS.as_uri())};
const corpus = {json.dumps(CORPUS)};
const rankCases = {json.dumps(RANK_CASES)};
process.stdout.write(JSON.stringify({{
  norm: corpus.map(s => [
    separatedForSearch(s), squashedForSearch(s), searchTokens(s),
  ]),
  ranks: rankCases.map(([name, barcode, query]) =>
    searchRank([name, barcode], query)),
}}));
"""
    proc = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        pytest.fail(f"node failed running format.js:\n{proc.stderr}")
    return json.loads(proc.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_and_python_normalizers_agree():
    results = _node_results()["norm"]
    assert len(results) == len(CORPUS)

    mismatches = []
    for raw, (js_sep, js_squash, js_tokens) in zip(CORPUS, results):
        py_sep = items_service._separated(raw)
        py_squash = items_service._squashed(raw)
        py_tokens = items_service._search_tokens(raw)
        if (js_sep, js_squash, js_tokens) != (py_sep, py_squash, py_tokens):
            mismatches.append(
                f"  {raw!r}\n"
                f"    separated  js={js_sep!r}    py={py_sep!r}\n"
                f"    squashed   js={js_squash!r} py={py_squash!r}\n"
                f"    tokens     js={js_tokens!r} py={py_tokens!r}"
            )

    assert not mismatches, (
        "format.js and items.py disagree on:\n" + "\n".join(mismatches)
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_and_python_ranking_agree():
    js_ranks = _node_results()["ranks"]
    assert len(js_ranks) == len(RANK_CASES)

    expected = [
        items_service._search_rank([name, barcode], query)
        for name, barcode, query in RANK_CASES
    ]
    assert js_ranks == expected

    # The corpus must actually exercise every tier, or this passes vacuously.
    assert set(expected) == {0, 1, 2, 3}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_postgres_agrees_with_python_normalizer(db):
    """The third implementation: the SQL expressions `list_items` filters on.

    Python normalizes the *query* while Postgres normalizes the *stored*
    text, so a divergence here means a row silently stops being findable
    by its own name.
    """
    from sqlalchemy import literal, select

    for raw in CORPUS:
        sql_sep, sql_squash = db.execute(
            select(
                items_service._sql_separated(literal(raw)),
                items_service._sql_squashed(literal(raw)),
            )
        ).one()
        assert sql_sep == items_service._separated(raw), f"separated: {raw!r}"
        assert sql_squash == items_service._squashed(raw), f"squashed: {raw!r}"
