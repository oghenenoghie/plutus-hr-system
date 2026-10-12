"""Stocktake rules (D6), free of the database so they can be tested
exhaustively. See docs/architecture/inventory-integration.md §16.

A stocktake compares what was counted with a snapshot of the books taken at
its cutoff, and posts only the difference. Stock that moved after the cutoff
is therefore never overwritten: the variance is added to whatever the
balance is when the stocktake posts.
"""

from collections.abc import Iterable
from decimal import Decimal

from app.domain.inventory.costing import CostPool, increase_value, round_minor


def variance(expected: Decimal, counted: Decimal) -> Decimal:
    """Counted minus expected: positive is stock found, negative is stock
    missing."""
    return counted - expected


def gain_value_minor(
    quantity: Decimal, pool: CostPool, default_cost_minor: int | None
) -> int | None:
    """What stock found in a count is worth: the item's current average
    cost, or its default cost when it holds no stock to average. None when
    neither is known (the count can't be valued and so can't post)."""
    if quantity <= 0:
        raise ValueError("a gain needs a positive quantity")
    if pool.quantity > 0:
        return round_minor(Decimal(pool.value_minor) * quantity / pool.quantity)
    if default_cost_minor is not None:
        return increase_value(quantity, default_cost_minor)
    return None


def needs_approval(
    variances: Iterable[tuple[Decimal, int | None]], gain_limit_minor: int | None
) -> bool:
    """The adjustment rule (D8) applied to a count: any stock missing needs
    approval; stock found needs it once its value reaches the limit (never,
    with no limit). A count that found nothing extra needs none, even with
    a limit of zero. `variances` are (quantity, value of a gain)."""
    gained = 0
    for quantity, value in variances:
        if quantity < 0:
            return True
        if quantity > 0:
            gained += value or 0
    return gain_limit_minor is not None and gained > 0 and gained >= gain_limit_minor
