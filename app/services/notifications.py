import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.membership import Membership
from app.models.notification import Notification


def broadcast_notification(
    db: Session,
    *,
    org_id: uuid.UUID,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> list[Notification]:
    """One notification per account holding a membership in this org —
    Membership carries no RLS (it's cross-tenant login-discovery data, per
    its own docstring), so this query sees every recipient regardless of
    the current tenant session's org context."""
    account_ids = db.scalars(select(Membership.account_id).where(Membership.org_id == org_id)).all()

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
