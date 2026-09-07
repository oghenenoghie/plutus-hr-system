import enum


class PayFrequency(str, enum.Enum):
    MONTHLY = "monthly"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"


_PERIODS_PER_YEAR: dict[PayFrequency, int] = {
    PayFrequency.MONTHLY: 12,
    PayFrequency.WEEKLY: 52,
    PayFrequency.BIWEEKLY: 26,
}


def periods_per_year(frequency: PayFrequency) -> int:
    return _PERIODS_PER_YEAR[frequency]


def prorate_annual_amount(
    annual_amount_minor: int, periods_elapsed: int, frequency: PayFrequency
) -> int:
    """Recognise a fixed annual amount (e.g. rent relief) cumulatively as the
    year progresses, reaching the full annual figure exactly at year-end —
    the same 'to-date' mechanism cumulative PAYE itself relies on, applied
    to the relief instead of the tax."""
    if annual_amount_minor < 0:
        raise ValueError("annual_amount_minor must not be negative")
    if periods_elapsed < 0:
        raise ValueError("periods_elapsed must not be negative")
    total_periods = periods_per_year(frequency)
    return annual_amount_minor * min(periods_elapsed, total_periods) // total_periods
