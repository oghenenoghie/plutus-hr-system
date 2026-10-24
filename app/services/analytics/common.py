"""Arithmetic and query pieces shared by every analytics section."""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Subquery

from app.models.branch import Branch
from app.models.department import Department
from app.models.employee import Employee, LifecycleState
from app.models.final_settlement import FinalSettlement
from app.schemas.analytics import (
    AppliedFilters,
    Breakdown,
    BreakdownRow,
    Meta,
    Metric,
    PeriodOut,
    Series,
    SeriesPoint,
    Trend,
    Unit,
    Unsupported,
)
from app.services.analytics.access import AnalyticsAccess
from app.services.analytics.filters import AnalyticsFilters, comparison_window, month_keys

# A breakdown group smaller than this is hidden from a caller who can't
# already see individual pay (or individual ratings), so an average or total
# can't reveal one person's figure. See docs/analytics-security.md §4.
MIN_GROUP_SIZE = 3

NO_DEPARTMENT = "No department"
NO_LOCATION = "No location"

Number = int | float


def change(current: Number | None, previous: Number | None) -> tuple[float | None, float | None]:
    """(absolute change, percentage change). The percentage is None when
    there is nothing to compare with, or the previous value is zero."""
    if current is None or previous is None:
        return None, None
    delta = float(current) - float(previous)
    if previous == 0:
        return delta, None
    return delta, round(delta / abs(float(previous)) * 100, 2)


def percent(numerator: Number, denominator: Number) -> float | None:
    """numerator / denominator as a percentage to two places; None for a
    zero denominator rather than a misleading 0%."""
    if not denominator:
        return None
    return round(float(numerator) / float(denominator) * 100, 2)


def average(total: Number, count: Number) -> float | None:
    if not count:
        return None
    return round(float(total) / float(count), 2)


def metric(
    *,
    key: str,
    label: str,
    unit: Unit,
    value: Number | None,
    previous: Number | None = None,
    compare: bool = True,
    currency: str | None = None,
    higher_is_better: bool | None = None,
    definition: str,
    href: str | None = None,
    dataset: str | None = None,
    text_value: str | None = None,
    note: str | None = None,
) -> Metric:
    delta, delta_pct = change(value, previous) if compare else (None, None)
    return Metric(
        key=key,
        label=label,
        unit=unit,
        value=None if value is None else float(value),
        previous_value=None if (previous is None or not compare) else float(previous),
        change=delta,
        change_pct=delta_pct,
        currency=currency,
        higher_is_better=higher_is_better,
        text_value=text_value,
        definition=definition,
        href=href,
        dataset=dataset,
        note=note,
    )


def series(
    key: str,
    label: str,
    months: Sequence[str],
    values: Mapping[str, Number | None],
    *,
    missing: Number | None = 0,
) -> Series:
    """One value per month; a month with no row takes `missing` (0 for
    counts, None where "no data" must not read as zero)."""
    points = []
    for month in months:
        value = values.get(month, missing)
        points.append(SeriesPoint(period=month, value=None if value is None else float(value)))
    return Series(key=key, label=label, points=points)


def trend(
    *,
    key: str,
    title: str,
    unit: Unit,
    series_list: list[Series],
    definition: str,
    currency: str | None = None,
    stacked: bool = False,
    dataset: str | None = None,
) -> Trend:
    return Trend(
        key=key,
        title=title,
        unit=unit,
        currency=currency,
        stacked=stacked,
        series=series_list,
        definition=definition,
        dataset=dataset,
    )


def breakdown(
    *,
    key: str,
    title: str,
    unit: Unit,
    rows: Iterable[BreakdownRow],
    definition: str,
    currency: str | None = None,
    dataset: str | None = None,
    sort: bool = True,
) -> Breakdown:
    ordered = list(rows)
    if sort:
        ordered.sort(key=lambda row: (row.suppressed, -(row.value or 0), row.label))
    return Breakdown(
        key=key,
        title=title,
        unit=unit,
        currency=currency,
        rows=ordered,
        definition=definition,
        dataset=dataset,
    )


def row(
    key: object,
    label: str,
    value: Number | None,
    *,
    count: int | None = None,
    protect: bool = False,
) -> BreakdownRow:
    """A breakdown row; with protect=True a group of 1 or 2 keeps its
    count but loses its value (an empty group reveals nothing)."""
    if protect and count is not None and 0 < count < MIN_GROUP_SIZE:
        return BreakdownRow(key=str(key), label=label, value=None, count=count, suppressed=True)
    return BreakdownRow(
        key=str(key),
        label=label,
        value=None if value is None else float(value),
        count=count,
    )


