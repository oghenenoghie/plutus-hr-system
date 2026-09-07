import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models.policy import Policy


def register_policy(
    db: Session,
    *,
    org_id: uuid.UUID,
    title: str,
    body: str,
    category: str | None = None,
    effective_date: date | None = None,
) -> Policy:
    policy = Policy(
        org_id=org_id, title=title, body=body, category=category, effective_date=effective_date
    )
    db.add(policy)
    db.flush()
    return policy
