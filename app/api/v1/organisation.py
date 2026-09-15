from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.membership import Role
from app.models.organisation import Organisation
from app.schemas.organisation import OrganisationOut, OrganisationUpdate
from app.services.organisation import get_organisation, update_organisation

router = APIRouter(prefix="/organisation", tags=["organisation"])

_MANAGE = require_roles(Role.ADMIN)


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
