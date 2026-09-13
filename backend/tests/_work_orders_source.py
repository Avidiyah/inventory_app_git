"""The Work Orders page's source, for the served-source tests.

`static/views/workOrders.js` is a barrel: the page's implementation lives in
its `workOrder*.js` siblings. Tests that pin the page's JavaScript as text
read the whole family through `work_orders_source()`, so a further module
split moves code without breaking a test that never cared which file held
it.

`workOrderRequests.js` is excluded on purpose. The material-request panel
is its own surface with its own `data-request-action` namespace and its own
`statusLabel`; folding it in would make the walkthrough-action parity test
compare two vocabularies.
"""

from pathlib import Path

VIEWS = Path(__file__).resolve().parents[1] / "static" / "views"

EXCLUDED = {"workOrderRequests.js"}


def work_orders_family() -> list[Path]:
    """The barrel plus every sibling, in a stable order."""
    siblings = sorted(
        path
        for path in VIEWS.glob("workOrder*.js")
        if path.name != "workOrders.js" and path.name not in EXCLUDED
    )
    return [VIEWS / "workOrders.js", *siblings]


def work_orders_source() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in work_orders_family())
