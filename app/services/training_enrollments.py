import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models.training_enrollment import TrainingEnrollment


def register_training_enrollment(
    db: Session,
    *,
    org_id: uuid.UUID,
    course_id: uuid.UUID,
    employee_id: uuid.UUID,
    enrolled_date: date,
) -> TrainingEnrollment:
    enrollment = TrainingEnrollment(
        org_id=org_id,
        course_id=course_id,
        employee_id=employee_id,
        enrolled_date=enrolled_date,
    )
    db.add(enrollment)
    db.flush()
    return enrollment
