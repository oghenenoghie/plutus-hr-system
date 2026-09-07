import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class JobPostingStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class JobPosting(Base):
    """An open (or since-closed) role an org is hiring for. department_id is
    nullable — a posting can exist before the hiring department is finalised.
    closed_date is set when status flips to CLOSED; nothing enforces this
    at the DB level (same as other status/timestamp pairs in this codebase),
    the API is the single writer.
    """

    __tablename__ = "job_postings"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL")
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[JobPostingStatus] = mapped_column(
        Enum(
            JobPostingStatus,
            name="job_posting_status",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
        default=JobPostingStatus.OPEN,
    )
    opened_date: Mapped[date] = mapped_column(Date, nullable=False)
    closed_date: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
