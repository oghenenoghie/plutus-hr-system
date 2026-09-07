import uuid

from sqlalchemy.orm import Session

from app.models.customer import Customer


def register_customer(
    db: Session,
    *,
    org_id: uuid.UUID,
    name: str,
    contact_email: str | None = None,
    contact_phone: str | None = None,
    tin: str | None = None,
) -> Customer:
    customer = Customer(
        org_id=org_id,
        name=name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        tin=tin,
    )
    db.add(customer)
    db.flush()
    return customer
