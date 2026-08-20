"""The work-order status vocabulary is spelled out in four hand-edited places.

Layer: unit (no DB, no browser). `domain/work_orders.py` owns the truth;
`views/workOrders.js` labels it, `pages/work-orders.html` filters on it, and
`styles.css` colors it. Nothing else checks that the four agree, and they
disagree *silently* -- a missing entry renders the raw `ready_to_complete`
slug in a badge, or drops a status off the filter, while every backend test
still passes.

Written in the same spirit as `test_role_mirror_parity.py`: parsing the JS and
CSS with regexes is crude, but the alternative is trusting four hand-edited
lists to stay in step, which is what this test is for.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.domain import work_orders as wo

STATIC = Path(__file__).resolve().parents[1] / "static"
WORK_ORDERS_JS = STATIC / "views" / "workOrders.js"
WORK_ORDERS_HTML = STATIC / "pages" / "work-orders.html"
STYLES_CSS = STATIC / "styles.css"


def _status_label_keys() -> set:
    """The keys of `statusLabel`'s lookup object."""
    source = WORK_ORDERS_JS.read_text(encoding="utf-8")
    match = re.search(
        r"function statusLabel\(status\) \{\s*return \{(.*?)\}\[status\]",
        source,
        re.DOTALL,
    )
    assert match, "statusLabel's lookup object was not found in workOrders.js"
    return set(re.findall(r"(\w+):", match.group(1)))


def test_every_status_has_a_front_end_label():
    """Without one, the badge shows the raw slug -- `ready_to_complete`
    rather than "Ready to Complete"."""
    assert _status_label_keys() == set(wo.ALL_STATUSES)


def test_every_status_is_offered_by_the_page_filter():
    """The payoff for making Ready to Complete a real status is that a
    supervisor can filter to their review queue."""
    html = WORK_ORDERS_HTML.read_text(encoding="utf-8")
    block = re.search(
        r'<select id="work-orders-status-filter">(.*?)</select>', html, re.DOTALL
    )
    assert block, "the status filter select was not found in work-orders.html"
    offered = set(re.findall(r'<option value="(\w+)"', block.group(1)))
    assert offered == set(wo.ALL_STATUSES)


def test_the_filter_lists_statuses_in_lifecycle_order():
    """`ALL_STATUSES` is ordered deliberately, and the dropdown is one of the
    two places that order is visible to a person."""
    html = WORK_ORDERS_HTML.read_text(encoding="utf-8")
    block = re.search(
        r'<select id="work-orders-status-filter">(.*?)</select>', html, re.DOTALL
    )
    offered = [
        value
        for value in re.findall(r'<option value="(\w*)"', block.group(1))
        if value
    ]
    assert offered == list(wo.ALL_STATUSES)


def test_every_status_has_a_badge_and_a_card_accent():
    """Status reads as color on the list. A status with no rule renders as an
    unstyled card, which looks like a broken row rather than a new state."""
    css = STYLES_CSS.read_text(encoding="utf-8")
    for status in wo.ALL_STATUSES:
        assert f".wo-status-{status} {{" in css, f"no badge color for {status}"
        assert (
            f".wo-card-status-{status} {{" in css
        ), f"no card accent for {status}"
        assert (
            f".wo-card-status-{status}:hover" in css
        ), f"no hover color for {status}, so .wo-card:hover will paint over it"


def test_the_walkthrough_action_names_match_their_handlers():
    """`renderBody` writes `data-action` attributes that the delegated click
    handler reads back by string. A rename in one place and not the other is
    a dead button with no error anywhere."""
    source = WORK_ORDERS_JS.read_text(encoding="utf-8")
    rendered = set(re.findall(r'data-action="([a-z-]+)"', source))
    handled = set(re.findall(r'action === "([a-z-]+)"', source))
    assert rendered == handled


def test_the_tracking_actions_replaced_the_old_status_buttons():
    """Start Tracking is the field's primary action now, and "Set
    In-Progress" / the technician's "Mark Completed" are gone as separate
    buttons -- their transitions are side effects of starting and finishing
    work."""
    source = WORK_ORDERS_JS.read_text(encoding="utf-8")
    rendered = set(re.findall(r'data-action="([a-z-]+)"', source))
    assert {
        "start-tracking-wo",
        "stop-tracking-wo",
        "notify-supervisor-wo",
        "send-back-wo",
    } <= rendered
    assert "start-wo" not in rendered
    assert "complete-assigned-wo" not in rendered
