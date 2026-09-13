import enum
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LeaveEncashmentStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"


class LeaveEncashmentRequest(Base):
    """Converting unused leave days into a cash payout instead of time off.
    Approved days are treated as consumed for balance purposes exactly like
    days actually taken (see app/services/leave.py::approved_days_taken) —
    encashing 5 days means 5 fewer are left to take as leave. amount_minor
    is caller-supplied rather than derived from a per-day rate formula: the
    statutory reference gives no such formula (same reasoning as
    overtime.amount_minor), so what a day of encashed leave is worth is an
    employer policy decision made outside this table. Picked up by the next
    pay run the same "request -> approval -> next-pay-run payout" way as
    overtime; requested_date anchors which leave year the days are debited
    from.
    """

    __tablename__ = "leave_encashment_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    requested_date: Mapped[date] = mapped_column(Date, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[LeaveEncashmentStatus] = mapped_column(
        Enum(
            LeaveEncashmentStatus,
            name="leave_encashment_status",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
        default=LeaveEncashmentStatus.PENDING,
    )
    pay_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pay_runs.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
