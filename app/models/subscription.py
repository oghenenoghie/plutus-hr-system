import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.subscription_plans import PlanCode
from app.models.base import Base


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"


class Subscription(Base):
    """One org's plan and billing status. This app has no payment
    processor integration — plan_code and monthly_price_minor (see
    app.domain.subscription_plans.PLAN_CATALOG) are record-keeping, not a
    live billing charge; changing the plan or marking a subscription
    past_due/canceled is a direct admin action here, not driven by a
    webhook from anywhere. One subscription per org (org_id unique) — a
    plan change updates this row rather than creating a new one, since
    unlike Bill/Invoice there's no append-only requirement on billing
    state itself.
    """

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    plan_code: Mapped[PlanCode] = mapped_column(
        Enum(
            PlanCode, name="subscription_plan_code", values_callable=lambda m: [x.value for x in m]
        ),
        nullable=False,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(
            SubscriptionStatus,
            name="subscription_status",
            values_callable=lambda m: [x.value for x in m],
        ),
        nullable=False,
        default=SubscriptionStatus.ACTIVE,
    )
    current_period_end: Mapped[date] = mapped_column(Date, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
