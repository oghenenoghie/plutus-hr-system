import uuid

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.account import Account
from app.models.membership import Membership, Role


class MembershipRoleChangeError(Exception):
    """Raised for a role change the API layer should reject with a 4xx —
    same pattern as PayRunLifecycleError."""


def create_membership(
    db: Session, *, org_id: uuid.UUID, email: str, password: str, role: Role
) -> Membership:
    """Creates a new Account + Membership in one org. Account.email is
    unique across the whole system (not just this org) — the caller maps
    the resulting IntegrityError to a 409.

    TOTP MFA is never enabled here — it's opt-in for any role via
    /auth/totp/setup + /auth/totp/verify, from the account's own security
    settings, once it can log in.
    """
    account_id = uuid.uuid4()

    account = Account(
        id=account_id,
        email=email,
        password_hash=hash_password(password),
    )
    membership = Membership(account_id=account_id, org_id=org_id, role=role)
    db.add(account)
    db.add(membership)
    db.flush()
    return membership


def change_membership_role(
    db: Session, *, membership: Membership, new_role: Role, acting_account_id: uuid.UUID
) -> Membership:
    """Promotes or demotes an existing membership to a different role —
    the only way to do this today; there's no self-service path, same as
    create_membership. Role no longer gates MFA (it's opt-in per account
    via /auth/totp/setup), so this is a plain role swap with no TOTP side
    effects to bootstrap.
    """
    if membership.account_id == acting_account_id:
        raise MembershipRoleChangeError("cannot change your own role")
    if membership.role == new_role:
        raise MembershipRoleChangeError(f"membership already has role {new_role.value}")

    membership.role = new_role
    db.add(membership)
    db.flush()
    return membership
