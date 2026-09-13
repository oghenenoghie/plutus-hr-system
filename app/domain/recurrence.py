import calendar
import enum
from datetime import date


class RecurrenceFrequency(str, enum.Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUALLY = "annually"


_MONTHS_PER_OCCURRENCE = {
    RecurrenceFrequency.MONTHLY: 1,
    RecurrenceFrequency.QUARTERLY: 3,
    RecurrenceFrequency.ANNUALLY: 12,
}


def add_months(start: date, months: int) -> date:
    """Adds calendar months, clamping the day to the target month's last day
    (Jan 31 + 1 month -> Feb 28/29, not a rollover into March)."""
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def next_occurrence(current: date, frequency: RecurrenceFrequency) -> date:
    return add_months(current, _MONTHS_PER_OCCURRENCE[frequency])
