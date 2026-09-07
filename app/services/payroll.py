import uuid
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.resolver import resolve_rule_version
from app.domain.payroll.payslip import compute_payslip
from app.domain.payroll.postings import build_payslip_postings
from app.domain.payroll.tin import ensure_tin_present
from app.models.employee import Employee
from app.models.ledger import LedgerEntry
from app.models.pay_run import PayRun, PayRunStatus
from app.models.payslip import Payslip

# Single-country assumption for this phase — Nigeria is the only rule set
# that exists (app/compliance/versions/). Revisit once Organisation carries
# a country once a second country's rule set lands (see the skill's
# pan-African guardrail against hardcoding Nigeria assumptions elsewhere).
_COUNTRY = "NG"


def _tax_year_start(period_end: date) -> date:
    return date(period_end.year, 1, 1)


def _cumulative_totals_before(
    db: Session, employee_id: uuid.UUID, tax_year_start: date
) -> tuple[int, int, int, int, int]:
    prior = db.scalars(
        select(Payslip)
        .where(Payslip.employee_id == employee_id)
        .where(Payslip.period_end >= tax_year_start)
        .order_by(Payslip.period_end)
    ).all()
    return (
        sum(p.gross_minor for p in prior),
        sum(p.pension_employee_minor for p in prior),
        sum(p.nhf_minor for p in prior),
        sum(p.paye_minor for p in prior),
        len(prior),
    )


def process_employee_payslip(
    db: Session, *, org_id: uuid.UUID, pay_run: PayRun, employee: Employee
) -> Payslip:
    """Compute and persist one employee's payslip for a pay run, plus its
    balanced ledger postings. Raises MissingTinError (never silently skips)
    if the employee has no valid TIN — the caller's transaction (a
    tenant_session) rolls back on that exception, so no partial run persists.
    """
    ensure_tin_present(employee.tin)

    rules = resolve_rule_version(_COUNTRY, pay_run.period_end)
    tax_year_start = _tax_year_start(pay_run.period_end)
    (
        cumulative_gross_before,
        cumulative_pension_employee_before,
        cumulative_nhf_before,
        cumulative_paye_before,
        periods_elapsed_before,
    ) = _cumulative_totals_before(db, employee.id, tax_year_start)

    computation = compute_payslip(
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

    payslip = Payslip(
        org_id=org_id,
        pay_run_id=pay_run.id,
        employee_id=employee.id,
        period_start=pay_run.period_start,
        period_end=pay_run.period_end,
        gross_minor=computation.gross_minor,
        pensionable_pay_minor=computation.pensionable_pay_minor,
        pension_employee_minor=computation.pension_employee_minor,
        pension_employer_minor=computation.pension_employer_minor,
        nhf_minor=computation.nhf_minor,
        paye_minor=computation.paye_minor,
        net_minor=computation.net_pay_minor,
        cumulative_chargeable_income_minor=computation.cumulative_chargeable_income_minor,
        rule_version_id=rules.id,
        derivation={
            "inputs": {
                "basic_minor": employee.basic_minor,
                "housing_minor": employee.housing_minor,
                "transport_minor": employee.transport_minor,
                "other_earnings_minor": employee.other_earnings_minor,
                "annual_rent_paid_minor": employee.annual_rent_paid_minor,
                "periods_elapsed_this_year": periods_elapsed_before + 1,
                "frequency": employee.pay_frequency.value,
                "cumulative_gross_before_minor": cumulative_gross_before,
                "cumulative_pension_employee_before_minor": cumulative_pension_employee_before,
                "cumulative_nhf_before_minor": cumulative_nhf_before,
                "cumulative_paye_withheld_before_minor": cumulative_paye_before,
                "rule_version_id": rules.id,
            },
            "outputs": asdict(computation),
        },
    )
    db.add(payslip)

    journal_entry_id = uuid.uuid4()
    for posting in build_payslip_postings(computation):
        db.add(
            LedgerEntry(
                org_id=org_id,
                journal_entry_id=journal_entry_id,
                pay_run_id=pay_run.id,
                employee_id=employee.id,
                account=posting.account,
                debit_minor=posting.debit_minor,
                credit_minor=posting.credit_minor,
                description=f"payslip for {employee.employee_number}, {pay_run.period_start}–{pay_run.period_end}",
            )
        )

    return payslip


def run_pay_run(
    db: Session, *, org_id: uuid.UUID, pay_run: PayRun, employees: Sequence[Employee]
) -> PayRun:
    """Process every employee in a pay run. The whole run is one
    transaction (the caller's tenant_session): a single missing TIN or
    computation error rolls back every payslip and ledger entry the run
    would otherwise have created — never a partially-processed run.
    """
    pay_run.status = PayRunStatus.PROCESSING
    db.add(pay_run)

    payslips = [
        process_employee_payslip(db, org_id=org_id, pay_run=pay_run, employee=employee)
        for employee in employees
    ]

    pay_run.employee_count = len(payslips)
    pay_run.gross_minor = sum(p.gross_minor for p in payslips)
    pay_run.net_minor = sum(p.net_minor for p in payslips)
    pay_run.rule_version_id = payslips[0].rule_version_id if payslips else None
    pay_run.status = PayRunStatus.COMPLETED
    db.add(pay_run)
    return pay_run
