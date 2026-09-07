import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.union_membership import UnionMembershipStatus


class UnionMembershipCreate(BaseModel):
    union_name: str
    monthly_dues_minor: int
    joined_date: date
    membership_number: str | None = None


class UnionMembershipUpdate(BaseModel):
    union_name: str | None = None
    membership_number: str | None = None
    monthly_dues_minor: int | None = None
    status: UnionMembershipStatus | None = None


class UnionMembershipTerminate(BaseModel):
    terminated_date: date


class UnionMembershipOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    employee_id: uuid.UUID
    union_name: str
    membership_number: str | None
    monthly_dues_minor: int
    status: UnionMembershipStatus
    joined_date: date
    terminated_date: date | None
    created_at: datetime

    model_config = {"from_attributes": True}
