import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_tenant_db, require_roles
from app.core.security import TokenClaims
from app.models.membership import Role
from app.models.public_holiday import PublicHoliday
from app.schemas.public_holidays import PublicHolidayCreate, PublicHolidayOut
from app.services.public_holidays import register_public_holiday, seed_default_public_holidays

router = APIRouter(prefix="/public-holidays", tags=["payroll"])

_MANAGE = require_roles(Role.ADMIN, Role.PAYROLL_MANAGER)


@router.post("", response_model=PublicHolidayOut, status_code=status.HTTP_201_CREATED)
def create_public_holiday(
    body: PublicHolidayCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> PublicHoliday:
    try:
        return register_public_holiday(db, org_id=claims.org_id, **body.model_dump())
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="this org already has a public holiday on that date",
        ) from exc


@router.post("/seed-defaults", response_model=list[PublicHolidayOut])
def seed_defaults(
    year: int = Query(..., description="Calendar year to seed the fixed-date holidays for"),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> list[PublicHoliday]:
    return seed_default_public_holidays(db, org_id=claims.org_id, year=year)


@router.get("", response_model=list[PublicHolidayOut])
def list_public_holidays(
    db: Session = Depends(get_tenant_db), claims: TokenClaims = Depends(_MANAGE)
) -> list[PublicHoliday]:
    return list(
        db.scalars(
            select(PublicHoliday)
            .where(PublicHoliday.org_id == claims.org_id)
            .order_by(PublicHoliday.holiday_date)
        )
    )


@router.delete("/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_public_holiday(
    holiday_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(_MANAGE),
) -> None:
    holiday = db.get(PublicHoliday, holiday_id)
    if holiday is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="holiday not found")
    db.delete(holiday)
