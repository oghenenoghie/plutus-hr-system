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
    # Only ever populated on the creation response, never on the plain
    # listing — an ADMIN/PAYROLL_MANAGER account can't complete its own
    # first login without MFA already enabled (there's no bootstrap-token
    # endpoint for a brand new account to call totp/setup itself), so this
    # is generated eagerly here and handed back once, the same way a
    # provisioning flow hands over a one-time credential.
    totp_secret: str | None = None
    totp_provisioning_uri: str | None = None

    model_config = {"from_attributes": True}


class MembershipRoleUpdate(BaseModel):
    role: Role


class MembershipRoleUpdateOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    email: str
    role: str
    # Only populated when this change was the account's first move into
    # an MFA-required role — see change_membership_role's docstring.
    totp_secret: str | None = None
    totp_provisioning_uri: str | None = None

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
