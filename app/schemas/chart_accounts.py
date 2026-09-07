import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.chart_account import AccountType


class ChartAccountCreate(BaseModel):
    code: str
    name: str
    type: AccountType


class ChartAccountUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None


class ChartAccountOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    code: str
    name: str
    type: AccountType
    is_system: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
