import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FixedAssetRevaluation(Base):
    """Append-only log of every revaluation applied to a FixedAsset — see
    revalue_fixed_asset, which resets cost_minor to the new value and
    accumulated_depreciation_minor to zero (a common simplified treatment:
    the asset's book value becomes its new cost basis, and future
    depreciation runs off that new basis and useful life going forward).
    This row is the permanent record of the old and new book value and why.
    """

    __tablename__ = "fixed_asset_revaluations"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    fixed_asset_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("fixed_assets.id", ondelete="CASCADE"), nullable=False
    )
    revaluation_date: Mapped[date] = mapped_column(Date, nullable=False)
    old_book_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    new_book_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
