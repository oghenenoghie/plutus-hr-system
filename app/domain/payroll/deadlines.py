"""Remittance deadlines, computed from the versioned rule set — never a
hardcoded day-of-month in calling code. Public holidays are NOT modelled:
there's no authoritative Nigerian public-holiday calendar in the
compliance reference to source one from, so `pension_deadline` only skips
weekends. Treat its result as a lower bound, not a guarantee, until a real
holiday calendar is wired in.
"""

from datetime import date, timedelta

from app.compliance.models import ItfRule, NhfRule, NsitfRule, PayeRule, PensionRule


def _same_day_of_following_month(on: date, day_of_month: int) -> date:
    year, month = on.year, on.month + 1
    if month > 12:
        year, month = year + 1, 1
    return date(year, month, day_of_month)


def paye_deadline(payment_date: date, rule: PayeRule) -> date:
    """§9: within N days of the following month."""
    return _same_day_of_following_month(payment_date, rule.due_day_of_following_month)


def nsitf_deadline(payment_date: date, rule: NsitfRule) -> date:
    """§6: before the Nth of the following month."""
    return _same_day_of_following_month(payment_date, rule.due_day_of_following_month)


def nhf_deadline(payment_date: date, rule: NhfRule) -> date:
    """§4: within N days of payment."""
    return payment_date + timedelta(days=rule.due_days_after_payment)


def pension_deadline(payment_date: date, rule: PensionRule) -> date:
    """§3: N working days after payment — weekends skipped, public
    holidays not (see module docstring)."""
    if rule.due_working_days_after_payment < 0:
        raise ValueError("due_working_days_after_payment must not be negative")
    current = payment_date
    remaining = rule.due_working_days_after_payment
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Monday=0 .. Friday=4
            remaining -= 1
    return current


def itf_deadline(payment_year: int, rule: ItfRule) -> date:
    """§7: on/before 1 April of the year following the payroll year."""
    return date(payment_year + 1, rule.due_month, rule.due_day)
