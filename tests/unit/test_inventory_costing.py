from decimal import Decimal

import pytest

from app.domain.inventory.costing import (
    EMPTY_POOL,
    CostPool,
    InsufficientStockError,
    apply_decrease,
    apply_increase,
    average_unit_cost,
    decrease_value,
    increase_value,
    round_minor,
    valued_at_average,
)


def test_round_minor_is_half_even() -> None:
    assert round_minor(Decimal("2.5")) == 2
    assert round_minor(Decimal("3.5")) == 4
    assert round_minor(Decimal("-2.5")) == -2
    assert round_minor(Decimal("2.51")) == 3


def test_increase_value_rounds_once() -> None:
    assert increase_value(Decimal(3), 1_000_00) == 3_000_00
    assert increase_value(Decimal("0.3333"), 100) == 33


def test_weighted_average_after_two_receipts() -> None:
    pool = apply_increase(EMPTY_POOL, Decimal(10), 10 * 100_00)  # 10 @ N100
    pool = apply_increase(pool, Decimal(30), 30 * 200_00)  # 30 @ N200
    assert pool == CostPool(quantity=Decimal(40), value_minor=7_000_00)
    assert average_unit_cost(pool) == Decimal(175_00)


def test_decrease_leaves_at_the_average() -> None:
    pool = CostPool(quantity=Decimal(40), value_minor=7_000_00)
    remaining, value = apply_decrease(pool, Decimal(4))
    assert value == 700_00
    assert remaining == CostPool(quantity=Decimal(36), value_minor=6_300_00)


def test_taking_everything_takes_all_the_value() -> None:
    # 3 units worth 100 kobo: the average (33.33...) would leave a residue
    # if each unit were rounded separately.
    pool = CostPool(quantity=Decimal(3), value_minor=100)
    pool, first = apply_decrease(pool, Decimal(1))
    pool, second = apply_decrease(pool, Decimal(1))
    pool, third = apply_decrease(pool, Decimal(1))
    assert (first, second, third) == (33, 34, 33)
    assert pool == EMPTY_POOL


def test_decrease_beyond_stock_raises() -> None:
    with pytest.raises(InsufficientStockError):
        decrease_value(CostPool(quantity=Decimal(2), value_minor=200), Decimal(3))


def test_pool_invariants_are_enforced() -> None:
    with pytest.raises(ValueError):
        CostPool(quantity=Decimal(-1), value_minor=0)
    with pytest.raises(ValueError):
        CostPool(quantity=Decimal(0), value_minor=5)


def test_zero_cost_stock_is_allowed() -> None:
    pool = apply_increase(EMPTY_POOL, Decimal(5), 0)
    assert pool == CostPool(quantity=Decimal(5), value_minor=0)
    assert average_unit_cost(pool) == 0


def test_valued_at_average() -> None:
    pool = CostPool(quantity=Decimal(3), value_minor=100)
    assert valued_at_average(pool, Decimal(3)) == 100
    assert valued_at_average(pool, Decimal(1)) == 33
    assert valued_at_average(EMPTY_POOL, Decimal(0)) == 0
