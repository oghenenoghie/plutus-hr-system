from datetime import date

import pytest

from app.domain.payroll.loans import (
    LoanEligibilityError,
    apply_flat_interest_minor,
    check_loan_eligibility,
    compute_equal_installments,
    next_installment_amount,
)


def test_equal_installments_sum_exactly_to_principal() -> None:
    installments = compute_equal_installments(100_000_00, 3)
    assert sum(installments) == 100_000_00
    # 100,000.00 / 3 = 33,333.33... — the remainder lands on the last one.
    assert installments == (33_333_33, 33_333_33, 33_333_34)


def test_equal_installments_evenly_divisible() -> None:
    assert compute_equal_installments(90_000_00, 3) == (30_000_00, 30_000_00, 30_000_00)


def test_equal_installments_rejects_non_positive_count() -> None:
    with pytest.raises(ValueError):
        compute_equal_installments(100_000_00, 0)


def test_next_installment_capped_at_outstanding_balance() -> None:
    assert (
        next_installment_amount(outstanding_minor=5_000_00, scheduled_installment_minor=30_000_00)
        == 5_000_00
    )
    assert (
        next_installment_amount(outstanding_minor=50_000_00, scheduled_installment_minor=30_000_00)
        == 30_000_00
    )


def test_flat_interest_zero_rate_returns_principal_unchanged() -> None:
    assert apply_flat_interest_minor(100_000_00, 0) == 100_000_00


def test_flat_interest_applies_once_over_the_full_term() -> None:
    # 5% (500 bps) of 100,000.00 = 5,000.00.
    assert apply_flat_interest_minor(100_000_00, 500) == 105_000_00


def test_flat_interest_rejects_negative_rate() -> None:
    with pytest.raises(ValueError):
        apply_flat_interest_minor(100_000_00, -1)


def test_eligibility_rejects_insufficient_tenure() -> None:
    with pytest.raises(LoanEligibilityError):
        check_loan_eligibility(
            hire_date=date(2026, 1, 1),
            start_date=date(2026, 2, 1),  # 31 days < 90
            principal_minor=10_000_00,
            monthly_pay_minor=500_000_00,
        )


def test_eligibility_rejects_principal_over_cap() -> None:
    with pytest.raises(LoanEligibilityError):
        check_loan_eligibility(
            hire_date=date(2025, 1, 1),
            start_date=date(2026, 1, 1),
            principal_minor=2_000_000_00,  # > 3x 500,000.00 monthly pay
            monthly_pay_minor=500_000_00,
        )


def test_eligibility_passes_within_tenure_and_principal_cap() -> None:
    check_loan_eligibility(
        hire_date=date(2025, 1, 1),
        start_date=date(2026, 1, 1),
        principal_minor=1_500_000_00,  # exactly 3x monthly pay
        monthly_pay_minor=500_000_00,
    )
