"""Purchase-order arithmetic — pure, no ORM.

Prices are integer minor units (kobo) per order-line unit; quantities are
Decimal. Tax is entered per line as an amount (no rate is assumed, D14) and
never enters stock value: stock is valued at the net price (after the line
discount), because recoverable VAT is handled by the bill (D14).
"""

from collections.abc import Iterable
from decimal import ROUND_DOWN, Decimal

from app.domain.inventory.costing import round_minor
from app.domain.inventory.quantities import QUANTITY_PLACES

_QUANTUM = Decimal(1).scaleb(-QUANTITY_PLACES)
_BASIS_POINTS = Decimal(10_000)


def line_gross_minor(quantity: Decimal, unit_price_minor: int) -> int:
    """quantity x unit price, rounded once (half-even)."""
    return round_minor(quantity * unit_price_minor)


def line_net_minor(quantity: Decimal, unit_price_minor: int, discount_minor: int) -> int:
    if discount_minor < 0:
        raise ValueError("a discount cannot be negative")
    if Decimal(discount_minor) > quantity * unit_price_minor:
        raise ValueError("the discount can't be more than the line's value")
    return max(line_gross_minor(quantity, unit_price_minor) - discount_minor, 0)


def line_total_minor(
    quantity: Decimal, unit_price_minor: int, discount_minor: int, tax_minor: int
) -> int:
    return line_net_minor(quantity, unit_price_minor, discount_minor) + tax_minor


def receipt_value_minor(
    accepted_quantity: Decimal,
    ordered_quantity: Decimal,
    unit_price_minor: int,
    discount_minor: int,
) -> int:
    """What received goods enter stock at: their share of the line's net
    value, i.e. accepted x (ordered x price - discount) / ordered, rounded
    once. Quantities are in the order line's unit. Goods received within
    an over-receipt tolerance are valued at the same net unit price."""
    if ordered_quantity <= 0:
        raise ValueError("an order line needs a positive quantity")
    if accepted_quantity < 0:
        raise ValueError("an accepted quantity cannot be negative")
    net_exact = ordered_quantity * unit_price_minor - discount_minor
    return round_minor(accepted_quantity * net_exact / ordered_quantity)


def max_receivable_base(ordered_base: Decimal, tolerance_bp: int) -> Decimal:
    """The most that may be received against a line in total: the ordered
    quantity plus the organisation's over-receipt tolerance (D4, in basis
    points; 0 = exactly the ordered quantity). Rounded down to the stored
    precision, so a tolerance never allows more than it says."""
    if not 0 <= tolerance_bp <= 10_000:
        raise ValueError("over-receipt tolerance must be between 0% and 100%")
    allowed = ordered_base * (_BASIS_POINTS + tolerance_bp) / _BASIS_POINTS
    return allowed.quantize(_QUANTUM, rounding=ROUND_DOWN)


def receipt_progress(lines: Iterable[tuple[Decimal, Decimal]]) -> str:
    """'none', 'partial' or 'full' for (ordered_base, received_base) pairs:
    full once every line has received at least its ordered quantity."""
    pairs = list(lines)
    if not pairs or all(received <= 0 for _, received in pairs):
        return "none"
    if all(received >= ordered for ordered, received in pairs):
        return "full"
    return "partial"
