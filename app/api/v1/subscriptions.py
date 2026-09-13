from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.membership import Role
from app.schemas.subscriptions import ChangePlanRequest, SubscriptionOut, UsageSummaryOut
from app.services.subscriptions import (
    cancel_subscription,
    change_plan,
    get_or_create_subscription,
    usage_summary,
)

router = APIRouter(prefix="/subscription", tags=["subscription"])

_MANAGE = require_roles(Role.ADMIN)


@router.get("", response_model=SubscriptionOut)
def get_subscription(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_MANAGE)
) -> SubscriptionOut:
    subscription = get_or_create_subscription(db, claims.org_id, as_of=datetime.now(UTC).date())
    return SubscriptionOut.model_validate(subscription)


@router.get("/usage", response_model=UsageSummaryOut)
def get_usage(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_MANAGE)
) -> UsageSummaryOut:
    subscription = get_or_create_subscription(db, claims.org_id, as_of=datetime.now(UTC).date())
    summary = usage_summary(db, subscription)
    return UsageSummaryOut(
        plan_code=summary.plan_code,
        plan_name=summary.plan_name,
        employee_count=summary.employee_count,
        employee_limit=summary.employee_limit,
        over_limit=summary.over_limit,
        monthly_price_minor=summary.monthly_price_minor,
    )


@router.post("/change-plan", response_model=SubscriptionOut)
def post_change_plan(
    body: ChangePlanRequest,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> SubscriptionOut:
    subscription = get_or_create_subscription(db, claims.org_id, as_of=datetime.now(UTC).date())
    try:
        change_plan(db, subscription, plan_code=body.plan_code)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SubscriptionOut.model_validate(subscription)


@router.post("/cancel", response_model=SubscriptionOut)
def post_cancel(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_MANAGE)
) -> SubscriptionOut:
    subscription = get_or_create_subscription(db, claims.org_id, as_of=datetime.now(UTC).date())
    try:
        cancel_subscription(db, subscription)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SubscriptionOut.model_validate(subscription)
