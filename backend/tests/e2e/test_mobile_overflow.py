"""Phone view never scrolls sideways: not the page, and not a wrapper inside it.

A page-width check alone misses `overflow-x: auto` wrappers, which hide the
overflow inside a box, so the second check names those too.
"""

import pytest

from .test_smoke import PAGE_LANDMARKS, PAGE_NAMES

pytestmark = pytest.mark.e2e

WIDTHS = [375, 320]
HUB_TABS = ["home", "dashboard", "timesheets", "leaderboards", "work-orders", "graphs", "report", "tutorials"]

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


_SCROLL_Y = "() => Math.round(window.scrollY)"


@pytest.mark.parametrize("width", WIDTHS + [1280])
def test_graphs_popup_freezes_the_page_and_fits(owner_page, width):
    """Opening and closing a Graphs chart must leave the page exactly where
    it was -- no jump, no drift under a swipe, no sideways shift as the
    scrollbar goes -- and the pop-up itself must never scroll sideways."""
    _open_at(owner_page, width)
    # The tab stays hidden until /hub has answered with the viewer's role; a
    # click before that is ignored.
    owner_page.wait_for_function(
        "() => document.querySelector('[data-hub-tab=\"graphs\"]')?.hidden === false", timeout=15000
    )
    _click(owner_page, '[data-hub-tab="graphs"]')
    owner_page.wait_for_selector("#hub-tabpanel-graphs [data-graph-trend]", timeout=15000)
    _assert_fits(owner_page, f"graphs tiles @ {width}px")
    # Start part-way down, so "did not move" cannot pass by sitting at 0.
    owner_page.evaluate(
        "document.querySelector('#hub-tabpanel-graphs [data-graph-trend]').scrollIntoView({block: 'center'})"
    )
    start = owner_page.evaluate(_SCROLL_Y)
    client_width = owner_page.evaluate("document.documentElement.clientWidth")

    openers = ['[data-graph-trend="days"]', '[data-graph-trend="ontime"]']
    if owner_page.locator("#hub-tabpanel-graphs [data-graph-pie]:not([disabled])").count():
        openers.append("[data-graph-pie]:not([disabled])")
    for opener in openers:
        _click(owner_page, f"#hub-tabpanel-graphs {opener}")
        owner_page.wait_for_selector(".hub-graph-sheet:not([hidden])", timeout=5000)
        cover = owner_page.evaluate(
            """() => { const r = document.querySelector('.hub-graph-sheet').getBoundingClientRect();
                return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height),
                        window.innerWidth, window.innerHeight]; }"""
        )
        # A frosted ancestor would trap the fixed overlay inside the tab panel.
        assert cover[:2] == [0, 0] and cover[3] == cover[5], f"{opener} @ {width}px: overlay {cover}"
        owner_page.mouse.move(width / 2, 300)
        owner_page.mouse.wheel(0, 900)
        owner_page.mouse.move(2, 2)  # the backdrop edge on a desktop
        owner_page.mouse.wheel(0, 900)
        owner_page.evaluate("document.querySelectorAll('.hub-graph-sheet details').forEach(d => d.open = true)")
        _assert_fits(owner_page, f"graphs pop-up {opener} @ {width}px")
        where = f"{opener} @ {width}px"
        assert owner_page.evaluate(_SCROLL_Y) == start, f"{where}: page moved while the pop-up was open"
        assert owner_page.evaluate("document.documentElement.clientWidth") == client_width, (
            f"{where}: page shifted sideways when the pop-up opened"
        )
        close = owner_page.evaluate(
            """() => { const r = document.querySelector('[data-graph-close]').getBoundingClientRect();
                return r.top >= 0 && r.bottom <= window.innerHeight; }"""
        )
        assert close, f"{where}: the red X scrolled out of view"
        _click(owner_page, ".hub-graph-sheet [data-graph-close]")
        owner_page.wait_for_selector(".hub-graph-sheet", state="hidden", timeout=5000)
        assert owner_page.evaluate(_SCROLL_Y) == start, f"{where}: page moved when the pop-up closed"
        assert owner_page.evaluate("document.documentElement.clientWidth") == client_width, (
            f"{where}: page shifted sideways when the pop-up closed"
        )
