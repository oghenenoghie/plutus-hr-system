import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# "everyone" reaches every account with a membership in the org (the
# original behaviour); "hr_admin" narrows delivery to Admin and HR
# Manager, for broadcasts that aren't meant for the whole company.
NotificationAudience = Literal["everyone", "hr_admin"]


class NotificationBroadcast(BaseModel):
    title: str
    body: str | None = None
    link: str | None = None
    audience: NotificationAudience = "everyone"


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
