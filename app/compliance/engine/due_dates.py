"""When each statutory line is due, from the period it belongs to. The same
rules as app.domain.payroll.deadlines, which date Nigeria's liabilities from
the pay run's period end."""

from datetime import date, timedelta

from app.compliance.engine.rules import (
    DueDayOfFollowingMonth,
    DueDaysAfterPeriodEnd,
    DueRule,
    DueWorkingDaysAfterPeriodEnd,
)


def due_date(rule: DueRule, period_end: date) -> date:
    if isinstance(rule, DueDayOfFollowingMonth):
        year, month = period_end.year, period_end.month + 1
        if month > 12:
            year, month = year + 1, 1
        return date(year, month, rule.day)
    if isinstance(rule, DueDaysAfterPeriodEnd):
        return period_end + timedelta(days=rule.days)
    if not isinstance(rule, DueWorkingDaysAfterPeriodEnd):
        raise TypeError(f"unknown due rule {rule!r}")
    current = period_end
    remaining = rule.days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Monday=0 .. Friday=4
            remaining -= 1
    return current
