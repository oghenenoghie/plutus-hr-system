import uuid

from sqlalchemy.orm import Session

from app.models.job_grade import JobGrade


def register_job_grade(
    db: Session,
    *,
    org_id: uuid.UUID,
    name: str,
    level: int | None = None,
    min_salary_minor: int | None = None,
    max_salary_minor: int | None = None,
) -> JobGrade:
    job_grade = JobGrade(
        org_id=org_id,
        name=name,
        level=level,
        min_salary_minor=min_salary_minor,
        max_salary_minor=max_salary_minor,
    )
    db.add(job_grade)
    db.flush()
    return job_grade
