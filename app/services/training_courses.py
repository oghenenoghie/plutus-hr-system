import uuid

from sqlalchemy.orm import Session

from app.models.training_course import TrainingCourse


def register_training_course(
    db: Session,
    *,
    org_id: uuid.UUID,
    title: str,
    description: str | None = None,
    provider: str | None = None,
    duration_hours: int | None = None,
) -> TrainingCourse:
    course = TrainingCourse(
        org_id=org_id,
        title=title,
        description=description,
        provider=provider,
        duration_hours=duration_hours,
    )
    db.add(course)
    db.flush()
    return course
