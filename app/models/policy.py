import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Policy(Base):
    """An HR policy document (leave policy, code of conduct, expense
    policy, etc). Unlike Department/Branch/JobGrade, policies are
    company-wide reading material — every employee can view the list,
    not just admin/payroll_manager/manager.
    """

    __tablename__ = "policies"
    __table_args__ = (UniqueConstraint("org_id", "title", name="uq_policy_org_title"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
