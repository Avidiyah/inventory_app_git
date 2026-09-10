"""Two journeys through the work-order surface, end to end.

Deliberately thin. Exhaustive behaviour coverage is P2's jsdom suite; what
these two add is the real network, the real service worker, the real
`history.pushState` deep link, and a real status write reaching Postgres.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

pytestmark = pytest.mark.e2e


def test_a_deep_linked_card_renders_on_its_own(owner_page, seeded, base_url):
    owner_page.goto(f"{base_url}/workorder_card/{seeded.work_order_number}")
    owner_page.wait_for_selector("#work-orders-page", state="visible", timeout=15000)
    card = owner_page.locator(".wo-card", has_text=seeded.work_order_number)
    card.wait_for(state="visible", timeout=15000)
    assert card.locator(".wo-status-created").count() == 1


def test_beginning_work_moves_the_badge_to_in_progress(owner_page, seeded, base_url):
    owner_page.goto(f"{base_url}/workorder_card/{seeded.work_order_number}")
    card = owner_page.locator(".wo-card", has_text=seeded.work_order_number)
    card.wait_for(state="visible", timeout=15000)

    # The only status control on a `created` card for a Supervisor+ viewer.
    # The transition to in_progress is a side effect of starting the clock --
    # see the comment above `statusActions` in views/workOrders.js.
    card.locator('[data-action="start-tracking-wo"]').click()

    card.locator(".wo-status-in_progress").wait_for(state="visible", timeout=15000)
    assert card.locator(".wo-status-created").count() == 0
