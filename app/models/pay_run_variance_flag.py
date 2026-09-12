import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class VarianceFlagType(str, enum.Enum):
    GROSS_SWING = "gross_swing"
    EMPLOYEE_MISSING = "employee_missing"


class PayRunVarianceFlag(Base):
    """Raised by validate_pay_run when a pay run looks surprising next to
    the org's last locked run of the same frequency: an employee's gross
    swinging by 30%+, or an active employee present last time missing from
    this run. Mutable (not append-only like Payslip/LedgerEntry) since
    acknowledging a flag is a real, correctable action, not a financial
    record — re-running validate replaces this pay run's flags with a
    fresh detection pass rather than accumulating stale ones.
    """

    __tablename__ = "pay_run_variance_flags"

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

    flag_type: Mapped[VarianceFlagType] = mapped_column(
        Enum(
            VarianceFlagType,
            name="pay_run_variance_flag_type",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
    )
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    acknowledged: Mapped[bool] = mapped_column(nullable=False, default=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
