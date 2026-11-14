"""Phone view never scrolls sideways: not the page, and not a wrapper inside it.

A page-width check alone misses `overflow-x: auto` wrappers, which hide the
overflow inside a box, so the second check names those too.
"""

import pytest

from .test_smoke import PAGE_LANDMARKS, PAGE_NAMES

pytestmark = pytest.mark.e2e

WIDTHS = [375, 320]
HUB_TABS = ["home", "dashboard", "timesheets", "leaderboards", "work-orders", "graphs", "report"]

# Returns [] when nothing overflows, else one line per offender.
_OFFENDERS_JS = """() => {
    const out = [];
    const root = document.documentElement;
    if (root.scrollWidth > root.clientWidth) {
        out.push(`PAGE scrollWidth ${root.scrollWidth} > ${root.clientWidth}`);
    }
    const name = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '')
        + (el.className && typeof el.className === 'string'
            ? '.' + el.className.trim().split(/\\s+/).join('.') : '');
    for (const el of document.querySelectorAll('body *')) {
        if (el.getClientRects().length && el.getBoundingClientRect().right > root.clientWidth + 1
            && !el.closest('[class*=scroller]') && !el.parentElement.closest('svg')) {
            out.push(`STICKS-OUT ${name(el)} right ${Math.round(el.getBoundingClientRect().right)}`);
        }
        if (!el.offsetParent && getComputedStyle(el).position !== 'fixed') continue;
        if (el.scrollWidth > root.clientWidth + 1 && el.clientWidth <= root.clientWidth
            && getComputedStyle(el).overflowX === 'visible' && !el.closest('svg')) {
            out.push(`WIDE-CONTENT ${name(el)} scrollWidth ${el.scrollWidth}`);
        }
        const ox = getComputedStyle(el).overflowX;
        if ((ox === 'auto' || ox === 'scroll') && el.scrollWidth > el.clientWidth + 1) {
            out.push(`SCROLLER ${name(el)} ${el.scrollWidth} > ${el.clientWidth}`);
        }
    }
    return out;
}"""


def _open_at(page, width):
    """Reload at phone width: views choose their layout at render time, so a
    resize after login would still show the desktop render."""
    page.set_viewport_size({"width": width, "height": 667})
    page.reload()
    page.wait_for_selector("#login-screen", state="hidden", timeout=15000)
    page.wait_for_selector("#user-hub-page", state="visible", timeout=15000)


def _click(page, selector):
    # JS click: on a phone the nav and hub tabs sit behind pickers/hamburgers.
    page.evaluate("(s) => document.querySelector(s)?.click()", selector)


def _assert_fits(page, where):
    page.wait_for_timeout(400)  # let async renders settle
    offenders = page.evaluate(_OFFENDERS_JS)
    assert not offenders, f"{where}:\n" + "\n".join(offenders)


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("page_name", PAGE_NAMES)
def test_page_does_not_scroll_sideways(owner_page, page_name, width):
    _open_at(owner_page, width)
    _click(owner_page, f'[data-page="{page_name}"]')
    owner_page.wait_for_selector(PAGE_LANDMARKS[page_name], state="visible", timeout=15000)
    # Open every collapsed panel so folded content is measured too.
    owner_page.evaluate(f"document.querySelectorAll('#{page_name}-page details').forEach(d => d.open = true)")
    _assert_fits(owner_page, f"{page_name} @ {width}px")


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("tab", HUB_TABS)
def test_hub_tab_does_not_scroll_sideways(owner_page, tab, width):
    _open_at(owner_page, width)
    _click(owner_page, f'[data-hub-tab="{tab}"]')
    owner_page.wait_for_timeout(600)
    if owner_page.locator(f"#hub-tabpanel-{tab}").is_hidden():
        pytest.skip(f"hub tab {tab} not available to this role")
    owner_page.evaluate("document.querySelectorAll('#user-hub-page details').forEach(d => d.open = true)")
    _assert_fits(owner_page, f"hub/{tab} @ {width}px")
