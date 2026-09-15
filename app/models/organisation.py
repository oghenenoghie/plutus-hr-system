import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.payroll.frequency import PayFrequency
from app.models.base import Base


class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rc_number: Mapped[str | None] = mapped_column(String(64))
    company_tin: Mapped[str | None] = mapped_column(String(64))
    # Onboarding defaults only — a starting point new-hire forms are
    # pre-filled with, never enforced on existing employees, who keep
    # whatever pay_frequency/PFA they were already set up with.
    default_pay_frequency: Mapped[PayFrequency] = mapped_column(
        Enum(
            PayFrequency,
            name="organisation_default_pay_frequency",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
        default=PayFrequency.MONTHLY,
    )
    default_pfa: Mapped[str | None] = mapped_column(String(255))
    # Nigerian states the org actually operates/employs in — informational
    # (drives which employees' PAYE the org expects to be routing to which
    # state IRS), not itself a source of any statutory figure; those still
    # only ever come from resolve_rule_version.
    states_of_operation: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
