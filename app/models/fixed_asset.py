import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FixedAssetStatus(str, enum.Enum):
    ACTIVE = "active"
    DISPOSED = "disposed"


class FixedAsset(Base):
    """A depreciable, financial asset — distinct from CompanyAsset (HR's
    operational tracking of who has which laptop). accumulated_depreciation_minor
    is denormalized onto the row (mirrors Bill.paid_amount_minor's pattern)
    so book value can be read without re-deriving it from the ledger;
    record_depreciation/dispose_fixed_asset are the only writers of it,
    keeping it in sync with what's actually posted.
    """

    __tablename__ = "fixed_assets"
    __table_args__ = (UniqueConstraint("org_id", "asset_tag", name="uq_fixed_asset_org_tag"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL")
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_tag: Mapped[str] = mapped_column(String(64), nullable=False)
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    cost_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    salvage_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    useful_life_months: Mapped[int] = mapped_column(Integer, nullable=False)
    accumulated_depreciation_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    status: Mapped[FixedAssetStatus] = mapped_column(
        Enum(
            FixedAssetStatus,
            name="fixed_asset_status",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
        default=FixedAssetStatus.ACTIVE,
    )
    disposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disposal_proceeds_minor: Mapped[int | None] = mapped_column(BigInteger)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def book_value_minor(self) -> int:
        return self.cost_minor - self.accumulated_depreciation_minor
