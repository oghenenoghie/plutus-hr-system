import uuid

from sqlalchemy.orm import Session

from app.models.training_course_attachment import TrainingCourseAttachment


def add_course_attachment(
    db: Session, *, org_id: uuid.UUID, course_id: uuid.UUID, title: str, storage_url: str
) -> TrainingCourseAttachment:
    attachment = TrainingCourseAttachment(
        org_id=org_id, course_id=course_id, title=title, storage_url=storage_url
    )
    db.add(attachment)
    db.flush()
    return attachment
