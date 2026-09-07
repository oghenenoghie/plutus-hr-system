import enum
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UnionMembershipStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class UnionMembership(Base):
    """An employee's membership in a trade union, and the monthly dues to
    deduct while it's active. Tracked for record-keeping here — not yet
    wired into payroll's deduction set (nigeria-statutory-compliance.md
    doesn't cover union dues; unlike PAYE/pension/NHF this isn't a
    statutory deduction, so nothing in the rules engine assumes it).
    terminated_date is only ever set once, by terminate — suspension
    (a temporary, reversible state) does not touch it.
    """

    __tablename__ = "union_memberships"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    union_name: Mapped[str] = mapped_column(String(255), nullable=False)
    membership_number: Mapped[str | None] = mapped_column(String(64))
    monthly_dues_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[UnionMembershipStatus] = mapped_column(
        Enum(
            UnionMembershipStatus,
            name="union_membership_status",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
        default=UnionMembershipStatus.ACTIVE,
    )
    joined_date: Mapped[date] = mapped_column(Date, nullable=False)
    terminated_date: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
