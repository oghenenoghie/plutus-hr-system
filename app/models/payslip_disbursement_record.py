import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DisbursementStatus(str, enum.Enum):
    SETTLED = "settled"
    FAILED = "failed"


class PayslipDisbursementRecord(Base):
    """One row per confirmed disbursement outcome for a payslip — a bank
    transfer settling, bouncing, or being retried. Never updated: a retry
    after a failed transfer is a new row, same discipline as
    PayslipDelivery, so the full settlement history for a payslip is
    always visible rather than overwritten. generate_disbursement_file
    only produces the file to send to a bank; this is where the outcome
    of actually sending it gets recorded back, since there is no live
    bank API integration in this codebase to confirm it automatically.
    """

    __tablename__ = "payslip_disbursement_records"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    payslip_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payslips.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[DisbursementStatus] = mapped_column(
        Enum(
            DisbursementStatus,
            name="payslip_disbursement_status",
            values_callable=lambda members: [m.value for m in members],
        ),
        nullable=False,
    )
    reference: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(String(1000))
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
