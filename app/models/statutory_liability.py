import enum
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LiabilityScheme(str, enum.Enum):
    PAYE = "paye"
    PENSION = "pension"
    NHF = "nhf"
    NSITF = "nsitf"
    ITF = "itf"
    WHT = "wht"


class LiabilityStatus(str, enum.Enum):
    PENDING = "pending"
    FILED = "filed"
    REMITTED = "remitted"


class StatutoryLiability(Base):
    """One scheme's liability for one period (and, for PAYE, one state —
    §9 requires per-state filing schedules since each state's IRS collects
    separately; every other scheme is national). Computed once from
    pay-run data and then tracked through filing and remittance — the
    amount itself is not meant to be edited after the fact; a correction
    is a new row, same discipline as payslips.
    """

    __tablename__ = "statutory_liabilities"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    pay_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("pay_runs.id", ondelete="CASCADE")
    )

    scheme: Mapped[LiabilityScheme] = mapped_column(
        Enum(
            LiabilityScheme, name="liability_scheme", values_callable=lambda m: [x.value for x in m]
        ),
        nullable=False,
    )
    state: Mapped[str | None] = mapped_column(String(64))  # PAYE only
    authority: Mapped[str] = mapped_column(String(64), nullable=False)
    base_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[LiabilityStatus] = mapped_column(
        Enum(
            LiabilityStatus, name="liability_status", values_callable=lambda m: [x.value for x in m]
        ),
        nullable=False,
        default=LiabilityStatus.PENDING,
    )
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remittance_reference: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
