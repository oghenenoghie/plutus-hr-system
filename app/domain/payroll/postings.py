from dataclasses import dataclass

from app.domain.payroll.payslip import PayslipComputation


@dataclass(frozen=True)
class Posting:
    account: str
    debit_minor: int
    credit_minor: int


def build_payslip_postings(computation: PayslipComputation) -> tuple[Posting, ...]:
    """Double-entry postings for one payslip. Debits (payroll expense —
    gross pay plus the employer's pension contribution, an employer cost
    never charged to the employee) always equal credits (every payable this
    posting set creates), by construction:

        debits  = gross + pension_employer
        credits = paye + (pension_employee + pension_employer) + nhf + net_pay
                = paye + pension_employee + pension_employer + nhf
                  + (gross - pension_employee - nhf - paye)
                = gross + pension_employer

    Zero-amount lines are omitted; omitting a line that contributes nothing
    to either side cannot break the balance.
    """
    postings: list[Posting] = [
        Posting("payroll_expense_gross", computation.gross_minor, 0),
    ]
    if computation.pension_employer_minor:
        postings.append(
            Posting("payroll_expense_employer_pension", computation.pension_employer_minor, 0)
        )
    if computation.paye_minor:
        postings.append(Posting("paye_payable", 0, computation.paye_minor))

    total_pension_payable = computation.pension_employee_minor + computation.pension_employer_minor
    if total_pension_payable:
        postings.append(Posting("pension_payable", 0, total_pension_payable))
    if computation.nhf_minor:
        postings.append(Posting("nhf_payable", 0, computation.nhf_minor))
    if computation.net_pay_minor:
        postings.append(Posting("net_pay_payable", 0, computation.net_pay_minor))

    return tuple(postings)
