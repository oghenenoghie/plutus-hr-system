import enum
from dataclasses import dataclass


class PlanCode(str, enum.Enum):
    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


@dataclass(frozen=True)
class SubscriptionPlan:
    code: PlanCode
    name: str
    employee_limit: int | None  # None means unlimited
    monthly_price_minor: int


# Illustrative placeholder pricing/limits for a platform operator to
# configure for real — unlike a PAYE/WHT rate, there's no statutory
# source for a SaaS price, so these aren't standing in for anything
# authoritative; they exist so plan/usage tracking has real numbers to
# work with.
PLAN_CATALOG: dict[PlanCode, SubscriptionPlan] = {
    PlanCode.FREE: SubscriptionPlan(
        code=PlanCode.FREE, name="Free", employee_limit=5, monthly_price_minor=0
    ),
    PlanCode.STARTER: SubscriptionPlan(
        code=PlanCode.STARTER, name="Starter", employee_limit=25, monthly_price_minor=15_000_00
    ),
    PlanCode.PROFESSIONAL: SubscriptionPlan(
        code=PlanCode.PROFESSIONAL,
        name="Professional",
        employee_limit=100,
        monthly_price_minor=45_000_00,
    ),
    PlanCode.ENTERPRISE: SubscriptionPlan(
        code=PlanCode.ENTERPRISE,
        name="Enterprise",
        employee_limit=None,
        monthly_price_minor=120_000_00,
    ),
}


def is_over_employee_limit(plan_code: PlanCode, employee_count: int) -> bool:
    limit = PLAN_CATALOG[plan_code].employee_limit
    return limit is not None and employee_count > limit
