import pytest

from app.domain.payroll.loans import compute_equal_installments, next_installment_amount


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
