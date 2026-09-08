import enum
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.payroll.frequency import PayFrequency
from app.models.base import Base


class PayRunStatus(str, enum.Enum):
    DRAFT = "draft"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REVERSED = "reversed"


class PayRun(Base):
    __tablename__ = "pay_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    frequency: Mapped[PayFrequency] = mapped_column(
        Enum(
            PayFrequency, name="pay_run_frequency", values_callable=lambda m: [x.value for x in m]
        ),
        nullable=False,
    )
    status: Mapped[PayRunStatus] = mapped_column(
        Enum(PayRunStatus, name="pay_run_status", values_callable=lambda m: [x.value for x in m]),
        nullable=False,
        default=PayRunStatus.DRAFT,
    )
    rule_version_id: Mapped[str | None] = mapped_column(String(32))

    employee_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gross_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
