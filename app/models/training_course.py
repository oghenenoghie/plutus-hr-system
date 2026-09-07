import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TrainingCourse(Base):
    """A course in an org's learning catalogue. Org-wide reference data,
    readable by every role (same as Policies) — employees browse the
    catalogue even though only ADMIN/PAYROLL_MANAGER can enroll them in one.
    """

    __tablename__ = "training_courses"
    __table_args__ = (UniqueConstraint("org_id", "title", name="uq_training_course_org_title"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(String(255))
    duration_hours: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
