import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.public_holiday import PublicHoliday

# Long-standing federal Nigerian public holidays whose date never moves
# year to year — safe to seed without a live source, unlike a tax rate or
# threshold. Islamic holidays (Eid al-Fitr, Eid al-Kabir, Maulud) and
# Easter-based ones (Good Friday, Easter Monday) shift every year and are
# deliberately not seeded here — an admin adds those for the years they
# need via register_public_holiday.
_FIXED_DATE_HOLIDAY_NAMES: tuple[tuple[int, int, str], ...] = (
    (1, 1, "New Year's Day"),
    (5, 1, "Workers' Day"),
    (6, 12, "Democracy Day"),
    (10, 1, "Independence Day"),
    (12, 25, "Christmas Day"),
    (12, 26, "Boxing Day"),
)


def seed_default_public_holidays(
    db: Session, *, org_id: uuid.UUID, year: int
) -> list[PublicHoliday]:
    """Idempotent per (org, year): only inserts dates the org doesn't
    already have for that year, so it's safe to call against a year
    that's already been seeded or partially customized."""
    existing = set(
        db.scalars(
            select(PublicHoliday.holiday_date).where(
                PublicHoliday.org_id == org_id,
                PublicHoliday.holiday_date >= date(year, 1, 1),
                PublicHoliday.holiday_date <= date(year, 12, 31),
            )
        )
    )
    created = []
    for month, day, name in _FIXED_DATE_HOLIDAY_NAMES:
        holiday_date = date(year, month, day)
        if holiday_date in existing:
            continue
        holiday = PublicHoliday(org_id=org_id, holiday_date=holiday_date, name=name)
        db.add(holiday)
        created.append(holiday)
    if created:
        db.flush()
    return created


def register_public_holiday(
    db: Session, *, org_id: uuid.UUID, holiday_date: date, name: str
) -> PublicHoliday:
    holiday = PublicHoliday(org_id=org_id, holiday_date=holiday_date, name=name)
    db.add(holiday)
    db.flush()
    return holiday


def holidays_for_range(
    db: Session, *, org_id: uuid.UUID, start: date, end: date
) -> frozenset[date]:
    """The set app.domain.payroll.proration's working-days calculation
    treats as non-working, alongside weekends."""
    return frozenset(
        db.scalars(
            select(PublicHoliday.holiday_date).where(
                PublicHoliday.org_id == org_id,
                PublicHoliday.holiday_date >= start,
                PublicHoliday.holiday_date <= end,
            )
        )
    )
