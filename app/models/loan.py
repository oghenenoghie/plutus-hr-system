import enum
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LoanStatus(str, enum.Enum):
    ACTIVE = "active"
    PAID_OFF = "paid_off"
    CANCELLED = "cancelled"


class Loan(Base):
    """An interest-free employee advance repaid via payroll deduction.
    Interest is deliberately not modelled: it's an employer policy choice,
    not a statutory figure, and nothing in the compliance reference
    specifies one — encoding a rate here would be inventing it.
    """

    __tablename__ = "loans"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    principal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    num_installments: Mapped[int] = mapped_column(Integer, nullable=False)
    installment_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[LoanStatus] = mapped_column(
        Enum(LoanStatus, name="loan_status", values_callable=lambda m: [x.value for x in m]),
        nullable=False,
        default=LoanStatus.ACTIVE,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LoanRepayment(Base):
    """One deduction against a loan, tied to the payslip it came from.
    Append-only — the outstanding balance is derived by summing these,
    never stored redundantly."""

    __tablename__ = "loan_repayments"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    loan_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("loans.id", ondelete="CASCADE"), nullable=False
    )
    payslip_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payslips.id", ondelete="SET NULL")
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
