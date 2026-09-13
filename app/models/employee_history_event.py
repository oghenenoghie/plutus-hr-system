import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EmployeeHistoryEventType(str, enum.Enum):
    STATUS_CHANGE = "status_change"
    COMPENSATION_CHANGE = "compensation_change"


class EmployeeHistoryEvent(Base):
    """An append-only record of what changed on an employee — lifecycle_state
    (STATUS_CHANGE) or any pay component (COMPENSATION_CHANGE) — and what it
    changed from/to, since Employee itself only ever holds the current
    value. detail holds {"from": {...}, "to": {...}}, one key per field that
    actually changed in that update. Never edited or deleted (see
    forbid_update_delete) — a correction is a new event, same as every
    other audit-shaped table in this codebase.
    """

    __tablename__ = "employee_history_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[EmployeeHistoryEventType] = mapped_column(
        Enum(
            EmployeeHistoryEventType,
            name="employee_history_event_type",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
