import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.membership import Membership, Role
from app.models.notification import Notification
from app.schemas.notifications import NotificationAudience

# Recipients for the "hr_admin" audience — Admin needs visibility into
# every broadcast it could otherwise send to everyone, HR Manager is the
# other role an announcement not meant for the whole company is for.
_HR_ADMIN_ROLES = (Role.ADMIN, Role.HR_MANAGER)


def broadcast_notification(
    db: Session,
    *,
    org_id: uuid.UUID,
    title: str,
    body: str | None = None,
    link: str | None = None,
    audience: NotificationAudience = "everyone",
) -> list[Notification]:
    """One notification per account holding a membership in this org (or,
    for the "hr_admin" audience, per account holding an Admin/HR Manager
    membership) — Membership carries no RLS (it's cross-tenant
    login-discovery data, per its own docstring), so this query sees every
    recipient regardless of the current tenant session's org context."""
    query = select(Membership.account_id).where(Membership.org_id == org_id)
    if audience == "hr_admin":
        query = query.where(Membership.role.in_(_HR_ADMIN_ROLES))
    account_ids = db.scalars(query).all()

    notifications = [
        Notification(org_id=org_id, account_id=account_id, title=title, body=body, link=link)
        for account_id in account_ids
    ]
    db.add_all(notifications)
    db.flush()
    return notifications


def mark_notification_read(db: Session, notification: Notification) -> Notification:
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        db.add(notification)
    return notification
