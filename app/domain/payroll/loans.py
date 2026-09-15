from datetime import date

# Employer policy defaults, not statutory figures — nothing in the
# compliance reference specifies a minimum tenure or a loan-to-pay ratio
# for an employee loan (same reasoning as interest itself, see Loan's
# docstring). Adjust here if an org's actual policy differs.
_MIN_TENURE_DAYS = 90
_MAX_PRINCIPAL_TO_MONTHLY_PAY_MULTIPLE = 3


class LoanEligibilityError(ValueError):
    """Raised when a requested loan fails employer eligibility policy —
    always a 400, never a 500, so the API layer can pass the message
    straight through like any other ValueError from this package."""


def check_loan_eligibility(
    *, hire_date: date, start_date: date, principal_minor: int, monthly_pay_minor: int
) -> None:
    tenure_days = (start_date - hire_date).days
    if tenure_days < _MIN_TENURE_DAYS:
        raise LoanEligibilityError(
            f"employee needs at least {_MIN_TENURE_DAYS} days' tenure before a loan "
            f"start date (has {max(tenure_days, 0)})"
        )
    max_principal_minor = monthly_pay_minor * _MAX_PRINCIPAL_TO_MONTHLY_PAY_MULTIPLE
    if principal_minor > max_principal_minor:
        raise LoanEligibilityError(
            f"principal exceeds {_MAX_PRINCIPAL_TO_MONTHLY_PAY_MULTIPLE}x monthly pay "
            f"({max_principal_minor} minor units)"
        )


def apply_flat_interest_minor(principal_minor: int, interest_rate_bps: int) -> int:
    """Total repayable under flat interest: a fixed percentage of
    principal added once over the full term — not compounding, not
    reducing-balance. The simplest convention for a small employee loan,
    and easy to verify by hand. interest_rate_bps is basis points (500 =
    5%), an employer policy choice (see Loan's docstring on interest) —
    never a statutory figure. 0 (the default) reproduces the previous
    interest-free behaviour exactly."""
    if principal_minor < 0:
        raise ValueError("principal_minor must not be negative")
    if interest_rate_bps < 0:
        raise ValueError("interest_rate_bps must not be negative")
    return principal_minor + (principal_minor * interest_rate_bps) // 10_000


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
