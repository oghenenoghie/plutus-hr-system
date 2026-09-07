import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class JobGrade(Base):
    """A salary band/level (e.g. "L1", "Senior") employees can be assigned
    to, independent of Department and Branch. level is a plain sort order
    (lower first) with no enforced meaning beyond that; min/max salary are
    advisory band bounds, not enforced against an employee's actual pay.
    """

    __tablename__ = "job_grades"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_job_grade_org_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    level: Mapped[int | None] = mapped_column(Integer)
    min_salary_minor: Mapped[int | None] = mapped_column(BigInteger)
    max_salary_minor: Mapped[int | None] = mapped_column(BigInteger)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
