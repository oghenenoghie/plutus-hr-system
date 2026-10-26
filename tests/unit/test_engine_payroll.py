"""The pay-run helpers around the engine (app/services/engine_payroll.py)
that need no database."""

from datetime import date

import pytest

from app.compliance.engine.rules import EarningCategory
from app.services.engine_payroll import earnings_for, tax_year_start


@pytest.mark.parametrize(
    ("period_end", "start_month", "expected"),
    [
        (date(2026, 3, 31), 1, date(2026, 1, 1)),
        (date(2026, 1, 31), 1, date(2026, 1, 1)),
        (date(2026, 6, 30), 7, date(2025, 7, 1)),
        (date(2026, 7, 31), 7, date(2026, 7, 1)),
        (date(2026, 12, 31), 7, date(2026, 7, 1)),
    ],
)
def test_the_tax_year_starts_on_the_rule_sets_month(
    period_end: date, start_month: int, expected: date
) -> None:
    assert tax_year_start(period_end, start_month) == expected


def test_each_pay_component_lands_in_its_own_category() -> None:
    earnings = earnings_for(
        basic_minor=1,
        housing_minor=2,
        transport_minor=3,
        recurring_other_minor=4,
        overtime_minor=5,
        one_off_minor=6,
    )
    assert {earning.category: earning.amount_minor for earning in earnings} == {
        EarningCategory.BASIC: 1,
        EarningCategory.HOUSING: 2,
        EarningCategory.TRANSPORT: 3,
        EarningCategory.FIXED_ALLOWANCE: 4,
        EarningCategory.VARIABLE: 5,
        EarningCategory.OTHER: 6,
    }
