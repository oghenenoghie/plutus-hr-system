import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.domain.permissions import Permission
from app.models.membership import Membership, Role
from app.schemas.permissions import EffectivePermissionsOut, PermissionOverrideRequest
from app.services.permissions import (
    clear_permission_override,
    effective_permissions,
    set_permission_override,
)

router = APIRouter(prefix="/memberships", tags=["permissions"])

_MANAGE = require_roles(Role.ADMIN)


def _get_membership_or_404(db: Session, org_id: uuid.UUID, membership_id: uuid.UUID) -> Membership:
    """Membership carries no RLS of its own (it's pre-tenant-session
    login-discovery data — see its docstring), so this filters by org_id
    explicitly rather than relying on the session's tenant scoping to
    prevent one org's admin from reaching another org's membership."""
    membership = db.scalar(
        select(Membership).where(Membership.id == membership_id, Membership.org_id == org_id)
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="membership not found")
    return membership


@router.get("/{membership_id}/permissions", response_model=EffectivePermissionsOut)
def get_effective_permissions(
    membership_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> EffectivePermissionsOut:
    membership = _get_membership_or_404(db, claims.org_id, membership_id)
    permissions = effective_permissions(db, membership)
    return EffectivePermissionsOut(
        membership_id=membership.id,
        role=membership.role.value,
        permissions=sorted(permissions, key=lambda p: p.value),
    )


@router.put("/{membership_id}/permissions/override", response_model=EffectivePermissionsOut)
def put_permission_override(
    membership_id: uuid.UUID,
    body: PermissionOverrideRequest,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> EffectivePermissionsOut:
    membership = _get_membership_or_404(db, claims.org_id, membership_id)
    set_permission_override(
        db,
        membership,
        permission=body.permission,
        granted=body.granted,
        granted_by=claims.account_id,
    )
    permissions = effective_permissions(db, membership)
    return EffectivePermissionsOut(
        membership_id=membership.id,
        role=membership.role.value,
        permissions=sorted(permissions, key=lambda p: p.value),
    )


@router.delete(
    "/{membership_id}/permissions/override/{permission}",
    response_model=EffectivePermissionsOut,
)
def delete_permission_override(
    membership_id: uuid.UUID,
    permission: Permission,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> EffectivePermissionsOut:
    membership = _get_membership_or_404(db, claims.org_id, membership_id)
    clear_permission_override(db, membership, permission=permission)
    permissions = effective_permissions(db, membership)
    return EffectivePermissionsOut(
        membership_id=membership.id,
        role=membership.role.value,
        permissions=sorted(permissions, key=lambda p: p.value),
    )
