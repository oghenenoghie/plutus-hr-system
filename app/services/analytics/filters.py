"""Analytics filters and period arithmetic, validated on the server.

Every analytics request is parsed into one AnalyticsFilters before any query
runs, so a hand-made URL is held to the same rules as the filter bar:
a bounded date range, a known comparison mode, enum values the models
accept and a country whose tax rules are approved. Department and location
IDs are checked against the database (and the caller's scope) separately,
in access.py, because that needs a session.
"""

import enum
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from app.compliance.multicountry import (
    TaxConfigurationError,
    get_country_profile,
    require_configured_country,
)
from app.models.employee import EmploymentType, LifecycleState
from app.models.pay_run import PayRunStatus
from app.schemas.analytics import CompareMode

MAX_RANGE_MONTHS = 36
DEFAULT_RANGE_MONTHS = 12
_EARLIEST = date(2000, 1, 1)
_MAX_IDS = 50

# "locked" is the default and only counts final figures; "validated" also
# includes runs that are approved but not yet locked. Draft runs are never
# final, and reversed runs are void.
PAYROLL_STATUS_FILTERS: dict[str, tuple[PayRunStatus, ...]] = {
    "locked": (PayRunStatus.LOCKED,),
    "validated": (PayRunStatus.LOCKED, PayRunStatus.VALIDATED),
}


class FilterError(ValueError):
    """An invalid filter value; the API answers 422 with this message."""


@dataclass(frozen=True)
class AnalyticsFilters:
    date_from: date
    date_to: date
    compare: CompareMode
    department_ids: tuple[uuid.UUID, ...] = ()
    location_ids: tuple[uuid.UUID, ...] = ()
    employment_types: tuple[EmploymentType, ...] = ()
    statuses: tuple[LifecycleState, ...] = ()
    payroll_status: str = "locked"
    country: str = "NG"

    @property
    def currency(self) -> str:
        return get_country_profile(self.country).currency

    @property
    def pay_run_statuses(self) -> tuple[PayRunStatus, ...]:
        return PAYROLL_STATUS_FILTERS[self.payroll_status]

    def comparison(self) -> "AnalyticsFilters | None":
        """The same filters over the comparison period, or None."""
        window = comparison_window(self.date_from, self.date_to, self.compare)
        if window is None:
            return None
        return AnalyticsFilters(
            date_from=window[0],
            date_to=window[1],
            compare=CompareMode.NONE,
            department_ids=self.department_ids,
            location_ids=self.location_ids,
            employment_types=self.employment_types,
            statuses=self.statuses,
            payroll_status=self.payroll_status,
            country=self.country,
        )


def month_start(day: date) -> date:
    return day.replace(day=1)


def month_end(day: date) -> date:
    following = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return following - timedelta(days=1)


def add_months(day: date, months: int) -> date:
    """The same day `months` later (negative for earlier), clamped to the
    last day of the target month (31 Jan + 1 month = 28/29 Feb)."""
    year, month_index = divmod(day.year * 12 + day.month - 1 + months, 12)
    first = date(year, month_index + 1, 1)
    return first.replace(day=min(day.day, month_end(first).day))


def months_spanned(date_from: date, date_to: date) -> int:
    """Calendar months touched by [date_from, date_to], inclusive."""
    return (date_to.year - date_from.year) * 12 + date_to.month - date_from.month + 1


def month_keys(date_from: date, date_to: date) -> list[str]:
    keys = []
    current = month_start(date_from)
    while current <= date_to:
        keys.append(current.strftime("%Y-%m"))
        current = add_months(current, 1)
    return keys


def month_buckets(date_from: date, date_to: date) -> list[tuple[str, date, date]]:
    """(key, first day, last day) for each month, clipped to the range."""
    buckets = []
    current = month_start(date_from)
    while current <= date_to:
        buckets.append(
            (current.strftime("%Y-%m"), max(current, date_from), min(month_end(current), date_to))
        )
        current = add_months(current, 1)
    return buckets


def _is_whole_months(date_from: date, date_to: date) -> bool:
    return date_from.day == 1 and date_to == month_end(date_to)


