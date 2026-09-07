import uuid

from sqlalchemy.orm import Session

from app.models.vendor import Vendor


def register_vendor(
    db: Session,
    *,
    org_id: uuid.UUID,
    name: str,
    contact_email: str | None = None,
    contact_phone: str | None = None,
    tin: str | None = None,
    contractor_id: uuid.UUID | None = None,
) -> Vendor:
    vendor = Vendor(
        org_id=org_id,
        name=name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        tin=tin,
        contractor_id=contractor_id,
    )
    db.add(vendor)
    db.flush()
    return vendor
