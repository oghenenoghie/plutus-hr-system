import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FixedAssetTransfer(Base):
    """Append-only log of every department reassignment for a FixedAsset —
    FixedAsset.department_id is only ever the current cost-centre; this is
    the permanent record of every prior one and when it changed, same
    precedent as EmployeeHistoryEvent for Employee's own current-value
    fields.
    """

    __tablename__ = "fixed_asset_transfers"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    fixed_asset_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("fixed_assets.id", ondelete="CASCADE"), nullable=False
    )
    from_department_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL")
    )
    to_department_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL")
    )
    transfer_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
