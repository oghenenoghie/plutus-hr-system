from datetime import date

from app.domain.recurrence import RecurrenceFrequency, add_months, next_occurrence


def test_add_months_within_same_year() -> None:
    assert add_months(date(2026, 1, 15), 1) == date(2026, 2, 15)


def test_add_months_rolls_over_year() -> None:
    assert add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)


def test_add_months_clamps_to_shorter_month() -> None:
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_next_occurrence_monthly() -> None:
    assert next_occurrence(date(2026, 1, 1), RecurrenceFrequency.MONTHLY) == date(2026, 2, 1)


def test_next_occurrence_quarterly() -> None:
    assert next_occurrence(date(2026, 1, 1), RecurrenceFrequency.QUARTERLY) == date(2026, 4, 1)


def test_next_occurrence_annually() -> None:
    assert next_occurrence(date(2026, 1, 1), RecurrenceFrequency.ANNUALLY) == date(2027, 1, 1)
