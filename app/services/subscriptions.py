import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.recurrence import add_months
from app.domain.subscription_plans import PLAN_CATALOG, PlanCode, is_over_employee_limit
from app.models.employee import Employee
from app.models.subscription import Subscription, SubscriptionStatus


def get_or_create_subscription(
    db: Session, org_id: uuid.UUID, *, as_of: date, default_plan: PlanCode = PlanCode.FREE
) -> Subscription:
    subscription = db.scalar(select(Subscription).where(Subscription.org_id == org_id))
    if subscription is not None:
        return subscription

    subscription = Subscription(
        org_id=org_id,
        plan_code=default_plan,
        current_period_end=add_months(as_of, 1),
    )
    db.add(subscription)
    db.flush()
    return subscription


def change_plan(db: Session, subscription: Subscription, *, plan_code: PlanCode) -> Subscription:
    if subscription.status == SubscriptionStatus.CANCELED:
        raise ValueError("cannot change the plan of a canceled subscription")
    subscription.plan_code = plan_code
    db.add(subscription)
    db.flush()
    return subscription


def cancel_subscription(db: Session, subscription: Subscription) -> Subscription:
    if subscription.status == SubscriptionStatus.CANCELED:
        raise ValueError("subscription is already canceled")
    subscription.status = SubscriptionStatus.CANCELED
    db.add(subscription)
    db.flush()
    return subscription


@dataclass(frozen=True)
class UsageSummary:
    plan_code: PlanCode
    plan_name: str
    employee_count: int
    employee_limit: int | None
    over_limit: bool
    monthly_price_minor: int


def usage_summary(db: Session, subscription: Subscription) -> UsageSummary:
    employee_count = int(
        db.scalar(
            select(func.count()).select_from(Employee).where(Employee.org_id == subscription.org_id)
        )
        or 0
    )
    plan = PLAN_CATALOG[subscription.plan_code]
    return UsageSummary(
        plan_code=plan.code,
        plan_name=plan.name,
        employee_count=employee_count,
        employee_limit=plan.employee_limit,
        over_limit=is_over_employee_limit(plan.code, employee_count),
        monthly_price_minor=plan.monthly_price_minor,
    )
