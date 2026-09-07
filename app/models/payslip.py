import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Payslip(Base):
    """Per employee per run. Append-only — enforced at the DB level
    (nigeria-statutory-compliance.md / python-engineering.md §4): corrections
    are new payslips (e.g. on a later run), never edits to this row.
    `derivation` carries every input and intermediate figure that produced
    this result, for the "how?" trail.
    """

    __tablename__ = "payslips"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    pay_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pay_runs.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    gross_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pensionable_pay_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pension_employee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pension_employer_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    nhf_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paye_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cumulative_chargeable_income_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)

    rule_version_id: Mapped[str] = mapped_column(String(32), nullable=False)
    derivation: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
