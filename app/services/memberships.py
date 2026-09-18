import uuid

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.account import Account
from app.models.membership import Membership, Role


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
