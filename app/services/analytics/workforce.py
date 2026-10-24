"""Workforce analytics: headcount, hires, departures, turnover and the shape
of the workforce. Definitions: docs/analytics-metrics.md §1."""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Date, String, case, column, func, select, values
from sqlalchemy.orm import Session

from app.models.employee import EmploymentType, LifecycleState
from app.schemas.analytics import Breakdown, Metric, Trend, Unit, WorkforceOut
from app.services.analytics.access import AnalyticsAccess
from app.services.analytics.common import (
    NO_DEPARTMENT,
    NO_LOCATION,
    average,
    breakdown,
    build_meta,
    department_names,
    employed_on,
    employee_roster,
    location_names,
    metric,
    percent,
    row,
    series,
    top_rows,
    trend,
)
from app.services.analytics.filters import AnalyticsFilters, month_buckets, month_keys

HREF = "/analytics/workforce"

_TENURE_BANDS = (
    ("lt1", "Under 1 year", 0, 1),
    ("1to2", "1–2 years", 1, 2),
    ("2to5", "2–5 years", 2, 5),
    ("5to10", "5–10 years", 5, 10),
    ("10plus", "10 years or more", 10, None),
)
_AGE_BANDS = (
    ("lt25", "Under 25", 0, 25),
    ("25to34", "25–34", 25, 35),
    ("35to44", "35–44", 35, 45),
    ("45to54", "45–54", 45, 55),
    ("55plus", "55 and over", 55, None),
)

_EMPLOYMENT_TYPE_LABELS = {
    EmploymentType.PERMANENT: "Permanent",
    EmploymentType.FIXED_TERM: "Fixed term",
    EmploymentType.PART_TIME: "Part time",
    EmploymentType.INTERN: "Intern",
    EmploymentType.CONSULTANT: "Consultant",
}
_STATUS_LABELS = {
    LifecycleState.ACTIVE: "Active",
    LifecycleState.SUSPENDED: "Suspended",
    LifecycleState.TERMINATED: "Left in period",
}


def headcount_on(
    db: Session, org_id: uuid.UUID, filters: AnalyticsFilters, dates: list[tuple[str, date]]
) -> dict[str, int]:
    """Headcount on each of several days, in one query."""
    if not dates:
        return {}
    roster = employee_roster(filters, org_id)
    days = values(column("key", String), column("as_of", Date), name="as_of_dates").data(dates)
    stmt = (
        select(days.c.key, func.count(roster.c.id))
        .select_from(days)
        .outerjoin(
            roster,
            employed_on(
                roster.c.date_of_joining, roster.c.lifecycle_state, roster.c.left_on, days.c.as_of
            ),
        )
        .group_by(days.c.key)
    )
    return {key: count for key, count in db.execute(stmt).tuples()}


def hires_by_month(db: Session, org_id: uuid.UUID, filters: AnalyticsFilters) -> dict[str, int]:
    roster = employee_roster(filters, org_id)
    month = func.to_char(roster.c.date_of_joining, "YYYY-MM")
    stmt = (
        select(month, func.count())
        .where(roster.c.date_of_joining.between(filters.date_from, filters.date_to))
        .group_by(month)
    )
    return {key: count for key, count in db.execute(stmt).tuples()}


def departures_by_month(
    db: Session, org_id: uuid.UUID, filters: AnalyticsFilters
) -> dict[str, int]:
    roster = employee_roster(filters, org_id)
    month = func.to_char(roster.c.left_on, "YYYY-MM")
    stmt = (
        select(month, func.count())
        .where(roster.c.left_on.between(filters.date_from, filters.date_to))
        .group_by(month)
    )
    return {key: count for key, count in db.execute(stmt).tuples()}


def turnover_rate(departures: int, opening: int, closing: int) -> float | None:
    """Departures as a percentage of average headcount ((opening +
    closing) / 2). None when there was nobody to turn over."""
    return percent(departures, (opening + closing) / 2)


