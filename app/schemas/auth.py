import uuid

from pydantic import BaseModel


class LoginRequest(BaseModel):
    # Either a work email or an employee's login_code — see
    # auth.py::_resolve_account for how the two are told apart. Deliberately
    # not EmailStr: a login_code isn't email-shaped, and validating it as
    # one would reject every code-based login before it's even checked.
    identifier: str
    password: str
    org_id: uuid.UUID | None = None
    totp_code: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class TotpSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class TotpVerifyRequest(BaseModel):
    code: str


class MeResponse(BaseModel):
    account_id: uuid.UUID
    org_id: uuid.UUID
    role: str
    org_name: str
