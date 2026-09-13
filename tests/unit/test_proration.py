from datetime import date

from app.domain.payroll.proration import (
    PayComponents,
    is_working_day,
    prorate_pay_components,
    working_days_in_range,
)

_JAN_2026 = (date(2026, 1, 1), date(2026, 1, 31))  # 22 working days (Thu-Sat)


def test_is_working_day_excludes_weekends_and_holidays() -> None:
    monday = date(2026, 1, 5)
    saturday = date(2026, 1, 3)
    holiday = date(2026, 1, 1)
    assert is_working_day(monday, frozenset())
    assert not is_working_day(saturday, frozenset())
    assert not is_working_day(holiday, frozenset({holiday}))


def test_working_days_in_range_january_2026() -> None:
    # 2026-01-01 is a Thursday; January 2026 has 22 weekdays.
    assert working_days_in_range(*_JAN_2026, frozenset()) == 22


def test_working_days_in_range_excludes_configured_holiday() -> None:
    new_years_day = date(2026, 1, 1)  # a Thursday, otherwise a working day
    assert working_days_in_range(*_JAN_2026, frozenset({new_years_day})) == 21


def test_full_period_is_not_prorated() -> None:
    components = PayComponents(
        basic_minor=300_000_00,
        housing_minor=150_000_00,
        transport_minor=50_000_00,
        other_earnings_minor=0,
    )
    result = prorate_pay_components(
        period_start=_JAN_2026[0],
        period_end=_JAN_2026[1],
        hire_date=date(2025, 1, 1),
        current=components,
    )
    assert not result.is_prorated
    assert result.basic_minor == components.basic_minor
    assert result.housing_minor == components.housing_minor
    assert result.transport_minor == components.transport_minor


def test_new_hire_mid_period_is_prorated_by_working_days() -> None:
    # Employee joins Monday 2026-01-19 — 10 working days remain in the 22
    # working-day period (Jan 19-23, 26-30).
    components = PayComponents(
        basic_minor=220_000, housing_minor=0, transport_minor=0, other_earnings_minor=0
    )
    result = prorate_pay_components(
        period_start=_JAN_2026[0],
        period_end=_JAN_2026[1],
        hire_date=date(2026, 1, 19),
        current=components,
    )
    assert result.is_prorated
    assert result.total_working_days == 22
    assert result.credited_working_days == 10
    assert result.basic_minor == 100_000  # 220_000 * 10 / 22, exact


def test_hire_date_after_period_end_credits_nothing() -> None:
    components = PayComponents(
        basic_minor=300_000_00, housing_minor=0, transport_minor=0, other_earnings_minor=0
    )
    result = prorate_pay_components(
        period_start=_JAN_2026[0],
        period_end=_JAN_2026[1],
        hire_date=date(2026, 2, 1),
        current=components,
    )
    assert result.credited_working_days == 0
    assert result.basic_minor == 0


def test_mid_period_compensation_change_splits_pay() -> None:
    # Change effective 2026-01-19 (a Monday): 12 working days at the prior
    # rate (Jan 1-18), 10 at the new rate (Jan 19-31).
    prior = PayComponents(
        basic_minor=110_000, housing_minor=0, transport_minor=0, other_earnings_minor=0
    )
    current = PayComponents(
        basic_minor=220_000, housing_minor=0, transport_minor=0, other_earnings_minor=0
    )
    result = prorate_pay_components(
        period_start=_JAN_2026[0],
        period_end=_JAN_2026[1],
        hire_date=date(2025, 1, 1),
        current=current,
        prior=prior,
        change_effective_date=date(2026, 1, 19),
    )
    # A mid-period rate change credits every working day (nothing is
    # excluded), so is_prorated is false even though the split changes the
    # amount paid — is_prorated only tracks credited vs. total days.
    assert not result.is_prorated
    assert result.credited_working_days == result.total_working_days == 22
    # 12 days at 110_000/22 (rounded) + 10 days at 220_000/22 (rounded).
    expected_prior_share = (110_000 * 12 + 22 // 2) // 22
    expected_current_share = (220_000 * 10 + 22 // 2) // 22
    assert result.basic_minor == expected_prior_share + expected_current_share
    assert result.basic_minor != current.basic_minor


def test_unpaid_leave_excludes_those_working_days() -> None:
    # A full working week (Jan 5-9) of unpaid leave inside the 22
    # working-day period leaves 17 credited days.
    components = PayComponents(
        basic_minor=220_000, housing_minor=0, transport_minor=0, other_earnings_minor=0
    )
    result = prorate_pay_components(
        period_start=_JAN_2026[0],
        period_end=_JAN_2026[1],
        hire_date=date(2025, 1, 1),
        current=components,
        unpaid_leave_ranges=((date(2026, 1, 5), date(2026, 1, 9)),),
    )
    assert result.is_prorated
    assert result.total_working_days == 22
    assert result.credited_working_days == 17
    assert result.basic_minor == (220_000 * 17 + 22 // 2) // 22


def test_weekend_inside_partial_period_neither_helps_nor_hurts() -> None:
    # Joining Saturday 2026-01-17 vs. Monday 2026-01-19 should credit the
    # same working days, since the weekend in between is excluded from
    # both the numerator and the denominator.
    components = PayComponents(
        basic_minor=220_000, housing_minor=0, transport_minor=0, other_earnings_minor=0
    )
    saturday_join = prorate_pay_components(
        period_start=_JAN_2026[0],
        period_end=_JAN_2026[1],
        hire_date=date(2026, 1, 17),
        current=components,
    )
    monday_join = prorate_pay_components(
        period_start=_JAN_2026[0],
        period_end=_JAN_2026[1],
        hire_date=date(2026, 1, 19),
        current=components,
    )
    assert saturday_join.credited_working_days == monday_join.credited_working_days
    assert saturday_join.basic_minor == monday_join.basic_minor