def _period_figures(
    db: Session, org_id: uuid.UUID, filters: AnalyticsFilters
) -> dict[str, float | int | None]:
    counts = headcount_on(
        db,
        org_id,
        filters,
        [("opening", filters.date_from - timedelta(days=1)), ("closing", filters.date_to)],
    )
    hires = sum(hires_by_month(db, org_id, filters).values())
    departures = sum(departures_by_month(db, org_id, filters).values())
    roster = employee_roster(filters, org_id)
    tenure_days = db.execute(
        select(
            func.count(roster.c.id),
            func.coalesce(func.sum(filters.date_to - roster.c.date_of_joining), 0),
        ).where(
            employed_on(
                roster.c.date_of_joining,
                roster.c.lifecycle_state,
                roster.c.left_on,
                filters.date_to,
            )
        )
    ).one()
    return {
        "opening": counts.get("opening", 0),
        "headcount": counts.get("closing", 0),
        "hires": hires,
        "departures": departures,
        "turnover": turnover_rate(departures, counts.get("opening", 0), counts.get("closing", 0)),
        "tenure_years": average(float(tenure_days[1]) / 365.25, tenure_days[0]),
    }


def active_now(db: Session, org_id: uuid.UUID, filters: AnalyticsFilters) -> int:
    roster = employee_roster(filters, org_id)
    return (
        db.scalar(select(func.count()).where(roster.c.lifecycle_state == LifecycleState.ACTIVE))
        or 0
    )


def workforce_kpis(db: Session, access: AnalyticsAccess, filters: AnalyticsFilters) -> list[Metric]:
    org_id = access.org_id
    now = _period_figures(db, org_id, filters)
    previous_filters = filters.comparison()
    before = _period_figures(db, org_id, previous_filters) if previous_filters else {}
    compare = previous_filters is not None
    return [
        metric(
            key="headcount",
            label="Total employees",
            unit=Unit.COUNT,
            value=now["headcount"],
            previous=before.get("headcount"),
            compare=compare,
            definition="Employees on the payroll on the last day of the period: joined on or "
            "before it and not yet past their termination date.",
            href=HREF,
            dataset="employees",
        ),
        metric(
            key="active",
            label="Active employees",
            unit=Unit.COUNT,
            value=active_now(db, org_id, filters),
            compare=False,
            definition="Employees whose status is Active today (not suspended or terminated). "
            "A current figure: status history isn't recorded, so it has no comparison.",
            href=HREF,
            dataset="employees",
        ),
        metric(
            key="hires",
            label="New hires",
            unit=Unit.COUNT,
            value=now["hires"],
            previous=before.get("hires"),
            compare=compare,
            definition="Employees whose date of joining falls in the period.",
            href=HREF,
            dataset="hires",
        ),
        metric(
            key="departures",
            label="Employees who left",
            unit=Unit.COUNT,
            value=now["departures"],
            previous=before.get("departures"),
            compare=compare,
            higher_is_better=False,
            definition="Employees whose final-settlement termination date falls in the period.",
            href=HREF,
            dataset="departures",
        ),
        metric(
            key="turnover",
            label="Turnover rate",
            unit=Unit.PERCENT,
            value=now["turnover"],
            previous=before.get("turnover"),
            compare=compare,
            higher_is_better=False,
            definition="Employees who left ÷ average headcount × 100, where average headcount is "
            "(headcount the day before the period + headcount on its last day) ÷ 2.",
            href=HREF,
            dataset="departures",
        ),
        metric(
            key="tenure",
            label="Average length of service",
            unit=Unit.YEARS,
            value=now["tenure_years"],
            previous=before.get("tenure_years"),
            compare=compare,
            definition="Mean years from date of joining to the period's last day, across "
            "the employees in headcount then.",
            href=HREF,
            dataset="employees",
        ),
    ]


def headcount_trend(db: Session, access: AnalyticsAccess, filters: AnalyticsFilters) -> Trend:
    buckets = month_buckets(filters.date_from, filters.date_to)
    counts = headcount_on(db, access.org_id, filters, [(key, end) for key, _, end in buckets])
    return trend(
        key="headcount",
        title="Headcount",
        unit=Unit.COUNT,
        series_list=[series("headcount", "Headcount", [k for k, _, _ in buckets], counts)],
        definition="Employees in headcount on the last day of each month (or the period's last "
        "day, for a month cut short).",
        dataset="employees",
    )


