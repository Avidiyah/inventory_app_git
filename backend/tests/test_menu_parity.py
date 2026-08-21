"""Guards for the themed popup menus and the dark-surface color rules.

Layer: unit (no DB, no browser). There is no JavaScript test harness in
this repo, so front-end invariants are checked the way
`test_work_order_status_parity.py` checks the status vocabulary: read the
static source as text and assert on it. Parsing CSS and JS with regexes is
crude, but the alternative is trusting hand-edited files to stay in step,
which is exactly what silently regressed here -- `#items-table`'s row hover
kept a light `--gray-50` fill through the flip to a dark canvas, so hovering
a row painted near-white text (`--text-panel`) on a near-white background.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STATIC = Path(__file__).resolve().parents[1] / "static"
STYLES_CSS = STATIC / "styles.css"

# The panel color the app's text actually sits on: --panel-bg composited over
# --color-canvas. Contrast in docs/design-system.md is measured against this,
# not against the canvas.
COMPOSITED_PANEL = "#2A2B2D"

# Light neutrals from the pre-dark-canvas design. Any of these as a *fill*
# behind panel text reproduces the white-on-white bug.
LIGHT_FILLS = ("--gray-50", "--gray-100", "--gray-200", "--color-white")


def _css() -> str:
    return STYLES_CSS.read_text(encoding="utf-8")


def _root_token(name: str) -> str:
    """The hex value of a custom property declared in :root."""
    match = re.search(rf"{re.escape(name)}:\s*(#[0-9A-Fa-f]{{3,8}})", _css())
    assert match, f"{name} is not declared with a hex value in :root"
    return match.group(1)


def _rule_body(selector: str) -> str:
    """The declarations inside the first rule matching `selector`."""
    match = re.search(
        rf"{re.escape(selector)}\s*\{{(.*?)\}}", _css(), re.DOTALL
    )
    assert match, f"no CSS rule found for {selector!r}"
    return match.group(1)


def _relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(ch * 2 for ch in hex_color)
    channels = []
    for offset in (0, 2, 4):
        value = int(hex_color[offset : offset + 2], 16) / 255
        channels.append(
            value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
        )
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(foreground: str, background: str) -> float:
    light = _relative_luminance(foreground)
    dark = _relative_luminance(background)
    if light < dark:
        light, dark = dark, light
    return (light + 0.05) / (dark + 0.05)


def test_the_contrast_helper_agrees_with_the_design_system_table():
    """docs/design-system.md publishes measured ratios. If this helper does
    not reproduce them, every other contrast assertion here is meaningless."""
    assert round(_contrast(_root_token("--color-brand"), COMPOSITED_PANEL), 1) == 2.4
    assert round(_contrast(_root_token("--color-brand-light"), COMPOSITED_PANEL), 1) == 5.5


def test_the_items_row_hover_is_not_a_light_fill():
    """Find Item's results row. Row text is --text-panel (#EDEEF0); a light
    fill here is near-white text on a near-white background."""
    body = _rule_body("#items-table tbody tr:hover")
    for token in LIGHT_FILLS:
        assert token not in body, (
            f"#items-table row hover fills with {token}, which is near-white; "
            "row text is --text-panel and becomes unreadable"
        )
    assert "--panel-hover" in body


def test_no_light_neutral_is_used_as_a_background_anywhere():
    """docs/design-system.md: 'nothing in the app reads them as a background
    anymore'. This is the guard that makes that sentence true."""
    offenders = [
        line.strip()
        for line in _css().splitlines()
        if re.search(r"background(-color)?:\s*var\(--gray-(50|100|200)\)", line)
    ]
    assert offenders == [], f"light neutral used as a fill on a dark surface: {offenders}"


MENUS_JS = STATIC / "menus.js"


def test_the_shared_menu_module_exists_and_exports_its_api():
    """items.js, tools.js, workOrders.js and notes.js all import from here.
    A rename that misses one is a dead dropdown with no error anywhere."""
    source = MENUS_JS.read_text(encoding="utf-8")
    for export in (
        "export function actionMenuHtml",
        "export function initActionMenus",
        "export function closeMenu",
        "export function closeAllMenus",
    ):
        assert export in source, f"menus.js is missing: {export}"


def test_the_action_menu_is_a_menu_not_a_listbox():
    """A fire-and-close command menu. role=listbox + aria-selected would
    promise a persistent selection the Actions column never has."""
    source = MENUS_JS.read_text(encoding="utf-8")
    action_menu = re.search(
        r"export function actionMenuHtml\(.*?\n\}", source, re.DOTALL
    )
    assert action_menu, "actionMenuHtml was not found in menus.js"
    body = action_menu.group(0)
    assert 'role="menu"' in body
    assert 'role="menuitem"' in body
    assert 'aria-haspopup="menu"' in body
    assert "aria-selected" not in body


def test_the_menu_has_the_css_it_renders_against():
    """menus.js writes these class names; without a rule each one falls back
    to the global `button` style, which is a solid brand-red block."""
    css = _css()
    for selector in (
        ".menu {",
        ".menu-trigger {",
        ".menu-trigger:hover",
        ".menu-list {",
        ".menu-list[hidden]",
        ".menu-option {",
        ".menu-option-danger {",
        ".menu-chevron {",
    ):
        assert selector in css, f"menus.js renders markup with no rule for {selector!r}"


def test_the_menu_popover_is_readable_on_its_own_background():
    """The popover is --color-header, darker than a panel, so panel text
    tokens have to be re-checked against it rather than assumed."""
    header = _root_token("--color-header")
    assert _contrast(_root_token("--text-panel"), header) >= 4.5
    assert _contrast(_root_token("--color-brand-light"), header) >= 4.5


def test_the_hidden_menu_list_actually_hides():
    """.menu-list sets display:flex, and [hidden] is only display:none in the
    UA sheet -- the flex wins unless this rule exists to outrank it."""
    assert re.search(r"\.menu-list\[hidden\]\s*\{\s*display:\s*none", _css())


ITEMS_JS = STATIC / "views" / "items.js"
TOOLS_JS = STATIC / "views" / "tools.js"


def _rendered_menu_values(source: str) -> set:
    return set(re.findall(r'value:\s*"([a-z-]+)"', source))


def _handled_action_values(source: str) -> set:
    return set(re.findall(r'action === "([a-z-]+)"', source))


def test_find_item_no_longer_uses_a_native_select_for_row_actions():
    """The one control on this page whose popup the OS may draw itself."""
    source = ITEMS_JS.read_text(encoding="utf-8")
    assert "row-actions-select" not in source
    assert "<select" not in source
    assert "actionMenuHtml" in source


def test_find_items_menu_options_all_have_handlers():
    """actionsCell writes value strings that the pick callback reads back by
    string. A rename in one place and not the other is a dead menu item with
    no error anywhere -- same guard as the work-order walkthrough actions."""
    source = ITEMS_JS.read_text(encoding="utf-8")
    assert _rendered_menu_values(source) <= _handled_action_values(source)


def test_find_items_archive_option_is_marked_dangerous():
    """Archive is the one irreversible-looking action in the menu; it gets
    the separating rule and the ghost-red treatment."""
    source = ITEMS_JS.read_text(encoding="utf-8")
    archive = re.search(r'\{[^}]*value:\s*"delete"[^}]*\}', source)
    assert archive, 'no menu option with value "delete" found in items.js'
    assert "danger: true" in archive.group(0)


def test_the_dead_row_action_select_style_is_gone():
    assert ".row-actions-select" not in _css()
