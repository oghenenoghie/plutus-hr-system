import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PayslipStatutoryLine(Base):
    """One statutory line of a payslip worked out by the country-neutral
    engine (app.compliance.engine): an employee or employer contribution or
    the income tax, with the rule set and source it came from. Nigerian
    payslips keep their own columns and have none of these. Append-only at
    the DB level, like the payslip itself.
    """

    __tablename__ = "payslip_statutory_lines"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    payslip_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payslips.id", ondelete="CASCADE"), nullable=False
    )
    pay_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pay_runs.id", ondelete="CASCADE"), nullable=False
    )
    rule_set_id: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # calculation order

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # employee_contribution, employer_contribution or income_tax
    # (app.compliance.engine.calculate.LineKind)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    authority: Mapped[str] = mapped_column(String(255), nullable=False)
    base_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rate_ppm: Mapped[int | None] = mapped_column(Integer)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    liability_account: Mapped[str] = mapped_column(String(64), nullable=False)
    expense_account: Mapped[str | None] = mapped_column(String(64))
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
