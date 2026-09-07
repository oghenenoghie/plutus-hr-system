import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PayslipDeliveryStatus(str, enum.Enum):
    SENT = "sent"
    FAILED = "failed"


class PayslipDelivery(Base):
    """One row per email attempt for a payslip. Never updated — a retry
    after a failure is a new row, not a correction to the old one, so the
    full delivery history for a payslip is always visible.
    """

    __tablename__ = "payslip_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    payslip_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payslips.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[PayslipDeliveryStatus] = mapped_column(
        Enum(
            PayslipDeliveryStatus,
            name="payslip_delivery_status",
            values_callable=lambda members: [m.value for m in members],
        ),
        nullable=False,
    )
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
