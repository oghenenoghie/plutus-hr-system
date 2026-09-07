import uuid
from datetime import datetime

from pydantic import BaseModel


class NotificationBroadcast(BaseModel):
    title: str
    body: str | None = None
    link: str | None = None


class NotificationOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    account_id: uuid.UUID
    title: str
    body: str | None
    link: str | None
    read_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationUnreadCount(BaseModel):
    unread_count: int
