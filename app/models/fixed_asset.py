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


class FixedAssetCategory(str, enum.Enum):
    """What kind of property this is — the same categories HR's old,
    now-retired CompanyAsset tracked separately. Nullable: not every fixed
    asset (a building, a server) is a device someone can be issued."""

    LAPTOP = "laptop"
    PHONE = "phone"
    VEHICLE = "vehicle"
    FURNITURE = "furniture"
    OTHER = "other"


class AssetAssignmentStatus(str, enum.Enum):
    """Operational status for a fixed asset that's issued to people —
    independent of FixedAssetStatus, which tracks the *financial*
    lifecycle (active/disposed). An asset can be ACTIVE and MAINTENANCE at
    the same time: still on the books, just not with anyone right now.
    Null when the asset has no category (nothing to issue)."""

    AVAILABLE = "available"
    ASSIGNED = "assigned"
    MAINTENANCE = "maintenance"


class FixedAsset(Base):
    """A depreciable, financial asset. Used to be split from HR's
    CompanyAsset (who has which laptop); category/assignment_status/
    assigned_employee_id fold that operational tracking in here instead,
    so there's one record per physical asset rather than two that could
    drift apart. accumulated_depreciation_minor is denormalized onto the
    row (mirrors Bill.paid_amount_minor's pattern) so book value can be
    read without re-deriving it from the ledger; record_depreciation/
    dispose_fixed_asset are the only writers of it, keeping it in sync
    with what's actually posted.
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

    category: Mapped[FixedAssetCategory | None] = mapped_column(
        Enum(
            FixedAssetCategory,
            name="fixed_asset_category",
            values_callable=lambda m: [x.value for x in m],
        )
    )
    assignment_status: Mapped[AssetAssignmentStatus | None] = mapped_column(
        Enum(
            AssetAssignmentStatus,
            name="asset_assignment_status",
            values_callable=lambda m: [x.value for x in m],
        )
    )
    assigned_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def book_value_minor(self) -> int:
        return self.cost_minor - self.accumulated_depreciation_minor
