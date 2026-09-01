"""The Low Stock page's plumbing.

The SPA has no JS test harness, so these pin the three hand-maintained
joins that fail silently: a fragment missing from `SHELL_PARTS` (the page
markup simply never reaches the browser), a page absent from `PAGE_ACCESS`
(its nav button is hidden for every role), and a nav button whose
`data-page` does not match a `.page` id (clicking it shows nothing).
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import SHELL_PARTS, STATIC_DIR

NAV_JS = Path(__file__).resolve().parents[1] / "static" / "views" / "nav.js"
SHELL_HEAD = Path(__file__).resolve().parents[1] / "static" / "shell-head.html"


def test_every_shell_fragment_exists():
    missing = [part for part in SHELL_PARTS if not (STATIC_DIR / part).is_file()]
    assert missing == []


def test_the_low_stock_fragment_is_assembled_into_the_shell():
    assembled = b"".join((STATIC_DIR / part).read_bytes() for part in SHELL_PARTS)
    assert b'id="low-stock-page"' in assembled


def test_the_recency_tabs_are_assembled_into_the_shell():
    """Three mutually exclusive buckets. A missing button is invisible in
    the browser -- the page just renders one bucket and hides the rest of
    the queue with no error."""
    assembled = b"".join((STATIC_DIR / part).read_bytes() for part in SHELL_PARTS)
    assert b'id="low-stock-tabs"' in assembled
    for bucket in (b"day", b"week", b"stale"):
        assert b'data-bucket="%s"' % bucket in assembled


def test_low_stock_is_reachable_by_techfm_oa_and_above():
    source = NAV_JS.read_text(encoding="utf-8")
    match = re.search(r'"low-stock":\s*\[(.*?)\]', source)
    assert match, "low-stock missing from PAGE_ACCESS"
    allowed = {role.strip().strip('"') for role in match.group(1).split(",") if role.strip()}
    assert allowed == {"owner", "admin", "techfm_oa"}


def test_the_nav_button_exists_and_targets_the_page():
    assert 'data-page="low-stock"' in SHELL_HEAD.read_text(encoding="utf-8")


def test_showpage_loads_the_low_stock_page():
    source = NAV_JS.read_text(encoding="utf-8")
    assert 'pageName === "low-stock"' in source
    assert "loadLowStock()" in source
