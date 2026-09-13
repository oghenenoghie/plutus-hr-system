import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.approval_workflow import ApprovalRequest, ApprovalRequestStatus
from app.models.membership import Membership, Role
from app.models.notification import Notification
from app.services.dashboard import upcoming_deadlines
from app.services.email import send_email


@dataclass(frozen=True)
class RemindersSummary:
    deadline_count: int
    stale_approval_count: int
    notifications_created: list[Notification]


def _admin_recipients(db: Session, org_id: uuid.UUID) -> list[Account]:
    account_ids = db.scalars(
        select(Membership.account_id).where(
            Membership.org_id == org_id, Membership.role.in_((Role.ADMIN, Role.PAYROLL_MANAGER))
        )
    ).all()
    if not account_ids:
        return []
    return list(db.scalars(select(Account).where(Account.id.in_(account_ids))))


def _stale_approval_requests(
    db: Session, org_id: uuid.UUID, *, as_of: date, stale_after_days: int
) -> list[ApprovalRequest]:
    cutoff = as_of - timedelta(days=stale_after_days)
    return list(
        db.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.org_id == org_id,
                ApprovalRequest.status == ApprovalRequestStatus.PENDING,
                ApprovalRequest.created_at <= cutoff,
            )
        )
    )


def run_reminder_job(
    db: Session, org_id: uuid.UUID, *, as_of: date, stale_after_days: int = 3
) -> RemindersSummary:
    """Scans for two things an org's admins need to know about without
    checking manually: statutory deadlines coming up (or already missed)
    and ApprovalRequests that have sat PENDING too long. When there's
    anything to report, notifies every ADMIN/PAYROLL_MANAGER account
    in-app (always) and by email (best-effort — a misconfigured or down
    email provider must not stop the in-app notification, which is the
    one guaranteed channel).
    """
    deadlines = upcoming_deadlines(db, org_id, on=as_of)
    stale_approvals = _stale_approval_requests(
        db, org_id, as_of=as_of, stale_after_days=stale_after_days
    )

    notifications: list[Notification] = []
    if deadlines or stale_approvals:
        title = "Deadlines and approvals need attention"
        body_lines = []
        if deadlines:
            body_lines.append(f"{len(deadlines)} statutory deadline(s) due within 30 days.")
        if stale_approvals:
            body_lines.append(
                f"{len(stale_approvals)} approval request(s) pending for over "
                f"{stale_after_days} day(s)."
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
        db.flush()

    return RemindersSummary(
        deadline_count=len(deadlines),
        stale_approval_count=len(stale_approvals),
        notifications_created=notifications,
    )
