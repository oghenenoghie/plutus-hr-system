import uuid

from sqlalchemy.orm import Session

from app.models.contractor import Contractor


def register_contractor(
    db: Session,
    *,
    org_id: uuid.UUID,
    name: str,
    tin: str | None = None,
    bank_name: str | None = None,
    account_number: str | None = None,
    account_name: str | None = None,
) -> Contractor:
    contractor = Contractor(
        org_id=org_id,
        name=name,
        tin=tin,
        bank_name=bank_name,
        account_number=account_number,
        account_name=account_name,
    )
    db.add(contractor)
    db.flush()
    return contractor
