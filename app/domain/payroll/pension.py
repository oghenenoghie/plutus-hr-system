from app.compliance.models import PensionRule
from app.domain.money import apply_rate_ppm


def compute_pensionable_pay(basic_minor: int, housing_minor: int, transport_minor: int) -> int:
    """Pensionable emoluments are basic + housing + transport as actually
    constituted for this employee — never a derived percentage of gross
    (nigeria-statutory-compliance.md §2 caveat)."""
    for value, name in (
        (basic_minor, "basic_minor"),
        (housing_minor, "housing_minor"),
        (transport_minor, "transport_minor"),
    ):
        if value < 0:
            raise ValueError(f"{name} must not be negative")
    return basic_minor + housing_minor + transport_minor


def compute_pension_employee(pensionable_pay_minor: int, rule: PensionRule) -> int:
    if pensionable_pay_minor < 0:
        raise ValueError("pensionable_pay_minor must not be negative")
    return apply_rate_ppm(pensionable_pay_minor, rule.employee_rate_ppm)


def compute_pension_employer(pensionable_pay_minor: int, rule: PensionRule) -> int:
    """Employer cost, never an employee deduction (§3)."""
    if pensionable_pay_minor < 0:
        raise ValueError("pensionable_pay_minor must not be negative")
    return apply_rate_ppm(pensionable_pay_minor, rule.employer_rate_ppm)
