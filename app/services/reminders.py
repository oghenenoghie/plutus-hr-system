import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.employee_lifecycle import LifecycleState
from app.models.account import Account
from app.models.approval import ApprovalInstance, ApprovalInstanceStatus
from app.models.employee import Employee
from app.models.membership import Membership, Role
from app.models.notification import Notification
from app.services.dashboard import upcoming_deadlines
from app.services.email import send_email


@dataclass(frozen=True)
class RemindersSummary:
    deadline_count: int
    stale_approval_count: int
    expiring_contract_count: int
    notifications_created: list[Notification]


def _admin_recipients(db: Session, org_id: uuid.UUID) -> list[Account]:
    account_ids = db.scalars(
        select(Membership.account_id).where(
            Membership.org_id == org_id, Membership.role.in_((Role.ADMIN, Role.PAYROLL_MANAGER, Role.ACCOUNTANT))
        )
    ).all()
    if not account_ids:
        return []
    return list(db.scalars(select(Account).where(Account.id.in_(account_ids))))


def _stale_approval_requests(
    db: Session, org_id: uuid.UUID, *, as_of: date, stale_after_days: int
) -> list[ApprovalInstance]:
    cutoff = as_of - timedelta(days=stale_after_days)
    return list(
        db.scalars(
            select(ApprovalInstance).where(
                ApprovalInstance.org_id == org_id,
                ApprovalInstance.status == ApprovalInstanceStatus.PENDING,
                ApprovalInstance.created_at <= cutoff,
            )
        )
    )


def _expiring_contracts(
    db: Session, org_id: uuid.UUID, *, as_of: date, within_days: int
) -> list[Employee]:
    """Active employees whose contract_end_date falls within the window
    (including already lapsed ones) and haven't been alerted on yet —
    contract_expiry_notified makes this a one-time alert per end date
    rather than a daily nag; update_employee clears the flag on a renewal
    (a changed contract_end_date) so the new date gets its own alert."""
    horizon = as_of + timedelta(days=within_days)
    return list(
        db.scalars(
            select(Employee).where(
                Employee.org_id == org_id,
                Employee.lifecycle_state == LifecycleState.ACTIVE,
                Employee.contract_end_date.is_not(None),
                Employee.contract_end_date <= horizon,
                Employee.contract_expiry_notified.is_(False),
            )
        )
    )


def run_reminder_job(
    db: Session, org_id: uuid.UUID, *, as_of: date, stale_after_days: int = 3
) -> RemindersSummary:
    """Scans for three things an org's admins need to know about without
    checking manually: statutory deadlines coming up (or already missed),
    ApprovalRequests that have sat PENDING too long, and fixed-term/
    consultant contracts expiring soon. When there's anything to report,
    notifies every ADMIN/PAYROLL_MANAGER account in-app (always) and by
    email (best-effort — a misconfigured or down email provider must not
    stop the in-app notification, which is the one guaranteed channel).
    """
    deadlines = upcoming_deadlines(db, org_id, on=as_of)
    stale_approvals = _stale_approval_requests(
        db, org_id, as_of=as_of, stale_after_days=stale_after_days
    )
    expiring_contracts = _expiring_contracts(db, org_id, as_of=as_of, within_days=30)

    notifications: list[Notification] = []
    if deadlines or stale_approvals or expiring_contracts:
        title = "Deadlines and approvals need attention"
        body_lines = []
        if deadlines:
            body_lines.append(f"{len(deadlines)} statutory deadline(s) due within 30 days.")
        if stale_approvals:
            body_lines.append(
                f"{len(stale_approvals)} approval request(s) pending for over "
                f"{stale_after_days} day(s)."
            )
        if expiring_contracts:
            body_lines.append(
                f"{len(expiring_contracts)} employee contract(s) expiring within 30 days."
            )
        body = " ".join(body_lines)

        for account in _admin_recipients(db, org_id):
            notification = Notification(
                org_id=org_id, account_id=account.id, title=title, body=body
            )
            db.add(notification)
            notifications.append(notification)
            try:
                send_email(to=account.email, subject=title, html_body=f"<p>{body}</p>")
            except RuntimeError:
                pass

        for employee in expiring_contracts:
            employee.contract_expiry_notified = True
            db.add(employee)

        db.flush()

    return RemindersSummary(
        deadline_count=len(deadlines),
        stale_approval_count=len(stale_approvals),
        expiring_contract_count=len(expiring_contracts),
        notifications_created=notifications,
    )
