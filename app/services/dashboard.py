import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.employee import Employee, LifecycleState
from app.models.expense import Expense, ExpenseStatus
from app.models.leave import LeaveRequest, LeaveStatus
from app.models.pay_run import PayRun, PayRunStatus
from app.models.statutory_liability import LiabilityStatus, StatutoryLiability

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

    return OrgSummary(
        active_employee_count=active_employee_count,
        last_completed_pay_run=last_completed_pay_run,
        outstanding_liability_minor=outstanding_liability_minor,
        pending_leave_request_count=pending_leave_request_count,
        pending_expense_count=pending_expense_count,
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
