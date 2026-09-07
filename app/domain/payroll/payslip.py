from dataclasses import dataclass

from app.compliance.models import RuleVersion
from app.domain.payroll.frequency import PayFrequency, prorate_annual_amount
from app.domain.payroll.nhf import compute_nhf
from app.domain.payroll.paye import compute_chargeable_income, compute_incremental_paye
from app.domain.payroll.pension import (
    compute_pension_employee,
    compute_pension_employer,
    compute_pensionable_pay,
)
from app.domain.payroll.reliefs import compute_rent_relief


@dataclass(frozen=True)
class PayslipComputation:
    gross_minor: int
    pensionable_pay_minor: int
    pension_employee_minor: int
    pension_employer_minor: int
    nhf_minor: int
    cumulative_rent_relief_minor: int
    cumulative_chargeable_income_minor: int
    paye_minor: int
    net_pay_minor: int


def compute_payslip(
    *,
    basic_minor: int,
    housing_minor: int,
    transport_minor: int,
    other_earnings_minor: int,
    annual_rent_paid_minor: int,
    periods_elapsed_this_year: int,
    frequency: PayFrequency,
    cumulative_gross_before_minor: int,
    cumulative_pension_employee_before_minor: int,
    cumulative_nhf_before_minor: int,
    cumulative_paye_withheld_before_minor: int,
    rules: RuleVersion,
) -> PayslipComputation:
    """One period's payslip, computed via cumulative-annual PAYE: this
    period's tax is the tax owed on year-to-date chargeable income, less
    what's already been withheld — never a naive slice of this period alone
    (nigeria-statutory-compliance.md §1). Callers must call
    ensure_tin_present(employee.tin) before this — it is not checked here.

    Gross is deliberately not assumed equal to pensionable pay: real pay
    structures include earnings outside basic/housing/transport, and that
    coincidence must never be relied on (§2 caveat).
    """
    if other_earnings_minor < 0:
        raise ValueError("other_earnings_minor must not be negative")

    pensionable_pay_minor = compute_pensionable_pay(basic_minor, housing_minor, transport_minor)
    gross_minor = pensionable_pay_minor + other_earnings_minor

    pension_employee_minor = compute_pension_employee(pensionable_pay_minor, rules.pension)
    pension_employer_minor = compute_pension_employer(pensionable_pay_minor, rules.pension)
    nhf_minor = compute_nhf(basic_minor, rules.nhf)

    annual_rent_relief_minor = compute_rent_relief(annual_rent_paid_minor, rules.paye)
    cumulative_rent_relief_minor = prorate_annual_amount(
        annual_rent_relief_minor, periods_elapsed_this_year, frequency
    )

    cumulative_gross_after = cumulative_gross_before_minor + gross_minor
    cumulative_pension_employee_after = (
        cumulative_pension_employee_before_minor + pension_employee_minor
    )
    cumulative_nhf_after = cumulative_nhf_before_minor + nhf_minor

    cumulative_chargeable_income_minor = compute_chargeable_income(
        cumulative_gross_after,
        cumulative_pension_employee_after,
        cumulative_nhf_after,
        cumulative_rent_relief_minor,
    )

    paye_minor = compute_incremental_paye(
        cumulative_chargeable_income_minor, cumulative_paye_withheld_before_minor, rules.paye.bands
    )

    net_pay_minor = gross_minor - pension_employee_minor - nhf_minor - paye_minor
    if net_pay_minor < 0:
        raise ValueError("computed net pay is negative — check input components and rates")

    return PayslipComputation(
        gross_minor=gross_minor,
        pensionable_pay_minor=pensionable_pay_minor,
        pension_employee_minor=pension_employee_minor,
        pension_employer_minor=pension_employer_minor,
        nhf_minor=nhf_minor,
        cumulative_rent_relief_minor=cumulative_rent_relief_minor,
        cumulative_chargeable_income_minor=cumulative_chargeable_income_minor,
        paye_minor=paye_minor,
        net_pay_minor=net_pay_minor,
    )
