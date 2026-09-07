import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models.candidate import Candidate


def register_candidate(
    db: Session,
    *,
    org_id: uuid.UUID,
    job_posting_id: uuid.UUID,
    full_name: str,
    applied_date: date,
    email: str | None = None,
    phone: str | None = None,
) -> Candidate:
    candidate = Candidate(
        org_id=org_id,
        job_posting_id=job_posting_id,
        full_name=full_name,
        applied_date=applied_date,
        email=email,
        phone=phone,
    )
    db.add(candidate)
    db.flush()
    return candidate
