import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AssetCategory(Base):
    """A class of fixed asset the organisation defines (Motor Vehicles,
    Office Equipment, Buildings), with the depreciation it usually takes:
    a new asset in the category starts from these, and can differ. Not the
    device type on FixedAsset.category, which says what can be issued to
    an employee."""

    __tablename__ = "asset_categories"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_asset_category_org_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    depreciation_method: Mapped[str] = mapped_column(String(24), nullable=False)
    depreciation_rate_ppm: Mapped[int | None] = mapped_column(Integer)
    useful_life_months: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
