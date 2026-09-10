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
