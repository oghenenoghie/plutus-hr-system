"""Double-entry postings for an engine payslip and for payroll levies, with
the same shape as Nigeria's (app.domain.payroll.postings): gross pay and the
employer's contributions are debited as expense; every deduction, employer
contribution and the net pay are credited to what they're owed as. Debits
always equal credits:

    debits  = gross + employer contributions
    credits = employee contributions + income tax + employer contributions + net pay
            = gross + employer contributions, since net pay = gross
              - employee contributions - income tax

Lines on the same account are combined (for example an employee's and the
employer's pension both owed to the pension fund), and zero amounts are left
out.
"""

from collections.abc import Iterable

from app.compliance.engine.calculate import LineKind, PayslipResult, StatutoryLine
from app.domain.payroll.postings import Posting

GROSS_PAY_EXPENSE = "payroll_expense_gross"
NET_PAY_PAYABLE = "net_pay_payable"


def _combined(entries: Iterable[tuple[str, int]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for account, amount in entries:
        if amount:
            totals[account] = totals.get(account, 0) + amount
    return totals


def _expense_account(line: StatutoryLine) -> str:
    if not line.expense_account:  # rules.structural_problems requires one
        raise ValueError(f"{line.code} has no expense account")
    return line.expense_account


def build_payslip_postings(result: PayslipResult) -> tuple[Posting, ...]:
    employer_lines = [line for line in result.lines if line.kind is LineKind.EMPLOYER_CONTRIBUTION]
    debits = _combined(
        [(GROSS_PAY_EXPENSE, result.gross_minor)]
        + [(_expense_account(line), line.amount_minor) for line in employer_lines]
    )
    credits = _combined(
        [(line.liability_account, line.amount_minor) for line in result.lines]
        + [(NET_PAY_PAYABLE, result.net_pay_minor)]
    )
    return tuple(Posting(account, amount, 0) for account, amount in debits.items()) + tuple(
        Posting(account, 0, amount) for account, amount in credits.items()
    )


def build_levy_postings(lines: Iterable[StatutoryLine]) -> tuple[Posting, ...]:
    postings: list[Posting] = []
    for line in lines:
        if line.kind is not LineKind.PAYROLL_LEVY:
            raise ValueError(f"{line.code} isn't a payroll levy")
        if line.amount_minor:
            postings.append(Posting(_expense_account(line), line.amount_minor, 0))
            postings.append(Posting(line.liability_account, 0, line.amount_minor))
    return tuple(postings)
