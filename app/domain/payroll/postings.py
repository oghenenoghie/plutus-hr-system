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
    posting set creates, plus the loan receivable recovered and any
    benefit cost recovered), by construction:

        debits  = gross + pension_employer
        credits = paye + (pension_employee + pension_employer) + nhf
                  + net_pay + loan_deduction + benefit_deduction
                  + union_dues_deduction
                = paye + pension_employee + pension_employer + nhf
                  + (gross - pension_employee - nhf - paye - loan_deduction
                     - benefit_deduction - union_dues_deduction)
                  + loan_deduction + benefit_deduction + union_dues_deduction
                = gross + pension_employer

    A loan repaid via payroll deduction reduces net pay (a liability) and,
    to balance, credits (reduces) the employee_loan_receivable asset by
    the same amount. A non-statutory benefit (health insurance, ...)
    deducted from net pay works the same way, recovering what the
    employer already covers for that benefit. Union dues withheld for a
    trade union are the same shape again, but with no employer cost of
    their own to recover — it's a flat pass-through owed to the union, not
    a statutory scheme. No cash changes hands beyond the smaller net pay
    in any of these three cases.

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
    if computation.loan_deduction_minor:
        postings.append(Posting("employee_loan_receivable", 0, computation.loan_deduction_minor))
    if computation.benefit_deduction_minor:
        postings.append(
            Posting("benefit_deductions_recovered", 0, computation.benefit_deduction_minor)
        )
    if computation.union_dues_deduction_minor:
        postings.append(Posting("union_dues_payable", 0, computation.union_dues_deduction_minor))
    if computation.net_pay_minor:
        postings.append(Posting("net_pay_payable", 0, computation.net_pay_minor))

    return tuple(postings)
