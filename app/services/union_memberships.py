import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models.union_membership import UnionMembership, UnionMembershipStatus


def register_union_membership(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    union_name: str,
    monthly_dues_minor: int,
    joined_date: date,
    membership_number: str | None = None,
) -> UnionMembership:
    if monthly_dues_minor < 0:
        raise ValueError("monthly_dues_minor must not be negative")

    membership = UnionMembership(
        org_id=org_id,
        employee_id=employee_id,
        union_name=union_name,
        membership_number=membership_number,
        monthly_dues_minor=monthly_dues_minor,
        joined_date=joined_date,
    )
    db.add(membership)
    db.flush()
    return membership


def terminate_union_membership(
    db: Session, membership: UnionMembership, *, terminated_date: date
) -> UnionMembership:
    if membership.status == UnionMembershipStatus.TERMINATED:
        raise ValueError("union membership is already terminated")
    if terminated_date < membership.joined_date:
        raise ValueError("terminated_date must not be before joined_date")

    membership.status = UnionMembershipStatus.TERMINATED
    membership.terminated_date = terminated_date
    db.add(membership)
    return membership
