import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OvertimeStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"


class Overtime(Base):
    """Extra hours worked beyond an employee's normal schedule. Approved,
    unpaid entries are picked up automatically by the next pay run
    (process_employee_payslip) as taxable but non-pensionable extra
    earnings — folded into cumulative PAYE the same way final
    settlement's gratuity/leave payout are, via extra_other_earnings_minor,
    but never counted toward pensionable_pay_minor (basic+housing+
    transport only, nigeria-statutory-compliance.md §6).

    hours and rate_multiplier are recorded for the audit trail, but
    amount_minor is what actually feeds payroll: what an overtime hour is
    paid at is an employer policy question this reference gives no
    statutory formula for (unlike PAYE/pension/NHF), so the caller
    supplies the computed amount directly rather than this table inventing
    a rate. Mutable status, same as leave_requests/loans/expenses — not
    append-only, since pending/rejected are corrected in place rather than
    superseded by a new row.
    """

    __tablename__ = "overtime_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    rate_multiplier: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[OvertimeStatus] = mapped_column(
        Enum(
            OvertimeStatus, name="overtime_status", values_callable=lambda m: [x.value for x in m]
        ),
        nullable=False,
        default=OvertimeStatus.PENDING,
    )
    # Set once a pay run actually pays this entry out; cleared back to None
    # (status reverted to APPROVED) if that run is later reversed — same
    # restoration pattern as loan repayments.
    pay_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pay_runs.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
