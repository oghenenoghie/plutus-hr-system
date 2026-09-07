import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FinalSettlement(Base):
    """Exit payroll: leave payout + gratuity, taxed through the normal
    payslip machinery (gratuity is taxable per nigeria-statutory-
    compliance.md §1), less any outstanding loan balance recovered in
    full. leave_payout_minor and gratuity_minor are supplied by the
    caller — how many naira a day of unused leave or a gratuity award is
    worth is an employer policy question with no statutory formula to
    encode, unlike PAYE/pension/NHF on the resulting payslip. Append-only.
    """

    __tablename__ = "final_settlements"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    payslip_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payslips.id", ondelete="CASCADE"), nullable=False
    )

    termination_date: Mapped[date] = mapped_column(Date, nullable=False)
    leave_days_paid_out: Mapped[int] = mapped_column(Integer, nullable=False)
    leave_payout_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gratuity_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    outstanding_loan_recovered_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    net_settlement_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
