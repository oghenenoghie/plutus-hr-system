import enum
import uuid
from datetime import date, datetime

from sqlalchemy import ARRAY, BigInteger, Date, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.payroll.frequency import PayFrequency
from app.models.base import Base


class PayRunStatus(str, enum.Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    LOCKED = "locked"
    REVERSED = "reversed"


class PayRun(Base):
    """draft -> validated -> locked is the review/approval gate; "paid" is
    not its own status (disbursed_at/disbursed_by instead), same reasoning
    as employees.login_code being a projection rather than a state: a
    pay run is either disbursed or not, independent of anything else about
    it. Payslips/ledger entries are append-only (see their own models), so
    nothing about a pay run is genuinely permanent until lock — draft and
    validated are freely discardable (see services/pay_run_lifecycle.py's
    discard_pay_run_draft) precisely because run_pay_run only ever executes
    at lock time. Once locked, a correction is reverse_pay_run (a
    correcting ledger entry, REVERSED status), never an edit.
    """

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
    # Resolved and pinned at draft creation (not re-resolved at validate/lock
    # time) so a hire made between draft and lock can't silently join a run
    # nobody reviewed them against, and so the "employee missing vs. the
    # last locked run" variance check compares two fixed sets.
    employee_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, default=list
    )
    rule_version_id: Mapped[str | None] = mapped_column(String(32))

    employee_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gross_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL")
    )
    disbursed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disbursed_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL")
    )
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
