import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Vendor(Base):
    """The general accounts-payable entity — anyone the org owes a Bill to.
    Deliberately separate from Contractor (contractor.py, payroll's WHT-
    subject payee): merging them would couple the payroll WHT flow to
    general AP, which is a different lifecycle. contractor_id is an
    optional back-reference for a vendor that also happens to be a
    WHT-subject contractor, so their name/TIN/bank details aren't
    duplicated across both tables.
    """

    __tablename__ = "vendors"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_vendor_org_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    contractor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contractors.id", ondelete="SET NULL")
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    tin: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
