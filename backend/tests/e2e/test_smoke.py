"""Every page in the shell, in a real browser, with a clean console."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

pytestmark = pytest.mark.e2e


def test_the_shell_is_served(owner_page, seeded):
    """The whole fixture chain in one assertion: server up, database seeded,
    login succeeded, console clean."""
    assert owner_page.locator("#login-screen").is_hidden()
    assert owner_page.locator("#user-hub-page").is_visible()


from app.main import SHELL_PARTS

# One landmark per page: an element that exists only once the page's module
# has rendered, so a blank page fails rather than passing on its container.
# `integrations-import-section` ships with a `hidden` attribute and is
# unhidden for Admin+ only, so asserting it visible also proves role gating ran.
PAGE_LANDMARKS = {
    "user-hub": "#hub-tabpanel-dashboard",
    "create-item": "#create-item-section",
    # NOT #items-table: it ships `hidden` and is unhidden only once a search
    # returns rows. #items-search is the always-rendered search control.
    "saved-items": "#items-search",
    "create-user": "#create-user-section",
    "saved-users": "#users-table",
    "transaction": "#txn-scango-section",
    "mass-stage": "#mass-stage-list-section",
    "work-orders": "#work-orders-list-section",
    "user-requests": "#user-requests-section",
    "low-stock": "#low-stock-section",
    "admin-review": "#admin-review-queue-section",
    "tools": "#tool-custody-section",
    "history": "#history-section",
    "integrations": "#integrations-import-section",
}

PAGE_NAMES = [
    part.removeprefix("pages/").removesuffix(".html")
    for part in SHELL_PARTS
    if part.startswith("pages/")
]


def test_every_shell_page_has_a_landmark():
    """A new fragment added to SHELL_PARTS joins this suite automatically.
    Without this check it would join it silently and never be visited."""
    assert sorted(PAGE_NAMES) == sorted(PAGE_LANDMARKS)


def _navigate_to(page, page_name):
    """Click a nav entry, opening its group first when it has one.

    For Supervisor+ the nav groups in shell-head.html are popovers: the entry
    exists in the DOM but is not visible until `.nav-group-toggle` is clicked.
    Only the user-hub indicator sits outside a group.
    """
    button = page.locator(f'[data-page="{page_name}"]')
    if not button.is_visible():
        group = page.locator(f'.nav-group:has([data-page="{page_name}"])')
        group.locator(".nav-group-toggle").click()
        button.wait_for(state="visible", timeout=15000)
    button.click()


@pytest.mark.parametrize("page_name", PAGE_NAMES)
def test_page_renders_with_a_clean_console(owner_page, page_name):
    _navigate_to(owner_page, page_name)
    owner_page.wait_for_selector(f"#{page_name}-page", state="visible", timeout=15000)
    owner_page.wait_for_selector(PAGE_LANDMARKS[page_name], state="visible", timeout=15000)
