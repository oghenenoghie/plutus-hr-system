import uuid

from sqlalchemy.orm import Session

from app.models.organisation import Organisation


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
