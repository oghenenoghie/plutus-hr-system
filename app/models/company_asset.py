import enum
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CompanyAssetCategory(str, enum.Enum):
    LAPTOP = "laptop"
    PHONE = "phone"
    VEHICLE = "vehicle"
    FURNITURE = "furniture"
    OTHER = "other"


class CompanyAssetStatus(str, enum.Enum):
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    MAINTENANCE = "maintenance"
    RETIRED = "retired"


class CompanyAsset(Base):
    """A piece of company property (laptop, phone, vehicle, ...) that can
    be issued to an employee and later returned. status is denormalized
    onto the asset for fast filtering ("show me what's available") —
    it's kept in sync by the assign/return service functions, which are
    the only writers of both this and CompanyAssetAssignment.
    """

    __tablename__ = "company_assets"
    __table_args__ = (UniqueConstraint("org_id", "asset_tag", name="uq_company_asset_org_tag"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_tag: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[CompanyAssetCategory] = mapped_column(
        Enum(
            CompanyAssetCategory,
            name="company_asset_category",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
    )
    status: Mapped[CompanyAssetStatus] = mapped_column(
        Enum(
            CompanyAssetStatus,
            name="company_asset_status",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
        default=CompanyAssetStatus.AVAILABLE,
    )
    purchase_date: Mapped[date | None] = mapped_column(Date)
    purchase_value_minor: Mapped[int | None] = mapped_column(BigInteger)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
