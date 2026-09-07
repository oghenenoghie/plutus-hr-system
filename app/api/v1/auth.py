import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_tenant_db, get_untenanted_db
from app.core.security import (
    TokenClaims,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_totp_secret,
    totp_provisioning_uri,
    verify_password,
    verify_totp,
)
from app.models import Account, Membership, Organisation, Role
from app.models.membership import MFA_REQUIRED_ROLES
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    RefreshRequest,
    TokenResponse,
    TotpSetupResponse,
    TotpVerifyRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _authentication_error(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_untenanted_db)) -> TokenResponse:
    account = db.scalar(select(Account).where(Account.email == body.email))
    if (
        account is None
        or not account.is_active
        or not verify_password(body.password, account.password_hash)
    ):
        raise _authentication_error("invalid email or password")

    memberships = list(db.scalars(select(Membership).where(Membership.account_id == account.id)))
    if not memberships:
        raise _authentication_error("account has no organisation membership")

    if body.org_id is not None:
        membership = next((m for m in memberships if m.org_id == body.org_id), None)
        if membership is None:
            raise _authentication_error("account is not a member of that organisation")
    elif len(memberships) == 1:
        membership = memberships[0]
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="account belongs to multiple organisations; specify org_id",
        )

    role = Role(membership.role)
    if role in MFA_REQUIRED_ROLES:
        if not account.totp_enabled:
            raise _authentication_error("TOTP MFA must be enabled for this role before logging in")
        if not body.totp_code or not verify_totp(account.totp_secret or "", body.totp_code):
            raise _authentication_error("missing or invalid TOTP code")

    return TokenResponse(
        access_token=create_access_token(account.id, membership.org_id, role.value),
        refresh_token=create_refresh_token(account.id, membership.org_id, role.value),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest) -> TokenResponse:
    try:
        claims = decode_token(body.refresh_token, expected_type="refresh")
    except jwt.InvalidTokenError as exc:
        raise _authentication_error("invalid or expired refresh token") from exc

    return TokenResponse(
        access_token=create_access_token(claims.account_id, claims.org_id, claims.role),
        refresh_token=create_refresh_token(claims.account_id, claims.org_id, claims.role),
    )


@router.post("/totp/setup", response_model=TotpSetupResponse)
def totp_setup(
    claims: TokenClaims = Depends(get_current_claims), db: Session = Depends(get_untenanted_db)
) -> TotpSetupResponse:
    account = db.get(Account, claims.account_id)
    if account is None:
        raise _authentication_error("account not found")

    secret = generate_totp_secret()
    account.totp_secret = secret
    account.totp_enabled = False
    db.add(account)
    db.flush()

    return TotpSetupResponse(
        secret=secret, provisioning_uri=totp_provisioning_uri(secret, account.email)
    )


@router.post("/totp/verify", status_code=status.HTTP_204_NO_CONTENT)
def totp_verify(
    body: TotpVerifyRequest,
    claims: TokenClaims = Depends(get_current_claims),
    db: Session = Depends(get_untenanted_db),
) -> None:
    account = db.get(Account, claims.account_id)
    if account is None or not account.totp_secret:
        raise _authentication_error("no pending TOTP setup for this account")
    if not verify_totp(account.totp_secret, body.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid TOTP code")

    account.totp_enabled = True
    db.add(account)


@router.get("/me", response_model=MeResponse)
def me(
    claims: TokenClaims = Depends(get_current_claims), db: Session = Depends(get_tenant_db)
) -> MeResponse:
    org = db.get(Organisation, claims.org_id)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="organisation not visible"
        )
    return MeResponse(
        account_id=claims.account_id, org_id=claims.org_id, role=claims.role, org_name=org.name
    )
