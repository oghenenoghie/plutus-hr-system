import uuid
from datetime import date

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
    email: str | None = None,
    phone: str | None = None,
    engagement_start_date: date | None = None,
    engagement_end_date: date | None = None,
) -> Contractor:
    contractor = Contractor(
        org_id=org_id,
        name=name,
        tin=tin,
        bank_name=bank_name,
        account_number=account_number,
        account_name=account_name,
        email=email,
        phone=phone,
        engagement_start_date=engagement_start_date,
        engagement_end_date=engagement_end_date,
    )
    db.add(contractor)
    db.flush()
    return contractor
