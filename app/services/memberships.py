import uuid

from sqlalchemy.orm import Session

from app.core.security import generate_totp_secret, hash_password
from app.models.account import Account
from app.models.membership import MFA_REQUIRED_ROLES, Membership, Role


class MembershipRoleChangeError(Exception):
    """Raised for a role change the API layer should reject with a 4xx —
    same pattern as PayRunLifecycleError."""


def create_membership(
    db: Session, *, org_id: uuid.UUID, email: str, password: str, role: Role
) -> tuple[Membership, str | None]:
    """Creates a new Account + Membership in one org. Account.email is
    unique across the whole system (not just this org) — the caller maps
    the resulting IntegrityError to a 409.

    ADMIN/PAYROLL_MANAGER accounts have their TOTP enabled immediately
    (secret generated here, not left for the new account to set up itself)
    since there's no bootstrap-token endpoint a brand new account could
    call totp/setup with before its first successful login — see
    MembershipCreateOut's own docstring.
    """
    account_id = uuid.uuid4()
    totp_secret = generate_totp_secret() if role in MFA_REQUIRED_ROLES else None

    account = Account(
        id=account_id,
        email=email,
        password_hash=hash_password(password),
        totp_secret=totp_secret,
        totp_enabled=totp_secret is not None,
    )
    membership = Membership(account_id=account_id, org_id=org_id, role=role)
    db.add(account)
    db.add(membership)
    db.flush()
    return membership, totp_secret


def change_membership_role(
    db: Session, *, membership: Membership, new_role: Role, acting_account_id: uuid.UUID
) -> tuple[Membership, str | None]:
    """Promotes or demotes an existing membership to a different role —
    the only way to do this today; there's no self-service path, same as
    create_membership. Mirrors create_membership's MFA bootstrap: moving
    into an MFA-required role for an account that never had one enables
    TOTP eagerly and hands back the secret once, since there's still no
    bootstrap-token endpoint for the account to call totp/setup itself
    before its first login under the new role. Moving between two
    MFA-required roles, or out of one, leaves existing TOTP state alone —
    a demoted account keeps MFA rather than silently losing it.
    """
    if membership.account_id == acting_account_id:
        raise MembershipRoleChangeError("cannot change your own role")
    if membership.role == new_role:
        raise MembershipRoleChangeError(f"membership already has role {new_role.value}")

    account = db.get(Account, membership.account_id)
    assert account is not None  # every membership has a backing account

    totp_secret: str | None = None
    if new_role in MFA_REQUIRED_ROLES and not account.totp_enabled:
        totp_secret = generate_totp_secret()
        account.totp_secret = totp_secret
        account.totp_enabled = True
        db.add(account)

    membership.role = new_role
    db.add(membership)
    db.flush()
    return membership, totp_secret
