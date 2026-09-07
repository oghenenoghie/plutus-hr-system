import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.api_key import ApiKey
from app.models.membership import Role
from app.schemas.api_keys import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from app.services.api_keys import register_api_key, revoke_api_key

router = APIRouter(prefix="/api-keys", tags=["integrations"])

_MANAGE = require_roles(Role.ADMIN)


def _get_api_key_or_404(db: Session, api_key_id: uuid.UUID) -> ApiKey:
    api_key = db.get(ApiKey, api_key_id)
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    return api_key


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
def create_api_key(
    body: ApiKeyCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> ApiKeyCreated:
    api_key, plaintext_key = register_api_key(db, org_id=claims.org_id, name=body.name)
    return ApiKeyCreated(key=plaintext_key, **ApiKeyOut.model_validate(api_key).model_dump())


@router.get("", response_model=list[ApiKeyOut])
def list_api_keys(
    db: Session = Depends(get_tenant_db), _claims: TokenClaims = Depends(_MANAGE)
) -> list[ApiKey]:
    return list(db.scalars(select(ApiKey)))


@router.post("/{api_key_id}/revoke", response_model=ApiKeyOut)
def revoke_key(
    api_key_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    _claims: TokenClaims = Depends(_MANAGE),
) -> ApiKey:
    api_key = _get_api_key_or_404(db, api_key_id)
    try:
        revoke_api_key(db, api_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.flush()
    return api_key