def _band_breakdown(
    db: Session,
    filters: AnalyticsFilters,
    org_id: uuid.UUID,
    *,
    date_column: str,
    bands: tuple[tuple[str, str, int, int | None], ...],
) -> list[tuple[str, int]]:
    roster = employee_roster(filters, org_id)
    source = roster.c[date_column]
    years = func.date_part("year", func.age(filters.date_to, source))
    whens = []
    for key, _, low, high in bands:
        condition = years >= low if high is None else years.between(low, high - 1)
        whens.append((condition, key))
    band = case((source.is_(None), "missing"), *whens, else_="missing")
    stmt = (
        select(band, func.count())
        .where(
            employed_on(
                roster.c.date_of_joining,
                roster.c.lifecycle_state,
                roster.c.left_on,
                filters.date_to,
            )
        )
        .group_by(band)
    )
    return [(key, count) for key, count in db.execute(stmt).tuples()]


def _group_counts(
    db: Session, filters: AnalyticsFilters, org_id: uuid.UUID, column_name: str
) -> list[tuple[Any, int]]:
    roster = employee_roster(filters, org_id)
    key = roster.c[column_name]
    stmt = (
        select(key, func.count())
        .where(
            employed_on(
                roster.c.date_of_joining,
                roster.c.lifecycle_state,
                roster.c.left_on,
                filters.date_to,
            )
        )
        .group_by(key)
    )
    return [(value, count) for value, count in db.execute(stmt).tuples()]


def headcount_by_department(
    db: Session, access: AnalyticsAccess, filters: AnalyticsFilters
) -> Breakdown:
    names = department_names(db, access.org_id)
    rows = [
        row(
            dept or "none",
            names.get(dept, NO_DEPARTMENT) if dept else NO_DEPARTMENT,
            count,
            count=count,
        )
        for dept, count in _group_counts(db, filters, access.org_id, "department_id")
    ]
    return breakdown(
        key="by_department",
        title="Headcount by department",
        unit=Unit.COUNT,
        rows=rows,
        definition="Employees in headcount on the period's last day, by their current department.",
        dataset="employees",
    )


