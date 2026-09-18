import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims, totp_provisioning_uri
from app.domain.permissions import Permission
from app.models.account import Account
from app.models.membership import Membership, Role
from app.schemas.permissions import (
    EffectivePermissionsOut,
    MembershipCreate,
    MembershipCreateOut,
    MembershipOut,
    MembershipRoleUpdate,
    MembershipRoleUpdateOut,
    PermissionOverrideRequest,
)
from app.services.audit import record_audit_event
from app.services.memberships import (
    MembershipRoleChangeError,
    change_membership_role,
    create_membership,
)
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


@router.get("", response_model=list[MembershipOut])
def list_memberships(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_MANAGE)
) -> list[MembershipOut]:
    """The only listing of an org's memberships — needed so an ADMIN can
    find a membership_id to manage permission overrides for. Membership
    carries no RLS (see _get_membership_or_404), so this filters by org_id
    explicitly, same as everywhere else in this router."""
    rows = db.execute(
        select(Membership, Account.email)
        .join(Account, Account.id == Membership.account_id)
        .where(Membership.org_id == claims.org_id)
        .order_by(Account.email)
    ).all()
    return [
        MembershipOut(
            id=membership.id,
            account_id=membership.account_id,
            email=email,
            role=membership.role.value,
            created_at=membership.created_at,
        )
        for membership, email in rows
    ]


@router.post("", response_model=MembershipCreateOut, status_code=status.HTTP_201_CREATED)
def create_new_membership(
    body: MembershipCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> MembershipCreateOut:
    """An ADMIN provisions a new user directly (email, initial password,
    role) — there's no self-service signup in this app, so this is the
    only way a new person gets a login."""
    try:
        membership, totp_secret = create_membership(
            db, org_id=claims.org_id, email=body.email, password=body.password, role=body.role
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an account with this email already exists",
        ) from exc
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="membership.create",
        entity_type="membership",
        entity_id=membership.id,
        metadata={"email": body.email, "role": body.role.value},
    )
    return MembershipCreateOut(
        id=membership.id,
        account_id=membership.account_id,
        email=body.email,
        role=membership.role.value,
        created_at=membership.created_at,
        totp_secret=totp_secret,
        totp_provisioning_uri=totp_provisioning_uri(totp_secret, body.email)
        if totp_secret
        else None,
    )


@router.put("/{membership_id}/role", response_model=MembershipRoleUpdateOut)
def update_membership_role(
    membership_id: uuid.UUID,
    body: MembershipRoleUpdate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> MembershipRoleUpdateOut:
    """Promotes or demotes an existing member — the permission-override
    toggles below adjust fine-grained access within a role, they never
    change the role itself. This is the only way to move someone (e.g. an
    EMPLOYEE) into ADMIN or another role after their login already exists.
    Takes effect on their next login — require_roles() checks the role
    embedded in the JWT at login time, same as every other role check."""
    membership = _get_membership_or_404(db, claims.org_id, membership_id)
    old_role = membership.role.value
    try:
        membership, totp_secret = change_membership_role(
            db, membership=membership, new_role=body.role, acting_account_id=claims.account_id
        )
    except MembershipRoleChangeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    email = db.scalar(select(Account.email).where(Account.id == membership.account_id))
    record_audit_event(
        db,
        org_id=claims.org_id,
        account_id=claims.account_id,
        role=claims.role,
        action="membership.role_change",
        entity_type="membership",
        entity_id=membership.id,
        metadata={"old_role": old_role, "new_role": body.role.value},
    )
    return MembershipRoleUpdateOut(
        id=membership.id,
        account_id=membership.account_id,
        email=email or "",
        role=membership.role.value,
        totp_secret=totp_secret,
        totp_provisioning_uri=totp_provisioning_uri(totp_secret, email) if totp_secret and email else None,
    )


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
