"""Properties of the weighted-average cost pool under any sequence of
receipts and issues: it never goes negative, never strands value with no
stock, and its value is always exactly what went in minus what came out."""

from decimal import ROUND_DOWN, Decimal

from hypothesis import given
from hypothesis import strategies as st

from app.domain.inventory.costing import (
    EMPTY_POOL,
    CostPool,
    apply_decrease,
    apply_increase,
    increase_value,
)

quantities = st.decimals(
    min_value=Decimal("0.0001"), max_value=Decimal(100_000), places=4, allow_nan=False
)
unit_costs = st.integers(min_value=0, max_value=10_000_000)
# True: receive (quantity, unit cost); False: issue a share (in basis points)
# of what is on hand.
steps = st.lists(
    st.tuples(st.booleans(), quantities, unit_costs, st.integers(min_value=1, max_value=10_000)),
    max_size=40,
)
_PLACES = Decimal("0.0001")


@given(steps)
def test_pool_conserves_value_and_never_goes_negative(
    operations: list[tuple[bool, Decimal, int, int]],
) -> None:
    pool = EMPTY_POOL
    value_in = 0
    value_out = 0
    for receive, quantity, unit_cost, basis_points in operations:
        if receive:
            value = increase_value(quantity, unit_cost)
            pool = apply_increase(pool, quantity, value)
            value_in += value
        else:
            wanted = (pool.quantity * basis_points / 10_000).quantize(_PLACES, ROUND_DOWN)
            if wanted <= 0:
                continue
            pool, value = apply_decrease(pool, wanted)
            assert value >= 0
            value_out += value
        assert pool.quantity >= 0 and pool.value_minor >= 0
        assert pool.quantity > 0 or pool.value_minor == 0
        assert pool.value_minor == value_in - value_out


@given(quantities, unit_costs)
def test_receiving_then_issuing_everything_returns_the_exact_value(
    quantity: Decimal, unit_cost: int
) -> None:
    value = increase_value(quantity, unit_cost)
    pool = apply_increase(EMPTY_POOL, quantity, value)
    remaining, out = apply_decrease(pool, quantity)
    assert out == value
    assert remaining == CostPool(quantity=Decimal(0), value_minor=0)


@given(quantities, unit_costs, st.integers(min_value=2, max_value=12))
def test_issuing_in_equal_parts_never_loses_a_kobo(
    quantity: Decimal, unit_cost: int, parts: int
) -> None:
    value = increase_value(quantity, unit_cost)
    pool = apply_increase(EMPTY_POOL, quantity, value)
    each = (quantity / parts).quantize(_PLACES, ROUND_DOWN)
    taken = 0
    for _ in range(parts - 1):
        if each <= 0:
            break
        pool, out = apply_decrease(pool, each)
        taken += out
    pool, last = apply_decrease(pool, pool.quantity) if pool.quantity > 0 else (pool, 0)
    assert taken + last == value
    assert pool == EMPTY_POOL
