import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ProbationStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class ProbationPeriod(Base):
    """A formal probation window for a new hire — a concrete start/end date
    and confirmation decision, distinct from the tenure-window
    LifecycleStage.ONBOARDING flag in app.domain.employee_lifecycle (which
    is just "still within N days of joining", with no record of a decision
    ever being made). end_date is extendable in place while IN_PROGRESS
    (see extend_probation) rather than modelled as a new period, since it's
    still the same probation being evaluated. Only one IN_PROGRESS period
    per employee is allowed at a time (see register_probation_period).
    Mutable, not append-only: like DisciplinaryCase, the decision itself is
    the state being tracked.
    """

    __tablename__ = "probation_periods"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[ProbationStatus] = mapped_column(
        Enum(
            ProbationStatus, name="probation_status", values_callable=lambda m: [x.value for x in m]
        ),
        nullable=False,
        default=ProbationStatus.IN_PROGRESS,
    )
    decided_date: Mapped[date | None] = mapped_column(Date)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(String(1000))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