def top_rows(
    rows: list[BreakdownRow], limit: int, other_label: str = "Other"
) -> list[BreakdownRow]:
    """The `limit` largest rows, with the rest folded into one "Other" row
    (counts and values summed)."""
    ranked = sorted(rows, key=lambda r: (-(r.value or 0), r.label))
    if len(ranked) <= limit:
        return ranked
    head, tail = ranked[: limit - 1], ranked[limit - 1 :]
    other_value = sum(r.value or 0 for r in tail)
    other_count = sum(r.count or 0 for r in tail)
    return [
        *head,
        BreakdownRow(key="other", label=other_label, value=other_value, count=other_count),
    ]


def employee_conditions(filters: AnalyticsFilters) -> list[ColumnElement[bool]]:
    """The employee filters (department, location, type, current status) as
    WHERE clauses on Employee. A department manager's filters already carry
    their departments (access.scoped_filters)."""
    conditions: list[ColumnElement[bool]] = []
    if filters.department_ids:
        conditions.append(Employee.department_id.in_(filters.department_ids))
    if filters.location_ids:
        conditions.append(Employee.branch_id.in_(filters.location_ids))
    if filters.employment_types:
        conditions.append(Employee.employment_type.in_(filters.employment_types))
    if filters.statuses:
        conditions.append(Employee.lifecycle_state.in_(filters.statuses))
    return conditions


def departures_subquery(org_id: uuid.UUID) -> Subquery:
    """Each terminated employee's departure date. Termination only happens
    through a final settlement, so its termination_date is the authority."""
    return (
        select(
            FinalSettlement.employee_id.label("employee_id"),
            func.min(FinalSettlement.termination_date).label("left_on"),
        )
        .where(FinalSettlement.org_id == org_id)
        .group_by(FinalSettlement.employee_id)
        .subquery("departures")
    )


def employed_on(joined: Any, state: Any, left_on: Any, as_of: Any) -> ColumnElement[bool]:
    """An employee is in headcount on a day from their joining date through
    their termination date. A terminated employee with no settlement (no
    known departure date) is not counted on any day."""
    return and_(
        joined <= as_of,
        or_(
            and_(left_on.is_(None), state != LifecycleState.TERMINATED),
            left_on >= as_of,
        ),
    )


def employee_roster(filters: AnalyticsFilters, org_id: uuid.UUID) -> Subquery:
    """The in-scope employees with their departure date (None if still
    employed), as one subquery every workforce query reads from."""
    departures = departures_subquery(org_id)
    return (
        select(
            Employee.id.label("id"),
            Employee.department_id.label("department_id"),
            Employee.branch_id.label("branch_id"),
            Employee.job_title.label("job_title"),
            Employee.employment_type.label("employment_type"),
            Employee.lifecycle_state.label("lifecycle_state"),
            Employee.date_of_joining.label("date_of_joining"),
            Employee.date_of_birth.label("date_of_birth"),
            Employee.annual_leave_entitlement_days.label("leave_entitlement"),
            departures.c.left_on.label("left_on"),
        )
        .outerjoin(departures, departures.c.employee_id == Employee.id)
        .where(Employee.org_id == org_id, *employee_conditions(filters))
        .subquery("roster")
    )


def scoped_employees(filters: AnalyticsFilters, org_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    return select(Employee.id).where(Employee.org_id == org_id, *employee_conditions(filters))


def department_names(db: Session, org_id: uuid.UUID) -> dict[uuid.UUID, str]:
    stmt = select(Department.id, Department.name).where(Department.org_id == org_id)
    return {key: name for key, name in db.execute(stmt).tuples()}


def location_names(db: Session, org_id: uuid.UUID) -> dict[uuid.UUID, str]:
    return {
        key: name
        for key, name in db.execute(
            select(Branch.id, Branch.name).where(Branch.org_id == org_id)
        ).tuples()
    }


def build_meta(
    section: str,
    filters: AnalyticsFilters,
    access: AnalyticsAccess,
    *,
    notes: list[str] | None = None,
    unsupported: list[Unsupported] | None = None,
) -> Meta:
    window = comparison_window(filters.date_from, filters.date_to, filters.compare)
    return Meta(
        section=section,
        period=PeriodOut(
            date_from=filters.date_from,
            date_to=filters.date_to,
            compare=filters.compare,
            compare_from=window[0] if window else None,
            compare_to=window[1] if window else None,
            months=month_keys(filters.date_from, filters.date_to),
        ),
        filters=AppliedFilters(
            department_ids=list(filters.department_ids),
            location_ids=list(filters.location_ids),
            employment_types=[t.value for t in filters.employment_types],
            statuses=[s.value for s in filters.statuses],
            payroll_status=filters.payroll_status,
            country=filters.country,
        ),
        currency=filters.currency,
        department_scope=list(access.department_scope)
        if access.department_scope is not None
        else None,
        generated_at=datetime.now(UTC),
        notes=notes or [],
        unsupported=unsupported or [],
    )
