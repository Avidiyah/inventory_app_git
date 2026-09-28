"""Printable barcode labels: one per live item, barcode over name.

Rendered as HTML, not a PDF, so the viewer's browser draws the barcode in
the locally installed `IDAutomationHC39M Free Version` Code 39 font; the
user prints or saves as PDF from there. A machine without the font sees
plain text.
"""

from html import escape

from sqlalchemy.orm import Session

from app.services import items as items_service


def labels_html(db: Session, *, search: str | None = None,
                barcodes: list[str] | None = None) -> str:
    """All live items, a Find Item search result (`search`, same matching
    as `GET /items?q=`), or specific primary `barcodes`."""
    items = items_service.list_items(db, search=search)
    if barcodes:
        items = [i for i in items if i.barcode in barcodes]
    items = sorted(items, key=lambda i: i.name.lower())
    # Code 39 fonts need the * start/stop characters to scan.
    labels = "".join(
        f'<div class="label"><div class="code39">*{escape(i.barcode)}*</div>'
        f'<div class="name">{escape(i.name)}</div></div>'
        for i in items
    )
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        "<title>Barcode labels</title>"
        '<link rel="stylesheet" href="/static/labels.css"></head><body>'
        '<p class="hint">Press Ctrl+P, then print or choose "Save as PDF".</p>'
        f"{labels}</body></html>"
    )
