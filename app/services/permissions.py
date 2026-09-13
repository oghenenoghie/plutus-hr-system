import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.permissions import Permission, resolve_permissions
from app.models.membership import Membership
from app.models.membership_permission_override import MembershipPermissionOverride


def set_permission_override(
    db: Session,
    membership: Membership,
    *,
    permission: Permission,
    granted: bool,
    granted_by: uuid.UUID | None,
) -> MembershipPermissionOverride:
    existing = db.scalar(
        select(MembershipPermissionOverride).where(
            MembershipPermissionOverride.membership_id == membership.id,
            MembershipPermissionOverride.permission == permission,
        )
    )
    if existing is not None:
        existing.granted = granted
        existing.granted_by = granted_by
        db.add(existing)
        db.flush()
        return existing

    override = MembershipPermissionOverride(
        org_id=membership.org_id,
        membership_id=membership.id,
        permission=permission,
        granted=granted,
        granted_by=granted_by,
    )
    db.add(override)
    db.flush()
    return override


def clear_permission_override(
    db: Session, membership: Membership, *, permission: Permission
) -> None:
    existing = db.scalar(
        select(MembershipPermissionOverride).where(
            MembershipPermissionOverride.membership_id == membership.id,
            MembershipPermissionOverride.permission == permission,
        )
    )
    if existing is not None:
        db.delete(existing)
        db.flush()


def effective_permissions(db: Session, membership: Membership) -> frozenset[Permission]:
    overrides = {
        row.permission: row.granted
        for row in db.scalars(
            select(MembershipPermissionOverride).where(
                MembershipPermissionOverride.membership_id == membership.id
            )
        )
    }
    return resolve_permissions(membership.role.value, overrides)
