"""`static/roles.js` is a hand-maintained twin of `app/domain/roles.py`.

Layer: unit (no DB, no browser). Nothing else checks that the two agree, and
they disagree silently: the frontend would simply gate the wrong things while
every backend test still passed. Parsing the JS is crude but it is the only
check that exists, and the alternative -- trusting two hand-edited rank tables
to stay in step -- is what this test is for.
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.domain import roles

ROLES_JS = Path(__file__).resolve().parents[1] / "static" / "roles.js"


def _js_object_literal(source: str, name: str) -> dict:
    """Extract `export const <name> = { ... };` as a dict.

    The literals in roles.js are plain JSON once the unquoted keys are
    quoted and the trailing comma is dropped, so this stays a few lines
    rather than pulling in a JS parser.
    """
    match = re.search(rf"export const {name} = \{{(.*?)\}};", source, re.DOTALL)
    assert match, f"{name} object literal not found in roles.js"
    body = re.sub(r"(\w+):", r'"\1":', match.group(1))
    body = re.sub(r",(\s*)$", r"\1", body.strip())
    return json.loads("{" + body + "}")


def _js_array_literal(source: str, name: str) -> list:
    match = re.search(rf"export const {name} = \[(.*?)\];", source, re.DOTALL)
    assert match, f"{name} array literal not found in roles.js"
    return json.loads("[" + match.group(1).strip().rstrip(",") + "]")


def test_rank_table_matches_the_python_domain():
    source = ROLES_JS.read_text(encoding="utf-8")
    assert _js_object_literal(source, "ROLE_RANK") == roles.ROLE_RANK


def test_role_list_matches_the_python_domain():
    source = ROLES_JS.read_text(encoding="utf-8")
    assert _js_array_literal(source, "ALL_ROLES") == list(roles.ALL_ROLES)


def test_labels_match_the_python_domain():
    source = ROLES_JS.read_text(encoding="utf-8")
    assert _js_object_literal(source, "ROLE_LABELS") == roles.ROLE_LABELS
