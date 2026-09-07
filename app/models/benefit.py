import enum
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BenefitFrequency(str, enum.Enum):
    ONE_TIME = "one_time"
    MONTHLY = "monthly"
    ANNUAL = "annual"


class Benefit(Base):
    """A non-statutory perk assigned to an employee (health insurance, meal
    allowance, gym membership, ...) — tracked for record-keeping, not run
    through payroll. value_minor is nullable because not every benefit is
    monetary (e.g. gym access). Deliberately not taxed or valued as a
    benefit-in-kind here: nigeria-statutory-compliance.md gives no figure
    for that (NHIS/NHIA is 'scheme-defined', §5, and nothing else in the
    reference addresses benefit-in-kind treatment) — encoding one would be
    inventing a statutory rule, which the engine's guardrail forbids.
    """

    __tablename__ = "benefits"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    value_minor: Mapped[int | None] = mapped_column(BigInteger)
    frequency: Mapped[BenefitFrequency] = mapped_column(
        Enum(
            BenefitFrequency,
            name="benefit_frequency",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
