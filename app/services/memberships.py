import uuid

from sqlalchemy.orm import Session

from app.core.security import generate_totp_secret, hash_password
from app.models.account import Account
from app.models.membership import MFA_REQUIRED_ROLES, Membership, Role


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
