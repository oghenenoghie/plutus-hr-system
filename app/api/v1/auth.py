import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_claims, get_tenant_db, get_untenanted_db
from app.core.rate_limit import limiter
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
from app.models.employee_login_code import EmployeeLoginCode
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


def _resolve_account(db: Session, identifier: str) -> Account | None:
    """A work email always contains '@'; a login_code (core/security.py's
    _LOGIN_CODE_ALPHABET) never does, so that's enough to tell them apart.
    employee_login_codes carries no RLS (see its model docstring), so this
    lookup works under the untenanted session /auth/login runs in, before
    any org — and therefore any tenant_session — is known.
    """
    if "@" in identifier:
        return db.scalar(select(Account).where(Account.email == identifier))
    login_code_row = db.scalar(
        select(EmployeeLoginCode).where(EmployeeLoginCode.login_code == identifier)
    )
    if login_code_row is None:
        return None
    return db.get(Account, login_code_row.account_id)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(
    request: Request, body: LoginRequest, db: Session = Depends(get_untenanted_db)
) -> TokenResponse:
    account = _resolve_account(db, body.identifier)
    if (
        account is None
        or not account.is_active
        or not verify_password(body.password, account.password_hash)
    ):
        raise _authentication_error("invalid email/employee ID or password")

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
    # MFA is opt-in for every role (via /auth/totp/setup + /auth/totp/verify
    # from the account's own security settings) rather than mandated by
    # role — enforced here only for accounts that have actually turned it
    # on, never as a login precondition.
    if account.totp_enabled:
        if not body.totp_code:
            # Structured (not a plain string like every other login error)
            # so the frontend can tell "credentials were fine, now ask for
            # the authenticator code" apart from a real failure — it drives
            # the login form's email/password-first, MFA-second UI.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "totp_required",
                    "message": "enter your authenticator code to continue",
                },
            )
        if not verify_totp(account.totp_secret or "", body.totp_code):
            raise _authentication_error("invalid TOTP code")

    return TokenResponse(
        access_token=create_access_token(account.id, membership.org_id, role.value),
        refresh_token=create_refresh_token(account.id, membership.org_id, role.value),
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("20/minute")
def refresh(
    request: Request, body: RefreshRequest, db: Session = Depends(get_untenanted_db)
) -> TokenResponse:
    try:
        claims = decode_token(body.refresh_token, expected_type="refresh")
    except jwt.InvalidTokenError as exc:
        raise _authentication_error("invalid or expired refresh token") from exc

    # Re-derive role from the database rather than trusting the refresh
    # token's embedded claim: an admin changing this account's role (or
    # deactivating it) must take effect within one access-token lifetime,
    # not linger for the refresh token's whole 7-day window — silent
    # token refresh would otherwise keep minting tokens for a role the
    # account no longer holds.
    account = db.get(Account, claims.account_id)
    membership = db.scalar(
        select(Membership).where(
            Membership.account_id == claims.account_id, Membership.org_id == claims.org_id
        )
    )
    if account is None or not account.is_active or membership is None:
        raise _authentication_error("account or membership no longer valid")

    role = membership.role.value
    return TokenResponse(
        access_token=create_access_token(claims.account_id, claims.org_id, role),
        refresh_token=create_refresh_token(claims.account_id, claims.org_id, role),
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
    account = db.get(Account, claims.account_id)
    return MeResponse(
        account_id=claims.account_id,
        org_id=claims.org_id,
        role=claims.role,
        org_name=org.name,
        mfa_enabled=account.totp_enabled if account is not None else False,
    )
