import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.chart_account import AccountType, ChartAccount
from app.models.employee import Employee, LifecycleState
from app.models.expense import Expense, ExpenseStatus
from app.models.leave import LeaveRequest, LeaveStatus
from app.models.ledger import LedgerEntry
from app.models.pay_run import PayRun, PayRunStatus
from app.models.statutory_liability import LiabilityStatus, StatutoryLiability

# The three chart-of-accounts codes seeded by every accounting-suite phase
# (see services/chart_accounts.py::DEFAULT_ACCOUNTS) that summarize an org's
# accounting position at a glance. Missing entirely (chart of accounts never
# seeded) reads as zero rather than an error — this is a summary tile, not
# a statement.
_ACCOUNTING_SUMMARY_CODES = ("cash", "accounts_payable", "accounts_receivable")


def _accounting_balances(db: Session, org_id: uuid.UUID) -> dict[str, int]:
    accounts = {
        account.code: account
        for account in db.scalars(
            select(ChartAccount).where(
                ChartAccount.org_id == org_id, ChartAccount.code.in_(_ACCOUNTING_SUMMARY_CODES)
            )
        )
    }
    if not accounts:
        return dict.fromkeys(_ACCOUNTING_SUMMARY_CODES, 0)

    totals: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
    for entry in db.scalars(
        select(LedgerEntry).where(
            LedgerEntry.org_id == org_id, LedgerEntry.account.in_(accounts.keys())
        )
    ):
        debit, credit = totals[entry.account]
        totals[entry.account] = (debit + entry.debit_minor, credit + entry.credit_minor)

    balances = {}
    for code in _ACCOUNTING_SUMMARY_CODES:
        account = accounts.get(code)
        debit, credit = totals.get(code, (0, 0))
        if account is None:
            balances[code] = 0
        elif account.type == AccountType.LIABILITY:
            balances[code] = credit - debit
        else:
            balances[code] = debit - credit
    return balances


# No Arq/Redis/Resend infrastructure exists in this repo yet to build a real
# async alerting pipeline (scheduled jobs, email delivery) against — that's
# real infra this environment can't provision or test. "Deadline alerting"
# is delivered here as a pull-based query instead: every statutory
# liability not yet remitted, ordered by how soon it's due. A caller (a
# dashboard screen, or a future scheduled job once Arq/Resend exist) polls
# this rather than waiting on a push notification that doesn't exist yet.


@dataclass(frozen=True)
class OrgSummary:
    active_employee_count: int
    last_completed_pay_run: PayRun | None
    outstanding_liability_minor: int
    pending_leave_request_count: int
    pending_expense_count: int
    cash_balance_minor: int
    accounts_payable_minor: int
    accounts_receivable_minor: int


def org_summary(db: Session, org_id: uuid.UUID) -> OrgSummary:
    active_employee_count = (
        db.scalar(
            select(func.count())
            .select_from(Employee)
            .where(Employee.org_id == org_id, Employee.lifecycle_state == LifecycleState.ACTIVE)
        )
        or 0
    )

    last_completed_pay_run = db.scalar(
        select(PayRun)
        .where(PayRun.org_id == org_id, PayRun.status == PayRunStatus.COMPLETED)
        .order_by(PayRun.period_end.desc())
        .limit(1)
    )

    outstanding_liability_minor = int(
        db.scalar(
            select(func.coalesce(func.sum(StatutoryLiability.amount_minor), 0)).where(
                StatutoryLiability.org_id == org_id,
                StatutoryLiability.status != LiabilityStatus.REMITTED,
            )
        )
        or 0
    )

    pending_leave_request_count = (
        db.scalar(
            select(func.count())
            .select_from(LeaveRequest)
            .where(LeaveRequest.org_id == org_id, LeaveRequest.status == LeaveStatus.PENDING)
        )
        or 0
    )

    pending_expense_count = (
        db.scalar(
            select(func.count())
            .select_from(Expense)
            .where(Expense.org_id == org_id, Expense.status == ExpenseStatus.PENDING)
        )
        or 0
    )

    accounting_balances = _accounting_balances(db, org_id)

    return OrgSummary(
        active_employee_count=active_employee_count,
        last_completed_pay_run=last_completed_pay_run,
        outstanding_liability_minor=outstanding_liability_minor,
        pending_leave_request_count=pending_leave_request_count,
        pending_expense_count=pending_expense_count,
        cash_balance_minor=accounting_balances["cash"],
        accounts_payable_minor=accounting_balances["accounts_payable"],
        accounts_receivable_minor=accounting_balances["accounts_receivable"],
    )


def upcoming_deadlines(
    db: Session, org_id: uuid.UUID, *, on: date, within_days: int = 30
) -> list[StatutoryLiability]:
    """Every not-yet-remitted liability due within the window, earliest
    first — including anything already overdue (due_date < on), since a
    missed deadline is exactly what alerting exists to surface."""
    horizon = on + timedelta(days=within_days)
    return list(
        db.scalars(
            select(StatutoryLiability)
            .where(
                StatutoryLiability.org_id == org_id,
                StatutoryLiability.status != LiabilityStatus.REMITTED,
                StatutoryLiability.due_date <= horizon,
            )
            .order_by(StatutoryLiability.due_date)
        )
    )
