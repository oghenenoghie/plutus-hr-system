import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.membership import Role
from app.models.notification import Notification
from app.schemas.notifications import (
    NotificationBroadcast,
    NotificationOut,
    NotificationUnreadCount,
)
from app.services.notifications import broadcast_notification, mark_notification_read

router = APIRouter(prefix="/notifications", tags=["notifications"])

_BROADCAST = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


def _get_own_notification_or_404(
    db: Session, claims: TokenClaims, notification_id: uuid.UUID
) -> Notification:
    notification = db.get(Notification, notification_id)
    if notification is None or notification.account_id != claims.account_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="notification not found")
    return notification


@router.get("/me", response_model=list[NotificationOut])
def list_my_notifications(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(get_current_claims)
) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.account_id == claims.account_id)
            .order_by(Notification.created_at.desc())
        )
    )


@router.get("/me/unread-count", response_model=NotificationUnreadCount)
def my_unread_count(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(get_current_claims)
) -> NotificationUnreadCount:
    unread_count = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.account_id == claims.account_id, Notification.read_at.is_(None))
    )
    return NotificationUnreadCount(unread_count=unread_count or 0)


@router.post("/me/{notification_id}/read", response_model=NotificationOut)
def read_notification(
    notification_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> Notification:
    notification = _get_own_notification_or_404(db, claims, notification_id)
    mark_notification_read(db, notification)
    db.flush()
    return notification


@router.post("/me/read-all", status_code=status.HTTP_204_NO_CONTENT)
def read_all_notifications(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(get_current_claims)
) -> None:
    unread = db.scalars(
        select(Notification).where(
            Notification.account_id == claims.account_id, Notification.read_at.is_(None)
        )
    )
    now = datetime.now(UTC)
    for notification in unread:
        notification.read_at = now
        db.add(notification)
    db.flush()


@router.post(
    "/broadcast", response_model=list[NotificationOut], status_code=status.HTTP_201_CREATED
)
def broadcast(
    body: NotificationBroadcast,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_BROADCAST),
) -> list[Notification]:
    return broadcast_notification(db, org_id=claims.org_id, **body.model_dump())
