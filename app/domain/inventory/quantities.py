"""Stock quantity rules — pure, no ORM. Quantities are Decimal, never float,
and are stored as NUMERIC(18, 4): four decimal places in the item's base
unit (docs/architecture/inventory-integration.md D12).
"""

from decimal import Decimal

QUANTITY_PLACES = 4
_QUANTUM = Decimal(1).scaleb(-QUANTITY_PLACES)  # Decimal("0.0001")

# NUMERIC(18, 4) holds at most 14 digits before the decimal point.
MAX_QUANTITY = Decimal(10) ** 14 - _QUANTUM


class QuantityError(ValueError):
    """A quantity that cannot be stored or is not allowed for its unit."""


def has_valid_precision(quantity: Decimal) -> bool:
    """True when `quantity` needs no more than QUANTITY_PLACES decimals."""
    return quantity == quantity.quantize(_QUANTUM)


def normalise(quantity: Decimal) -> Decimal:
    """Checks a quantity fits the column and returns it at exactly four
    decimal places. Never rounds: a value needing more precision is
    rejected, because silently rounding stock is how ledgers drift."""
    if not quantity.is_finite():
        raise QuantityError("quantity must be a finite number")
    if not has_valid_precision(quantity):
        raise QuantityError(f"quantity {quantity} has more than {QUANTITY_PLACES} decimal places")
    if abs(quantity) > MAX_QUANTITY:
        raise QuantityError(f"quantity {quantity} is too large")
    return quantity.quantize(_QUANTUM)


def to_base_quantity(quantity: Decimal, factor_to_base: Decimal) -> Decimal:
    """Converts a quantity in some unit into the item's base unit, e.g. 2
    cartons x 24 pieces/carton = 48 pieces. Exact: rejects a result that
    would need more than four decimal places instead of rounding it."""
    if factor_to_base <= 0:
        raise QuantityError("a unit conversion factor must be greater than zero")
    return normalise(quantity * factor_to_base)


def require_whole_if_needed(quantity: Decimal, *, allows_fraction: bool, unit_code: str) -> None:
    """Units such as pieces or boxes only come in whole numbers."""
    if not allows_fraction and quantity != quantity.to_integral_value():
        raise QuantityError(f"{unit_code} does not allow fractional quantities")
