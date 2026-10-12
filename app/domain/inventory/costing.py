"""Moving weighted-average costing — pure, no ORM.

One cost pool per organisation and item (docs/architecture/
inventory-integration.md D1): every warehouse shares the item's average, so
moving stock between warehouses can never change its value.

Values are integer minor units (kobo). Quantities are Decimal in the item's
base unit. The pool's invariants, which every function here preserves:

* quantity >= 0 and value_minor >= 0;
* quantity == 0 implies value_minor == 0 (no orphaned value when the last
  unit leaves — the final decrease takes whatever value is left).
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal


class InsufficientStockError(ValueError):
    """A decrease larger than the stock available."""


@dataclass(frozen=True)
class CostPool:
    quantity: Decimal
    value_minor: int

    def __post_init__(self) -> None:
        if self.quantity < 0 or self.value_minor < 0:
            raise ValueError("a cost pool cannot hold a negative quantity or value")
        if self.quantity == 0 and self.value_minor != 0:
            raise ValueError("a cost pool with no quantity cannot hold value")


EMPTY_POOL = CostPool(quantity=Decimal(0), value_minor=0)


def round_minor(amount: Decimal) -> int:
    """Rounds to whole minor units, half to even (banker's rounding), so
    repeated rounding has no systematic upward or downward bias."""
    return int(amount.to_integral_value(rounding=ROUND_HALF_EVEN))


def increase_value(quantity: Decimal, unit_cost_minor: int) -> int:
    """The value stock enters at: quantity x unit cost, rounded once."""
    if quantity <= 0:
        raise ValueError("an increase needs a positive quantity")
    if unit_cost_minor < 0:
        raise ValueError("a unit cost cannot be negative")
    return round_minor(quantity * unit_cost_minor)


def decrease_value(pool: CostPool, quantity: Decimal) -> int:
    """The value stock leaves at: its share of the pool at the current
    average. Taking the whole quantity takes the whole value, so rounding
    never leaves a residue behind."""
    if quantity <= 0:
        raise ValueError("a decrease needs a positive quantity")
    if quantity > pool.quantity:
        raise InsufficientStockError(f"cannot remove {quantity}: only {pool.quantity} available")
    if quantity == pool.quantity:
        return pool.value_minor
    return round_minor(Decimal(pool.value_minor) * quantity / pool.quantity)


def apply_increase(pool: CostPool, quantity: Decimal, value_minor: int) -> CostPool:
    if quantity <= 0 or value_minor < 0:
        raise ValueError("an increase needs a positive quantity and a non-negative value")
    return CostPool(quantity=pool.quantity + quantity, value_minor=pool.value_minor + value_minor)


def apply_decrease(pool: CostPool, quantity: Decimal) -> tuple[CostPool, int]:
    """Removes `quantity` at the current average; returns the new pool and
    the (positive) value removed."""
    value = decrease_value(pool, quantity)
    remaining = CostPool(quantity=pool.quantity - quantity, value_minor=pool.value_minor - value)
    return remaining, value


def average_unit_cost(pool: CostPool) -> Decimal | None:
    """Exact average cost per base unit, or None for an empty pool."""
    if pool.quantity == 0:
        return None
    return Decimal(pool.value_minor) / pool.quantity


def valued_at_average(pool: CostPool, quantity: Decimal) -> int:
    """`quantity` priced at the pool's average, for display (e.g. one
    warehouse's share of the item's value). Never posted."""
    average = average_unit_cost(pool)
    if average is None or quantity == 0:
        return 0
    if quantity == pool.quantity:
        return pool.value_minor
    return round_minor(average * quantity)
