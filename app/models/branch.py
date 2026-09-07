import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Branch(Base):
    """A physical office/site an org operates from — distinct from Department
    (an org's functional structure). An employee's branch and department are
    independent: two employees in the same department can sit in different
    branches. manager_id is nullable: a newly created branch has no head
    until one is assigned.
    """

    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_branch_org_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str | None] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(String(500))
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
