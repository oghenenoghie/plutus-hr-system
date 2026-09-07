import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Department(Base):
    """An org's internal structure, independent of the reporting-line
    hierarchy already captured by Employee.manager_id — an employee's
    manager and their department head are frequently different people.
    manager_id is nullable: a newly created department has no head until
    one is assigned.
    """

    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_department_org_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
