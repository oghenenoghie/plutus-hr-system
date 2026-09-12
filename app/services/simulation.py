import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.compliance.resolver import resolve_rule_version
from app.domain.payroll.frequency import PayFrequency
from app.domain.payroll.gross_up import (
    RegularPackageGrossUpResult,
    solve_lump_sum_gross_for_net_minor,
    solve_regular_package_gross_up,
)
from app.domain.payroll.loans import next_installment_amount
from app.domain.payroll.payslip import PayslipComputation, compute_payslip
from app.models.employee import Employee
from app.services.payroll import (
    active_loan,
    cumulative_totals_before,
    outstanding_loan_balance,
    tax_year_start,
)

_COUNTRY = "NG"  # same single-country assumption as app.services.payroll


@dataclass(frozen=True)
class SimulationInput:
    """Any field left as None falls back to the employee's current stored
    value — so a caller only needs to specify what they're changing."""

    period_end: date
    basic_minor: int | None = None
    housing_minor: int | None = None
    transport_minor: int | None = None
    other_earnings_minor: int | None = None
    annual_rent_paid_minor: int | None = None
    frequency: PayFrequency | None = None
    include_active_loan_deduction: bool = True


def simulate_payslip(
    db: Session, *, employee: Employee, scenario: SimulationInput
) -> PayslipComputation:
    """What a payslip would look like under a hypothetical change (a raise,
    a new pay frequency, ...), without persisting anything: no PayRun,
    Payslip, LedgerEntry or LoanRepayment is created. Cumulative PAYE
    inputs are seeded from the employee's real payslip history so far this
    tax year, exactly as a real run would — the only thing hypothetical is
    this one period's components. A caller re-simulating a period that
    already has a real payslip will see the hypothetical figures for that
    period, not a match to what actually happened.
    """
    rules = resolve_rule_version(_COUNTRY, scenario.period_end)
    year_start = tax_year_start(scenario.period_end)
    (
        cumulative_gross_before,
        cumulative_pension_employee_before,
        cumulative_nhf_before,
        cumulative_paye_before,
        periods_elapsed_before,
    ) = cumulative_totals_before(db, employee.id, year_start)

    loan_deduction_minor = 0
    if scenario.include_active_loan_deduction:
        loan = active_loan(db, employee.id)
        if loan is not None:
            outstanding = outstanding_loan_balance(db, loan)
            if outstanding > 0:
                loan_deduction_minor = next_installment_amount(outstanding, loan.installment_minor)

    return compute_payslip(
        basic_minor=scenario.basic_minor
        if scenario.basic_minor is not None
        else employee.basic_minor,
        housing_minor=(
            scenario.housing_minor if scenario.housing_minor is not None else employee.housing_minor
        ),
        transport_minor=(
            scenario.transport_minor
            if scenario.transport_minor is not None
            else employee.transport_minor
        ),
        other_earnings_minor=(
            scenario.other_earnings_minor
            if scenario.other_earnings_minor is not None
            else employee.other_earnings_minor
        ),
        annual_rent_paid_minor=(
            scenario.annual_rent_paid_minor
            if scenario.annual_rent_paid_minor is not None
            else employee.annual_rent_paid_minor
        ),
        periods_elapsed_this_year=periods_elapsed_before + 1,
        frequency=scenario.frequency if scenario.frequency is not None else employee.pay_frequency,
        cumulative_gross_before_minor=cumulative_gross_before,
        cumulative_pension_employee_before_minor=cumulative_pension_employee_before,
        cumulative_nhf_before_minor=cumulative_nhf_before,
        cumulative_paye_withheld_before_minor=cumulative_paye_before,
        rules=rules,
        loan_deduction_minor=loan_deduction_minor,
    )


@dataclass(frozen=True)
class PayRunSimulationResult:
    by_employee_id: dict[uuid.UUID, PayslipComputation]

    @property
    def total_gross_minor(self) -> int:
        return sum(c.gross_minor for c in self.by_employee_id.values())

    @property
    def total_employer_cost_minor(self) -> int:
        """Gross + employer pension — the full cost to the org, not just
        take-home pay (employer pension is never an employee deduction)."""
        return sum(c.gross_minor + c.pension_employer_minor for c in self.by_employee_id.values())

    @property
    def total_net_minor(self) -> int:
        return sum(c.net_pay_minor for c in self.by_employee_id.values())


