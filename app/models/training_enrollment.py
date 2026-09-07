import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TrainingEnrollmentStatus(str, enum.Enum):
    ENROLLED = "enrolled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class TrainingEnrollment(Base):
    """One employee's participation in a single training course. Deleting
    the course deletes its enrollments (ondelete CASCADE) — an enrollment
    record has no meaning detached from what it enrolled the employee in.
    score is an optional 0-100 assessment result, advisory only — nothing
    enforces its range at the DB level.
    """

    __tablename__ = "training_enrollments"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("training_courses.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[TrainingEnrollmentStatus] = mapped_column(
        Enum(
            TrainingEnrollmentStatus,
            name="training_enrollment_status",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
        default=TrainingEnrollmentStatus.ENROLLED,
    )
    enrolled_date: Mapped[date] = mapped_column(Date, nullable=False)
    completed_date: Mapped[date | None] = mapped_column(Date)
    score: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
