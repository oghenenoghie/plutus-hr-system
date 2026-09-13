import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TrainingQuiz(Base):
    """A quiz attached to a TrainingCourse. passing_score is the minimum
    percentage (0-100) an attempt needs to count as passed — see
    app.domain.quiz_grading.grade_quiz."""

    __tablename__ = "training_quizzes"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("training_courses.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    passing_score: Mapped[int] = mapped_column(Integer, nullable=False, default=70)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
