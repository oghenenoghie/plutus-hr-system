from datetime import date

import pytest

from app.domain.accounting.depreciation import (
    DepreciationMethod,
    check_method,
    months_held,
    period_charge,
)


def _charge(method: DepreciationMethod, **overrides: int | None) -> int:
    args: dict = {
        "cost_minor": 1_000_000_00,
        "salvage_value_minor": 0,
        "accumulated_minor": 0,
        "useful_life_months": 60,
        "rate_ppm": None,
        "months": 12,
    }
    args.update(overrides)
    return period_charge(method=method, **args)


def test_straight_line_over_the_useful_life_or_at_a_rate() -> None:
    assert _charge(DepreciationMethod.STRAIGHT_LINE) == 200_000_00
    assert _charge(DepreciationMethod.STRAIGHT_LINE, months=1) == 16_666_66
    assert _charge(DepreciationMethod.STRAIGHT_LINE, rate_ppm=250_000) == 250_000_00
    assert _charge(DepreciationMethod.STRAIGHT_LINE, salvage_value_minor=100_000_00) == 180_000_00


def test_reducing_balance_applies_the_rate_to_net_book_value() -> None:
    # 25% a year: 250,000 the first year, then 25% of 750,000.
    assert _charge(DepreciationMethod.REDUCING_BALANCE, rate_ppm=250_000) == 250_000_00
    assert (
        _charge(DepreciationMethod.REDUCING_BALANCE, rate_ppm=250_000, accumulated_minor=250_000_00)
        == 187_500_00
    )
    # Three months of a year.
    assert _charge(DepreciationMethod.REDUCING_BALANCE, rate_ppm=250_000, months=3) == 62_500_00


def test_write_off_charges_everything_at_once() -> None:
    assert _charge(DepreciationMethod.WRITE_OFF, salvage_value_minor=10_000_00) == 990_000_00


def test_a_charge_never_passes_cost_less_salvage() -> None:
    assert _charge(DepreciationMethod.STRAIGHT_LINE, accumulated_minor=950_000_00) == 50_000_00
    assert _charge(DepreciationMethod.STRAIGHT_LINE, accumulated_minor=1_000_000_00) == 0
    assert (
        _charge(
            DepreciationMethod.REDUCING_BALANCE,
            rate_ppm=500_000,
            salvage_value_minor=400_000_00,
            accumulated_minor=500_000_00,
        )
        == 100_000_00
    )


def test_reducing_balance_needs_a_rate_and_rates_are_bounded() -> None:
    with pytest.raises(ValueError, match="needs a depreciation rate"):
        check_method(DepreciationMethod.REDUCING_BALANCE, rate_ppm=None)
    with pytest.raises(ValueError, match="at most 100%"):
        check_method(DepreciationMethod.STRAIGHT_LINE, rate_ppm=1_500_000)
    check_method(DepreciationMethod.STRAIGHT_LINE, rate_ppm=None)


def test_months_held_in_a_year() -> None:
    assert months_held(date(2025, 6, 1), 2026) == 12
    assert months_held(date(2026, 10, 15), 2026) == 3
    assert months_held(date(2026, 1, 1), 2026) == 12
    assert months_held(date(2027, 1, 1), 2026) == 0
