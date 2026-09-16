from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.rate_limit import limiter
from app.core.security import TokenClaims, totp_provisioning_uri
from app.models.membership import Role
from app.models.organisation import Organisation
from app.schemas.organisation import (
    OrganisationOut,
    OrganisationSignupOut,
    OrganisationSignupRequest,
    OrganisationUpdate,
)
from app.services.organisation import get_organisation, signup_organisation, update_organisation

router = APIRouter(prefix="/organisation", tags=["organisation"])

_MANAGE = require_roles(Role.ADMIN)


@router.post("/signup", response_model=OrganisationSignupOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/hour")
def signup(request: Request, body: OrganisationSignupRequest) -> OrganisationSignupOut:
    """The only public, unauthenticated way a new company gets onto
    Plutus — everyone else (a second admin, an employee, any other role)
    is invited from inside an org that already exists, via /memberships
    or /employees/{id}/create-login."""
    try:
        org, membership, totp_secret = signup_organisation(
            org_name=body.org_name,
            admin_email=body.admin_email,
            admin_password=body.admin_password,
        )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an account with this email already exists",
        ) from exc
    return OrganisationSignupOut(
        org_id=org.id,
        account_id=membership.account_id,
        email=body.admin_email,
        totp_secret=totp_secret,
        totp_provisioning_uri=totp_provisioning_uri(totp_secret, body.admin_email),
    )


@router.get("", response_model=OrganisationOut)
def get_my_organisation(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_MANAGE)
) -> Organisation:
    return get_organisation(db, claims.org_id)


@router.put("", response_model=OrganisationOut)
def update_my_organisation(
    body: OrganisationUpdate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> Organisation:
    org = get_organisation(db, claims.org_id)
    return update_organisation(db, org, **body.model_dump())
