import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models.benefit import Benefit, BenefitFrequency


def assign_benefit(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    name: str,
    frequency: BenefitFrequency,
    effective_date: date,
    description: str | None = None,
    value_minor: int | None = None,
    end_date: date | None = None,
) -> Benefit:
    if value_minor is not None and value_minor < 0:
        raise ValueError("value_minor must not be negative")
    if end_date is not None and end_date < effective_date:
        raise ValueError("end_date must not be before effective_date")

    benefit = Benefit(
        org_id=org_id,
        employee_id=employee_id,
        name=name,
        description=description,
        value_minor=value_minor,
        frequency=frequency,
        effective_date=effective_date,
        end_date=end_date,
    )
    db.add(benefit)
    db.flush()
    return benefit


def end_benefit(db: Session, benefit: Benefit, *, end_date: date) -> Benefit:
    if end_date < benefit.effective_date:
        raise ValueError("end_date must not be before effective_date")
    benefit.end_date = end_date
    db.add(benefit)
    return benefit
