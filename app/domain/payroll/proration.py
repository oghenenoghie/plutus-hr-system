from dataclasses import dataclass
from datetime import date, timedelta

# Proration basis: working days (Mon-Fri, minus configured public holidays)
# in both the numerator and the denominator — chosen over calendar days or
# a 30-day convention as a product decision. This means a partial period
# credits a day only if it would otherwise have been worked, which is why
# a weekend or holiday inside a partial period neither helps nor hurts the
# prorated amount.


def is_working_day(day: date, holidays: frozenset[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def working_days_in_range(start: date, end: date, holidays: frozenset[date]) -> int:
    if start > end:
        return 0
    return sum(
        1
        for offset in range((end - start).days + 1)
        if is_working_day(start + timedelta(days=offset), holidays)
    )


def _scale(amount_minor: int, *, credited_days: int, total_days: int) -> int:
    """Round-half-up integer scaling — the same documented rounding rule
    app.domain.money.apply_rate_ppm uses for tax, applied here to a
    days-credited/total-days ratio instead of a parts-per-million rate."""
    return (amount_minor * credited_days + total_days // 2) // total_days


@dataclass(frozen=True)
class PayComponents:
    basic_minor: int
    housing_minor: int
    transport_minor: int
    other_earnings_minor: int


@dataclass(frozen=True)
class ProrationResult:
    basic_minor: int
    housing_minor: int
    transport_minor: int
    other_earnings_minor: int
    total_working_days: int
    credited_working_days: int

    @property
    def is_prorated(self) -> bool:
        return self.credited_working_days < self.total_working_days


def prorate_pay_components(
    *,
    period_start: date,
    period_end: date,
    hire_date: date,
    current: PayComponents,
    prior: PayComponents | None = None,
    change_effective_date: date | None = None,
    unpaid_leave_ranges: tuple[tuple[date, date], ...] = (),
    holidays: frozenset[date] = frozenset(),
) -> ProrationResult:
    """Prorates one pay period's basic/housing/transport/other_earnings for:
    - a new hire whose date_of_joining falls inside the period,
    - a mid-period compensation change (prior applies before
      change_effective_date, current from that date on — only the earliest
      change in a period is treated as a two-way split boundary, a
      disclosed simplification for the rare case of two changes in one
      period),
    - approved unpaid leave overlapping the period (working days inside
      unpaid_leave_ranges are not credited).

    Computed day by day rather than as a closed-form fraction, since that's
    the only way to combine "which rate applies" and "was this day on
    unpaid leave" correctly without duplicating the working-day walk for
    each concern separately. total_working_days is the full period's
    working days regardless of hire date — the denominator a partial
    period is measured against — while credited_working_days is what's
    actually paid for.
    """
    total_working_days = working_days_in_range(period_start, period_end, holidays)
    effective_start = max(period_start, hire_date)

    if effective_start > period_end:
        # The employee's own tenure hasn't started within this period at
        # all (hire_date falls after period_end) — nothing is owed for it,
        # not a full, unprorated amount.
        return ProrationResult(
            basic_minor=0,
            housing_minor=0,
            transport_minor=0,
            other_earnings_minor=0,
            total_working_days=total_working_days,
            credited_working_days=0,
        )

    if total_working_days <= 0:
        # A zero-working-day period (e.g. entirely on weekends/holidays) —
        # nothing to divide by, so there's no meaningful ratio to apply.
        # Pay the full, unprorated amount rather than dividing by zero.
        return ProrationResult(
            basic_minor=current.basic_minor,
            housing_minor=current.housing_minor,
            transport_minor=current.transport_minor,
            other_earnings_minor=current.other_earnings_minor,
            total_working_days=total_working_days,
            credited_working_days=total_working_days,
        )

    credited_current = 0
    credited_prior = 0
    day = effective_start
    while day <= period_end:
        if is_working_day(day, holidays) and not any(
            leave_start <= day <= leave_end for leave_start, leave_end in unpaid_leave_ranges
        ):
            if (
                prior is not None
                and change_effective_date is not None
                and day < change_effective_date
            ):
                credited_prior += 1
            else:
                credited_current += 1
        day += timedelta(days=1)

    def combine(field: str) -> int:
        current_amount = _scale(
            getattr(current, field), credited_days=credited_current, total_days=total_working_days
        )
        if prior is None or credited_prior == 0:
            return current_amount
        prior_amount = _scale(
            getattr(prior, field), credited_days=credited_prior, total_days=total_working_days
        )
        return current_amount + prior_amount

    return ProrationResult(
        basic_minor=combine("basic_minor"),
        housing_minor=combine("housing_minor"),
        transport_minor=combine("transport_minor"),
        other_earnings_minor=combine("other_earnings_minor"),
        total_working_days=total_working_days,
        credited_working_days=credited_current + credited_prior,
    )