def comparison_window(
    date_from: date, date_to: date, mode: CompareMode
) -> tuple[date, date] | None:
    """The period a range is compared with.

    previous_period: the same length immediately before. A range of whole
    calendar months is compared with the same number of whole months (Q2
    with Q1, not with the 91 days before it); any other range with the same
    number of days. previous_year: the same dates a year earlier (29 Feb
    becomes 28 Feb).
    """
    if mode == CompareMode.NONE:
        return None
    if mode == CompareMode.PREVIOUS_YEAR:
        return add_months(date_from, -12), add_months(date_to, -12)
    if _is_whole_months(date_from, date_to):
        months = months_spanned(date_from, date_to)
        start = add_months(date_from, -months)
        return start, month_end(add_months(start, months - 1))
    length = (date_to - date_from).days + 1
    return date_from - timedelta(days=length), date_from - timedelta(days=1)


def default_range(today: date) -> tuple[date, date]:
    """The last 12 calendar months, this one included, up to today."""
    return add_months(month_start(today), -(DEFAULT_RANGE_MONTHS - 1)), today


def _parse_enum[E: enum.Enum](enum_cls: type[E], values: list[str], label: str) -> tuple[E, ...]:
    parsed = []
    for value in values:
        try:
            parsed.append(enum_cls(value))
        except ValueError as exc:
            raise FilterError(f"unknown {label}: {value!r}") from exc
    return tuple(dict.fromkeys(parsed))


def _parse_ids(values: list[uuid.UUID], label: str) -> tuple[uuid.UUID, ...]:
    if len(values) > _MAX_IDS:
        raise FilterError(f"at most {_MAX_IDS} {label} filters at once")
    return tuple(dict.fromkeys(values))


def parse_filters(
    *,
    today: date,
    date_from: date | None,
    date_to: date | None,
    compare: str | None,
    department_ids: list[uuid.UUID],
    location_ids: list[uuid.UUID],
    employment_types: list[str],
    statuses: list[str],
    payroll_status: str | None,
    country: str | None,
) -> AnalyticsFilters:
    # A missing end is today (or, for a future start, the end of its month);
    # a missing start is the default length back from the end.
    end = date_to or (today if date_from is None or date_from <= today else month_end(date_from))
    start = date_from or add_months(month_start(end), -(DEFAULT_RANGE_MONTHS - 1))
    if start > end:
        raise FilterError("date_from must not be after date_to")
    if start < _EARLIEST:
        raise FilterError(f"date_from must not be before {_EARLIEST.isoformat()}")
    if end > today + timedelta(days=366):
        raise FilterError("date_to must be within a year of today")
    if months_spanned(start, end) > MAX_RANGE_MONTHS:
        raise FilterError(f"the date range must span at most {MAX_RANGE_MONTHS} months")

    try:
        compare_mode = CompareMode(compare or CompareMode.PREVIOUS_PERIOD.value)
    except ValueError as exc:
        raise FilterError(f"unknown compare mode: {compare!r}") from exc

    status_key = payroll_status or "locked"
    if status_key not in PAYROLL_STATUS_FILTERS:
        raise FilterError(f"unknown payroll_status: {payroll_status!r}")

    country_code = (country or "NG").strip().upper()
    try:
        get_country_profile(country_code)
        # Fail closed: a catalogued country with no approved rules has no
        # figures to show, and inventing a zero would be wrong.
        require_configured_country(country_code, tax_type="analytics")
    except TaxConfigurationError as exc:
        raise FilterError(str(exc)) from exc
    except ValueError as exc:
        raise FilterError(f"unknown country: {country!r}") from exc

    return AnalyticsFilters(
        date_from=start,
        date_to=end,
        compare=compare_mode,
        department_ids=_parse_ids(department_ids, "department"),
        location_ids=_parse_ids(location_ids, "location"),
        employment_types=_parse_enum(EmploymentType, employment_types, "employment type"),
        statuses=_parse_enum(LifecycleState, statuses, "employment status"),
        payroll_status=status_key,
        country=country_code,
    )
