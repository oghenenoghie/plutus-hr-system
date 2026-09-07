import pytest

from app.domain.payroll.leave import compute_leave_balance


def test_leave_balance_subtracts_taken_from_entitlement() -> None:
    assert compute_leave_balance(entitlement_days=20, approved_days_taken=5) == 15


def test_leave_balance_floors_at_zero() -> None:
    assert compute_leave_balance(entitlement_days=10, approved_days_taken=15) == 0


def test_leave_balance_rejects_negative_inputs() -> None:
    with pytest.raises(ValueError):
        compute_leave_balance(entitlement_days=-1, approved_days_taken=0)
    with pytest.raises(ValueError):
        compute_leave_balance(entitlement_days=10, approved_days_taken=-1)
