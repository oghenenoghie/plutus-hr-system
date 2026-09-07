from datetime import date

from app.compliance.versions.ng_2026_1 import NG_2026_1
from app.domain.payroll.deadlines import (
    itf_deadline,
    nhf_deadline,
    nsitf_deadline,
    paye_deadline,
    pension_deadline,
)

RULES = NG_2026_1


def test_paye_deadline_is_10th_of_following_month() -> None:
    assert paye_deadline(date(2026, 1, 31), RULES.paye) == date(2026, 2, 10)


def test_paye_deadline_rolls_over_the_year() -> None:
    assert paye_deadline(date(2026, 12, 15), RULES.paye) == date(2027, 1, 10)


def test_nsitf_deadline_is_16th_of_following_month() -> None:
    assert nsitf_deadline(date(2026, 3, 1), RULES.nsitf) == date(2026, 4, 16)


def test_nhf_deadline_is_30_days_after_payment() -> None:
    assert nhf_deadline(date(2026, 1, 1), RULES.nhf) == date(2026, 1, 31)


def test_pension_deadline_skips_weekends() -> None:
    # Payment on Friday 2026-01-02. Hand-counted 7 working days, skipping
    # both weekends in between: Mon 5, Tue 6, Wed 7, Thu 8, Fri 9 (5 days),
    # then Mon 12, Tue 13 (2 more) -> due 2026-01-13.
    assert pension_deadline(date(2026, 1, 2), RULES.pension) == date(2026, 1, 13)


def test_pension_deadline_zero_working_days_is_same_day() -> None:
    assert pension_deadline(
        date(2026, 1, 2), RULES.pension.model_copy(update={"due_working_days_after_payment": 0})
    ) == date(2026, 1, 2)


def test_itf_deadline_is_1_april_the_following_year() -> None:
    assert itf_deadline(2026, RULES.itf) == date(2027, 4, 1)
