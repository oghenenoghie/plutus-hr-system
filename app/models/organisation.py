import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.compliance.multicountry import get_country_profile
from app.domain.payroll.frequency import PayFrequency
from app.models.base import Base


class Organisation(Base):
    __tablename__ = "organisations"
    __table_args__ = (
        CheckConstraint("country_code ~ '^[A-Z]{2}$'", name="ck_organisations_country_code_iso"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rc_number: Mapped[str | None] = mapped_column(String(64))
    company_tin: Mapped[str | None] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(String(500))
    # ISO 3166-1 alpha-2. Selects the statutory rules every calculation uses
    # (app/services/jurisdiction.py) and, through the country's profile, the
    # currency. Any catalogued country can be chosen; payroll and statutory
    # tax refuse one whose rules aren't approved.
    country_code: Mapped[str] = mapped_column(
        String(2), nullable=False, default="NG", server_default="NG"
    )
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

    @property
    def currency(self) -> str:
        """The ISO 4217 currency every amount of this organisation is in,
        from its country's profile."""
        return get_country_profile(self.country_code).currency
