"""How much an asset depreciates (or a leased asset amortises) in a period.

Three methods, as an accountant chooses them per asset:

- straight line: the same charge every year. From a rate (say 20% of cost
  a year) or, without one, spread evenly over the useful life;
- reducing balance: the rate applied to the net book value at the start of
  the period, so the charge falls each year;
- write off: the whole cost (less salvage value) charged at once.

A charge for part of a year (an asset bought in October, a monthly run) is
the yearly charge times months / 12. Amounts are integer minor units,
rounded down, and a charge never takes accumulated depreciation past cost
less salvage value. Rates are parts per million (200_000 = 20%).
"""

import enum
from datetime import date

PPM = 1_000_000


class DepreciationMethod(str, enum.Enum):
    STRAIGHT_LINE = "straight_line"
    REDUCING_BALANCE = "reducing_balance"
    WRITE_OFF = "write_off"


def check_method(method: DepreciationMethod, *, rate_ppm: int | None) -> None:
    if rate_ppm is not None and not 0 < rate_ppm <= PPM:
        raise ValueError("the depreciation rate must be more than 0% and at most 100%")
    if method == DepreciationMethod.REDUCING_BALANCE and rate_ppm is None:
        raise ValueError("reducing balance needs a depreciation rate (a percentage a year)")


def period_charge(
    *,
    method: DepreciationMethod,
    cost_minor: int,
    salvage_value_minor: int,
    accumulated_minor: int,
    useful_life_months: int,
    rate_ppm: int | None,
    months: int,
) -> int:
    """The charge for `months` (1 to 12) of depreciation."""
    if not 1 <= months <= 12:
        raise ValueError("a depreciation period is 1 to 12 months")
    remaining = cost_minor - salvage_value_minor - accumulated_minor
    if remaining <= 0:
        return 0
    if method == DepreciationMethod.WRITE_OFF:
        charge = remaining
    elif method == DepreciationMethod.REDUCING_BALANCE:
        if rate_ppm is None:
            raise ValueError("reducing balance needs a depreciation rate")
        book_value = cost_minor - accumulated_minor
        charge = book_value * rate_ppm * months // (PPM * 12)
    elif rate_ppm is not None:
        charge = cost_minor * rate_ppm * months // (PPM * 12)
    else:
        charge = (cost_minor - salvage_value_minor) * months // useful_life_months
    return min(charge, remaining)


def months_held(acquisition_date: date, year: int) -> int:
    """Months of `year` the asset was held, counting the month it was
    acquired in as a full month: 12 for an asset held all year, 0 for one
    acquired after it."""
    if acquisition_date.year > year:
        return 0
    if acquisition_date.year < year:
        return 12
    return 13 - acquisition_date.month
