import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.domain.permissions import Permission
from app.models.membership import Role


class MembershipOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    email: str
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MembershipCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    role: Role


class MembershipCreateOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    email: str
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PermissionOverrideRequest(BaseModel):
    permission: Permission
    granted: bool


class MembershipPermissionOverrideOut(BaseModel):
    id: uuid.UUID
    membership_id: uuid.UUID
    permission: Permission
    granted: bool
    granted_by: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class EffectivePermissionsOut(BaseModel):
    membership_id: uuid.UUID
    role: str
    permissions: list[Permission]
