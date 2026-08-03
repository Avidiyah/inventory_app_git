"""The customer-facing work-order receipt.

Layer: pure domain (no FastAPI, no SQLAlchemy, no Pydantic).

This is a **port of `static/adminReviewReceipt.js` + `static/pricingText.js`**,
which build the same receipt in the browser for the Admin Review page's copy
box. The two must agree character for character: Admin Review is where a
receipt is read and pasted, and the "For Client" CSV export is the same receipt
delivered in bulk, so a number that differs between them is a billing
discrepancy. `tests/test_receipt.py` pins the output; change one side and the
other has to move with it.

Contract inherited from the destination system: every line fits within 41
characters, because the company's receipt box hard-wraps at 42. Materials carry
a fixed 15% mark-up; labor does not (`domain.work_orders.labor_charge` already
prices it).
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Sequence

# The destination hard-wraps at character 42, so 41 is the usable width.
PRICING_LINE_WIDTH = 41

# Fixed company mark-up applied to material charges (not to labor). Mirrors
# MARKUP_RATE in `static/adminReviewReceipt.js`, `static/views/history.js`, and
# `static/views/workOrders.js`.
MARKUP_RATE = Decimal("1.15")


@dataclass(frozen=True)
class ReceiptLine:
    """One material line: what was used, and what it costs. `unit_price` is
    None for an item that has no price yet -- the receipt says so out loud
    rather than quietly billing zero."""

    name: str
    quantity: Decimal
    billable_quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None


@dataclass(frozen=True)
class Receipt:
    """The rendered receipt plus the names blocking it. `missing_prices` is
    what makes a receipt "incomplete"; Admin Review refuses to close a work
    order while it is non-empty."""

    text: str
    missing_prices: tuple[str, ...]


def _round_money(value: Decimal) -> Decimal:
    """Two decimal places, half away from zero -- how the browser's
    `toLocaleString` currency formatting rounds for display."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def format_money(value) -> str:
    """`$1,234.56`, matching `format.js formatMoney` (en-US currency). A
    negative amount leads with the sign, as the browser renders it."""
    if value is None or value == "":
        return ""
    amount = _round_money(Decimal(value))
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def format_quantity(quantity) -> str:
    """Shortest form of a quantity (`3.00` -> `3`, `0.50` -> `0.5`), matching
    the JS `String(Number(quantity))`."""
    value = Decimal(quantity)
    if value == value.to_integral_value():
        return str(value.quantize(Decimal(1)))
    return format(value.normalize(), "f")


def sanitise(value) -> str:
    """Tabs/newlines would break the one-row-per-line contract in the
    destination, so they collapse to a single space."""
    text = str(value)
    out = []
    previous_ws = False
    for char in text:
        if char in "\t\r\n":
            if not previous_ws:
                out.append(" ")
            previous_ws = True
        else:
            out.append(char)
            previous_ws = False
    return "".join(out)


def pricing_line(quantity, name, price) -> str:
    """One `<qty> <name>...<price>` line, price flush right within the 41-char
    width. An over-long name is truncated with `...` so the amount always
    stays aligned."""
    qty = sanitise(quantity)
    name_text = sanitise(name)
    price_text = sanitise(price)
    prefix = f"{qty} "
    name_width = PRICING_LINE_WIDTH - len(prefix) - len(price_text)
    if name_width < 1:
        return f"{prefix}{price_text}"[:PRICING_LINE_WIDTH]
    if len(name_text) <= name_width:
        return prefix + name_text.ljust(name_width) + price_text
    cut = name_width - 3
    trimmed = name_text[:cut] + "..." if cut > 0 else "." * name_width
    return prefix + trimmed + price_text


def pricing_amount_line(label, price) -> str:
    """A right-aligned amount after a label -- the closing Total line."""
    label_text = sanitise(label)
    price_text = sanitise(price)
    label_width = PRICING_LINE_WIDTH - len(price_text)
    if label_width < 1:
        return price_text[:PRICING_LINE_WIDTH]
    if len(label_text) <= label_width:
        return label_text.ljust(label_width) + price_text
    cut = label_width - 3
    trimmed = label_text[:cut] + "..." if cut > 0 else "." * label_width
    return trimmed + price_text


def billed_labor_hours(minutes: int) -> str:
    """Billed minutes as shortest-form hours (`90` -> `1.5`), rounded to two
    places first like the JS `hours.toFixed(2)`."""
    hours = Decimal(minutes or 0) / Decimal(60)
    return format_quantity(hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def effective_billable(line: ReceiptLine) -> Decimal:
    """Units actually charged: the override when set, else the full quantity."""
    return line.quantity if line.billable_quantity is None else line.billable_quantity


def marked_material_charge(line: ReceiptLine) -> Optional[Decimal]:
    """One line's marked-up charge, or None when the item has no price."""
    if line.unit_price is None:
        return None
    return effective_billable(line) * Decimal(line.unit_price) * MARKUP_RATE


def build_receipt(
    *,
    lines: Sequence[ReceiptLine],
    labor_billed_minutes: int,
    labor_total: Decimal,
) -> Receipt:
    """Render the receipt: one line per material at the marked-up charge, the
    billed labor hours, then the Total.

    An item with no price prints `NO PRICE` and is collected into
    `missing_prices`, which also relabels the closing line
    `Total (incomplete)` -- the total below it is real but understated, and
    saying so is the point."""
    rendered: list[str] = []
    missing: list[str] = []
    marked_materials = Decimal(0)

    for line in lines:
        quantity = effective_billable(line)
        charge = marked_material_charge(line)
        if charge is None:
            missing.append(line.name)
            rendered.append(
                pricing_line(format_quantity(quantity), line.name, "NO PRICE")
            )
            continue
        marked_materials += charge
        rendered.append(
            pricing_line(format_quantity(quantity), line.name, format_money(charge))
        )

    labor = Decimal(labor_total or 0)
    rendered.append(
        pricing_line(
            f"[{billed_labor_hours(labor_billed_minutes)}]",
            "Labor Hours",
            format_money(labor),
        )
    )

    total = marked_materials + labor
    rendered.append("")
    rendered.append(
        pricing_amount_line(
            "Total (incomplete)" if missing else "Total",
            format_money(total),
        )
    )
    return Receipt(text="\n".join(rendered), missing_prices=tuple(missing))