def workforce(db: Session, access: AnalyticsAccess, filters: AnalyticsFilters) -> WorkforceOut:
    org_id = access.org_id
    months = month_keys(filters.date_from, filters.date_to)
    buckets = month_buckets(filters.date_from, filters.date_to)

    # Headcount the day before each month and on its last day, for the trend
    # and for each month's turnover rate.
    days: list[tuple[str, date]] = []
    for key, start, end in buckets:
        days.append((f"{key}:open", start - timedelta(days=1)))
        days.append((f"{key}:close", end))
    counts = headcount_on(db, org_id, filters, days)
    hires = hires_by_month(db, org_id, filters)
    departures = departures_by_month(db, org_id, filters)
    turnover = {
        key: turnover_rate(
            departures.get(key, 0), counts.get(f"{key}:open", 0), counts.get(f"{key}:close", 0)
        )
        for key in months
    }

    location_lookup = location_names(db, org_id)
    by_location = [
        row(
            loc or "none",
            location_lookup.get(loc, NO_LOCATION) if loc else NO_LOCATION,
            count,
            count=count,
        )
        for loc, count in _group_counts(db, filters, org_id, "branch_id")
    ]
    by_type = [
        row(kind.value, _EMPLOYMENT_TYPE_LABELS[kind], count, count=count)
        for kind, count in _group_counts(db, filters, org_id, "employment_type")
    ]
    job_titles = top_rows(
        [
            row(title or "none", title or "No job title", count, count=count)
            for title, count in _group_counts(db, filters, org_id, "job_title")
        ],
        10,
    )

    roster = employee_roster(filters, org_id)
    status_rows = db.execute(
        select(roster.c.lifecycle_state, func.count())
        .where(
            (roster.c.lifecycle_state != LifecycleState.TERMINATED)
            | roster.c.left_on.between(filters.date_from, filters.date_to)
        )
        .group_by(roster.c.lifecycle_state)
    ).tuples()
    by_status = [
        row(state.value, _STATUS_LABELS[state], count, count=count) for state, count in status_rows
    ]

    tenure = dict(
        _band_breakdown(db, filters, org_id, date_column="date_of_joining", bands=_TENURE_BANDS)
    )
    ages = dict(_band_breakdown(db, filters, org_id, date_column="date_of_birth", bands=_AGE_BANDS))

    return WorkforceOut(
        meta=build_meta(
            "workforce",
            filters,
            access,
            notes=[
                (
                    "Department, location, job title and employment type are each employee's "
                    "current values; employee history records status and pay changes only."
                ),
            ],
        ),
        kpis=workforce_kpis(db, access, filters),
        headcount_trend=trend(
            key="headcount",
            title="Headcount",
            unit=Unit.COUNT,
            series_list=[
                series(
                    "headcount",
                    "Headcount",
                    months,
                    {k: counts.get(f"{k}:close", 0) for k in months},
                )
            ],
            definition="Employees in headcount on the last day of each month (or the period's "
            "last day, for a month cut short).",
            dataset="employees",
        ),
        hires_vs_departures=trend(
            key="hires_vs_departures",
            title="Hires and departures",
            unit=Unit.COUNT,
            series_list=[
                series("hires", "Hires", months, hires),
                series("departures", "Departures", months, departures),
            ],
            definition="Joining dates and final-settlement termination dates, by month.",
            dataset="hires",
        ),
        turnover_trend=trend(
            key="turnover",
            title="Monthly turnover rate",
            unit=Unit.PERCENT,
            series_list=[series("turnover", "Turnover rate", months, turnover, missing=None)],
            definition="Each month's departures ÷ its average headcount × 100.",
            dataset="departures",
        ),
        by_department=headcount_by_department(db, access, filters),
        by_job_title=breakdown(
            key="by_job_title",
            title="Headcount by job title",
            unit=Unit.COUNT,
            rows=job_titles,
            definition="Employees in headcount on the period's last day; the ten largest titles, "
            "the rest as Other.",
            dataset="employees",
            sort=False,
        ),
        by_status=breakdown(
            key="by_status",
            title="Employment status",
            unit=Unit.COUNT,
            rows=by_status,
            definition="Employees by their status today; Left in period counts only those whose "
            "termination date falls in the period.",
            dataset="employees",
        ),
        by_location=breakdown(
            key="by_location",
            title="Headcount by location",
            unit=Unit.COUNT,
            rows=by_location,
            definition="Employees in headcount on the period's last day, by their branch.",
            dataset="employees",
        ),
        by_employment_type=breakdown(
            key="by_employment_type",
            title="Headcount by employment type",
            unit=Unit.COUNT,
            rows=by_type,
            definition="Employees in headcount on the period's last day, by employment type.",
            dataset="employees",
        ),
        tenure_bands=breakdown(
            key="tenure_bands",
            title="Length of service",
            unit=Unit.COUNT,
            rows=[
                row(key, label, tenure.get(key, 0), count=tenure.get(key, 0))
                for key, label, _, _ in _TENURE_BANDS
            ],
            definition="Completed years from date of joining to the period's last day.",
            sort=False,
        ),
        age_bands=breakdown(
            key="age_bands",
            title="Age distribution",
            unit=Unit.COUNT,
            rows=[
                *(
                    row(key, label, ages.get(key, 0), count=ages.get(key, 0), protect=True)
                    for key, label, _, _ in _AGE_BANDS
                ),
                row(
                    "missing", "Not recorded", ages.get("missing", 0), count=ages.get("missing", 0)
                ),
            ],
            definition="Completed years of age on the period's last day. A band of fewer than "
            "3 people is hidden so no one's age can be inferred.",
            sort=False,
        ),
    )
