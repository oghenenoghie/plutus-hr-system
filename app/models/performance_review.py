import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PerformanceReviewStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"


class PerformanceReview(Base):
    """A single review cycle for one employee, covering period_start to
    period_end. reviewer_id is the manager who conducted it — nullable via
    SET NULL so removing a manager account doesn't destroy review history.
    Lifecycle is linear: draft (created, not yet delivered) -> submitted
    (manager has rated/commented) -> acknowledged (employee has read and
    responded). Nothing enforces the manager/employee relationship at the
    DB level; the API is the single writer for status transitions.
    """

    __tablename__ = "performance_reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL")
    )

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PerformanceReviewStatus] = mapped_column(
        Enum(
            PerformanceReviewStatus,
            name="performance_review_status",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
        default=PerformanceReviewStatus.DRAFT,
    )
    rating: Mapped[int | None] = mapped_column(Integer)
    goals: Mapped[str | None] = mapped_column(Text)
    manager_comments: Mapped[str | None] = mapped_column(Text)
    employee_comments: Mapped[str | None] = mapped_column(Text)
    submitted_date: Mapped[date | None] = mapped_column(Date)
    acknowledged_date: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
