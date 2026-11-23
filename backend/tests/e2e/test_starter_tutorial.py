"""The Field starter tour on a 375 px phone, real layout, real mouse.

Proves what jsdom cannot: the lit menu control is really tappable, a real click
anywhere else (Log Out included) is swallowed by the cover, the tour sends only
GETs (plus its own progress PUTs), and the box never makes the page scroll
sideways. Team Lead and above share the compact bar the admin sees; a
technician has the flat bar.
"""

import pytest

from .test_mobile_overflow import _OFFENDERS_JS, _assert_fits, _open_at

pytestmark = pytest.mark.e2e

_OWN_BOOKKEEPING = "/tutorials/progress/"


def _tap_lit(page):
    """A real mouse click in the middle of the lit rectangle; waits for the box to move on."""
    before = page.locator(".tut-text").inner_text()
    spot = page.locator(".tut-spot").bounding_box()
    assert spot and spot["width"] > 0, "nothing is lit"
    page.mouse.click(spot["x"] + spot["width"] / 2, spot["y"] + spot["height"] / 2)
    page.wait_for_function(
        "(t) => !document.querySelector('.tut-overlay') || document.querySelector('.tut-text').textContent !== t",
        arg=before, timeout=8000)


def _play_field_starter(page):
    page.evaluate("document.querySelector('#hub-tab-tutorials').click()")
    page.wait_for_selector("#hub-tabpanel-tutorials:not([hidden])", timeout=15000)
    page.evaluate("document.querySelector('[data-tut-sub=\"starter\"]').click()")
    page.wait_for_selector('.hub-tut-entry[data-tut-key="starter.field"]', timeout=15000)

    requests = []
    page.on("request", lambda r: requests.append((r.method, r.url)))
    page.evaluate("document.querySelector('.hub-tut-entry[data-tut-key=\"starter.field\"]').click()")
    page.wait_for_selector(".tut-overlay .tut-box", timeout=8000)

    # A real click on Log Out lands on the cover: nobody is signed out.
    logout = page.locator("#logout-btn").bounding_box()
    point = (logout["x"] + logout["width"] / 2, logout["y"] + logout["height"] / 2) if logout else (5, 5)
    page.mouse.click(*point)
    page.wait_for_timeout(300)
    assert page.locator("#login-screen").is_hidden()
    assert page.locator(".tut-overlay").count() == 1

    # Tap the lit toggle (compact bar only), then Scan / Stock.
    for _ in range(2):
        _tap_lit(page)
        if page.locator("#transaction-page.active").count():
            break
    page.wait_for_selector("#transaction-page.active", timeout=8000)
    _assert_fits(page, "Field starter, Scan / Stock overview @ 375px")
    assert not page.evaluate(_OFFENDERS_JS), "tour box overflows"

    others = [r for r in requests if r[0] != "GET" and _OWN_BOOKKEEPING not in r[1]]
    assert others == [], f"the tour sent non-GET requests: {others}"
    page.keyboard.press("Escape")
    page.wait_for_selector(".tut-overlay", state="detached", timeout=5000)


def test_field_starter_on_the_compact_bar(admin_page):
    _open_at(admin_page, 375)
    _play_field_starter(admin_page)


def test_field_starter_on_the_flat_bar(login_as, seeded, console_errors):
    page = login_as(seeded.technician_username)
    _open_at(page, 375)
    _play_field_starter(page)
