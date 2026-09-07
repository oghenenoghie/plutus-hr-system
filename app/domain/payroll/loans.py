def compute_equal_installments(principal_minor: int, num_installments: int) -> tuple[int, ...]:
    """Equal installments summing exactly to principal — the last one
    absorbs whatever remainder integer division leaves, so nothing is lost
    or invented at the boundary."""
    if principal_minor < 0:
        raise ValueError("principal_minor must not be negative")
    if num_installments <= 0:
        raise ValueError("num_installments must be positive")

    base = principal_minor // num_installments
    installments = [base] * num_installments
    installments[-1] += principal_minor - base * num_installments
    return tuple(installments)


def next_installment_amount(outstanding_minor: int, scheduled_installment_minor: int) -> int:
    """Never deduct more than what's actually still owed — the final
    installment on a loan may be smaller than the scheduled amount."""
    if outstanding_minor < 0:
        raise ValueError("outstanding_minor must not be negative")
    if scheduled_installment_minor < 0:
        raise ValueError("scheduled_installment_minor must not be negative")
    return min(outstanding_minor, scheduled_installment_minor)
