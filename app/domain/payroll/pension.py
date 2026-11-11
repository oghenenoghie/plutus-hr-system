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


def pension_rule_for(
    rule: PensionRule, *, employee_rate_ppm: int | None, employer_rate_ppm: int | None
) -> PensionRule:
    """The pension rule one employee contributes under: the rule set's, or
    higher rates where their employer's scheme contributes more. The rule
    set's rates are statutory minimums (§3), so a lower rate is refused
    rather than quietly raised."""
    for rate, minimum, name in (
        (employee_rate_ppm, rule.employee_rate_ppm, "employee"),
        (employer_rate_ppm, rule.employer_rate_ppm, "employer"),
    ):
        if rate is None:
            continue
        if rate < minimum:
            raise ValueError(
                f"the {name} pension rate can't be below the statutory minimum "
                f"({minimum / 10_000:g}%)"
            )
        if rate > 1_000_000:
            raise ValueError(f"the {name} pension rate can't be more than 100%")
    if employee_rate_ppm is None and employer_rate_ppm is None:
        return rule
    return rule.model_copy(
        update={
            "employee_rate_ppm": employee_rate_ppm or rule.employee_rate_ppm,
            "employer_rate_ppm": employer_rate_ppm or rule.employer_rate_ppm,
        }
    )
