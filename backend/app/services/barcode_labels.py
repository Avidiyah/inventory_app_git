"""Printable barcode labels: 2.5in x 3in cells cut from letter paper,
barcode over name, optionally narrowed to one item location.

Rendered as HTML; the user prints or saves as PDF from the browser. The
Code 39 barcode is drawn as inline SVG stretched to the cell width, so a
long code gets thinner bars rather than a wider label, and the printing
machine needs no barcode font.
"""

import re
from html import escape

from sqlalchemy.orm import Session

from app.services import items as items_service

# Code 39: each character is 9 elements alternating bar/space, starting
# with a bar; "1" marks a wide element. `*` is the start/stop character.
_CODE39 = {
    "0": "000110100", "1": "100100001", "2": "001100001", "3": "101100000",
    "4": "000110001", "5": "100110000", "6": "001110000", "7": "000100101",
    "8": "100100100", "9": "001100100", "A": "100001001", "B": "001001001",
    "C": "101001000", "D": "000011001", "E": "100011000", "F": "001011000",
    "G": "000001101", "H": "100001100", "I": "001001100", "J": "000011100",
    "K": "100000011", "L": "001000011", "M": "101000010", "N": "000010011",
    "O": "100010010", "P": "001010010", "Q": "000000111", "R": "100000110",
    "S": "001000110", "T": "000010110", "U": "110000001", "V": "011000001",
    "W": "111000000", "X": "010010001", "Y": "110010000", "Z": "011010000",
    "-": "010000101", ".": "110000100", " ": "011000100", "$": "010101000",
    "/": "010100010", "+": "010001010", "%": "000101010", "*": "010010100",
}
_WIDE = 3  # modules per wide element; narrow is 1
_QUIET = 10  # blank modules each side, the Code 39 minimum

# ponytail: Code 39 is ~16 modules per character, so past ~20 characters
# the bars get thin enough (< 6 mil at 2.2in) that a phone camera may
# struggle. Switch long codes to Code 128 if they stop scanning.


def _code39_modules(text: str) -> str | None:
    """`*text*` as bar ("1") / space ("0") modules with a narrow gap
    between characters, or None if Code 39 cannot encode `text`."""
    if not text or any(c not in _CODE39 or c == "*" for c in text):
        return None
    return "0".join(
        "".join(("1" if i % 2 == 0 else "0") * (_WIDE if w == "1" else 1)
                for i, w in enumerate(_CODE39[c]))
        for c in f"*{text}*"
    )


def _bars_html(code: str) -> str:
    modules = _code39_modules(code)
    if modules is None:
        return '<div class="no-bars">No Code 39 for this barcode</div>'
    padded = "0" * _QUIET + modules + "0" * _QUIET
    path = "".join(f"M{m.start()} 0h{len(m[0])}v1h-{len(m[0])}z"
                   for m in re.finditer("1+", padded))
    return (f'<svg class="bars" viewBox="0 0 {len(padded)} 1" '
            'preserveAspectRatio="none" shape-rendering="crispEdges" '
            f'aria-hidden="true"><path d="{path}"/></svg>')


def _name_html(name: str) -> str:
    """The name, with everything from its first `(` on a line below."""
    head, paren, rest = name.partition("(")
    if not (paren and head.strip()):
        return f'<div class="name">{escape(name)}</div>'
    return (f'<div class="name">{escape(head.strip())}</div>'
            f'<div class="name-sub">{escape(paren + rest)}</div>')


def labels_html(db: Session, *, search: str | None = None,
                barcodes: list[str] | None = None,
                location: str | None = None) -> str:
    """All live items, a Find Item search result (`search`, same matching
    as `GET /items?q=`), specific primary `barcodes`, and/or one exact
    `location`. The location picker lists every live item's location."""
    everything = items_service.list_items(db)
    items = everything if search is None else items_service.list_items(db, search=search)
    if barcodes:
        items = [i for i in items if i.barcode in barcodes]
    if location:
        items = [i for i in items if i.location == location]
    items = sorted(items, key=lambda i: i.name.lower())

    options = "".join(
        f'<option value="{escape(loc)}"{" selected" if loc == location else ""}>'
        f"{escape(loc)}</option>"
        for loc in sorted({i.location for i in everything}, key=str.lower)
    )
    labels = "".join(
        f'<div class="label">{_bars_html(i.barcode)}'
        f'<div class="code">{escape(i.barcode)}</div>{_name_html(i.name)}</div>'
        for i in items
    )
    count = f"{len(items)} label{'' if len(items) == 1 else 's'}"
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        "<title>Labels</title>"
        '<link rel="stylesheet" href="/static/labels.css"></head><body>'
        '<form class="toolbar" method="get">'
        '<label>Location <select name="location"><option value="">All items</option>'
        f'{options}</select></label><button type="submit">Show</button>'
        f'<span>{count}. Press Ctrl+P and print at 100% scale, or choose "Save as PDF".'
        "</span></form>"
        f'<div class="sheet">{labels}</div></body></html>'
    )
