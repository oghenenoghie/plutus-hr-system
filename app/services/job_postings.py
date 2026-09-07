import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models.job_posting import JobPosting


def register_job_posting(
    db: Session,
    *,
    org_id: uuid.UUID,
    title: str,
    opened_date: date,
    department_id: uuid.UUID | None = None,
    description: str | None = None,
) -> JobPosting:
    job_posting = JobPosting(
        org_id=org_id,
        title=title,
        opened_date=opened_date,
        department_id=department_id,
        description=description,
    )
    db.add(job_posting)
    db.flush()
    return job_posting
