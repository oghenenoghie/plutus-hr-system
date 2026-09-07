import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AssetAssignment(Base):
    """One stretch of a company asset being issued to an employee, from
    assigned_date to (once returned) returned_date. Deleting the asset or
    the employee cascades — an assignment record has no meaning detached
    from either. A currently-held asset is one whose latest assignment has
    returned_date is null; nothing enforces at most one open assignment
    per asset at the DB level, that's the service layer's job (mirroring
    how the asset's own status field is kept in sync there too).
    """

    __tablename__ = "asset_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("company_assets.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )

    assigned_date: Mapped[date] = mapped_column(Date, nullable=False)
    returned_date: Mapped[date | None] = mapped_column(Date)
    condition_notes: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
