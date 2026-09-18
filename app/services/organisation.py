import uuid

from sqlalchemy.orm import Session

from app.core.db import tenant_session
from app.models.membership import Membership, Role
from app.models.organisation import Organisation
from app.services.memberships import create_membership


def signup_organisation(
    *, org_name: str, admin_email: str, admin_password: str
) -> tuple[Organisation, Membership]:
    """The only way a brand-new company gets onto Plutus — there's no
    invite-only path in for a first org, unlike every subsequent login
    within it (see MembershipCreate's own docstring). Opens its own
    tenant_session rather than taking a Session/claims dependency, since
    by definition no org or account exists yet to derive either from —
    same reasoning as create_org() in the test helpers, which this
    mirrors: the org_id is generated client-side so the RLS
    WITH CHECK (id = current_org GUC) is satisfiable on first insert.
    """
    org_id = uuid.uuid4()
    with tenant_session(org_id, uuid.uuid4(), Role.ADMIN.value) as db:
        org = Organisation(id=org_id, name=org_name)
        db.add(org)
        db.flush()
        membership = create_membership(
            db, org_id=org_id, email=admin_email, password=admin_password, role=Role.ADMIN
        )
    return org, membership


def get_organisation(db: Session, org_id: uuid.UUID) -> Organisation:
    org = db.get(Organisation, org_id)
    if org is None:
        raise ValueError("organisation not found")
    return org


def update_organisation(db: Session, org: Organisation, **fields: object) -> Organisation:
    for field, value in fields.items():
        if value is not None:
            setattr(org, field, value)
    db.flush()
    return org