def simulate_pay_run(
    db: Session,
    *,
    employees: list[Employee],
    period_end: date,
    overrides_by_employee_id: dict[uuid.UUID, SimulationInput] | None = None,
) -> PayRunSimulationResult:
    """The team-wide version: 'what would this pay run cost if we gave
    everyone a 10% raise' or 'what if we hired these three people'. Each
    employee not named in overrides_by_employee_id is simulated at their
    current stored pay with no change.
    """
    overrides = overrides_by_employee_id or {}
    results: dict[uuid.UUID, PayslipComputation] = {}
    for employee in employees:
        scenario = overrides.get(employee.id, SimulationInput(period_end=period_end))
        results[employee.id] = simulate_payslip(db, employee=employee, scenario=scenario)
    return PayRunSimulationResult(by_employee_id=results)


def solve_lump_sum_gross_up(
    db: Session, *, employee: Employee, period_end: date, target_net_minor: int
) -> int:
    """The minimal one-off lump-sum gross (bonus, arrears, ...) whose own
    net contribution is at least target_net_minor, seeded from the
    employee's real cumulative PAYE history so far this tax year — same
    inputs simulate_payslip uses, nothing persisted."""
    rules = resolve_rule_version(_COUNTRY, period_end)
    year_start = tax_year_start(period_end)
    (
        cumulative_gross_before,
        cumulative_pension_employee_before,
        cumulative_nhf_before,
        cumulative_paye_before,
        periods_elapsed_before,
    ) = cumulative_totals_before(db, employee.id, year_start)

    return solve_lump_sum_gross_for_net_minor(
        target_net_minor=target_net_minor,
        basic_minor=employee.basic_minor,
        housing_minor=employee.housing_minor,
        transport_minor=employee.transport_minor,
        other_earnings_minor=employee.other_earnings_minor,
        annual_rent_paid_minor=employee.annual_rent_paid_minor,
        periods_elapsed_this_year=periods_elapsed_before + 1,
        frequency=employee.pay_frequency,
        cumulative_gross_before_minor=cumulative_gross_before,
        cumulative_pension_employee_before_minor=cumulative_pension_employee_before,
        cumulative_nhf_before_minor=cumulative_nhf_before,
        cumulative_paye_withheld_before_minor=cumulative_paye_before,
        rules=rules,
    )


def solve_package_gross_up(
    db: Session, *, employee: Employee, period_end: date, target_net_minor: int
) -> RegularPackageGrossUpResult:
    """The minimal basic/housing/transport package (scaled from the
    employee's current ratio) whose net pay is at least target_net_minor —
    for 'pay this employee X net every period' negotiations. Does not
    persist anything; a caller applying the result writes the returned
    basic/housing/transport back onto the employee record itself."""
    rules = resolve_rule_version(_COUNTRY, period_end)
    year_start = tax_year_start(period_end)
    (
        cumulative_gross_before,
        cumulative_pension_employee_before,
        cumulative_nhf_before,
        cumulative_paye_before,
        periods_elapsed_before,
    ) = cumulative_totals_before(db, employee.id, year_start)

    loan = active_loan(db, employee.id)
    loan_deduction_minor = 0
    if loan is not None:
        outstanding = outstanding_loan_balance(db, loan)
        if outstanding > 0:
            loan_deduction_minor = next_installment_amount(outstanding, loan.installment_minor)

    return solve_regular_package_gross_up(
        target_net_minor=target_net_minor,
        current_basic_minor=employee.basic_minor,
        current_housing_minor=employee.housing_minor,
        current_transport_minor=employee.transport_minor,
        other_earnings_minor=employee.other_earnings_minor,
        annual_rent_paid_minor=employee.annual_rent_paid_minor,
        periods_elapsed_this_year=periods_elapsed_before + 1,
        frequency=employee.pay_frequency,
        cumulative_gross_before_minor=cumulative_gross_before,
        cumulative_pension_employee_before_minor=cumulative_pension_employee_before,
        cumulative_nhf_before_minor=cumulative_nhf_before,
        cumulative_paye_withheld_before_minor=cumulative_paye_before,
        rules=rules,
        loan_deduction_minor=loan_deduction_minor,
    )
