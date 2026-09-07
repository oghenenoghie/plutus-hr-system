import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID | None
    role: str | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    event_metadata: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}
