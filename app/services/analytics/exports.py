"""Lays an analytics section (or a drill-down dataset) out as a ReportTable
for CSV, XLSX or PDF, with the report's metadata on top: organisation,
period, comparison, filters, currency, when it was generated, and the
definitions of what it shows. The figures are the same objects the screen
renders, so an export can't disagree with the dashboard."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel

from app.compliance.multicountry import get_country_profile
from app.domain.money import minor_units_exponent
from app.schemas.analytics import (
    Breakdown,
    BudgetActualRow,
    DeadlineOut,
    Meta,
    Metric,
    RecordColumn,
    Trend,
    Unit,
)
from app.services.analytics.filters import AnalyticsFilters
from app.services.report_export import ReportTable, money

_WAT = timezone(timedelta(hours=1))
_UNIT_LABELS = {
    Unit.COUNT: "count",
    Unit.PERCENT: "%",
    Unit.DAYS: "days",
    Unit.HOURS: "hours",
    Unit.YEARS: "years",
    Unit.RATING: "rating",
    Unit.TEXT: "",
}


def _number(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".") if value % 1 else f"{int(value):,}"


def format_value(value: float | None, unit: Unit, currency: str | None) -> str:
    if value is None:
        return ""
    if unit == Unit.MONEY:
        return money(round(value), currency or "NGN")
    if unit == Unit.PERCENT:
        return f"{value:.2f}"
    return _number(value)


def _decimal_places(currency: str) -> str:
    places = minor_units_exponent(currency)
    return "whole units" if places == 0 else f"{places} decimal places"


def _unit(unit: Unit, currency: str | None) -> str:
    return currency or "" if unit == Unit.MONEY else _UNIT_LABELS[unit]


def metadata_lines(
    meta: Meta,
    *,
    organisation: str,
    department_names: dict[str, str],
    location_names: dict[str, str],
    role: str,
) -> list[str]:
    period = meta.period
    filters = meta.filters
    compared = (
        f" (compared with {period.compare_from} to {period.compare_to})"
        if period.compare_from
        else ""
    )

    def names(ids: list[Any], lookup: dict[str, str]) -> str:
        return ", ".join(lookup.get(str(i), str(i)) for i in ids) if ids else "all"

    lines = [
        f"Organisation: {organisation}",
        f"Period: {period.date_from} to {period.date_to}{compared}",
        "Filters: "
        + "; ".join(
            [
                f"departments {names(filters.department_ids, department_names)}",
                f"locations {names(filters.location_ids, location_names)}",
                f"employment types {', '.join(filters.employment_types) or 'all'}",
                f"statuses {', '.join(filters.statuses) or 'all'}",
                f"payroll status {filters.payroll_status}",
                f"country {get_country_profile(filters.country).name}",
            ]
        ),
        f"Currency: {meta.currency}; amounts to {_decimal_places(meta.currency)}, without a symbol",
        f"Generated: {meta.generated_at.astimezone(_WAT):%Y-%m-%d %H:%M} WAT, for the {role} role",
    ]
    if meta.department_scope is not None:
        lines.append("Scope: limited to the departments you head")
    lines += [f"Note: {note}" for note in meta.notes]
    lines += [f"Not available: {u.label}. {u.reason}" for u in meta.unsupported]
    return lines


_HEADERS = ["Part", "Item", "Period or category", "Value", "Unit", "Detail"]


def _kpi_rows(metrics: list[Metric]) -> list[list[str]]:
    rows = []
    for m in metrics:
        detail = []
        if m.previous_value is not None:
            detail.append(f"previous {format_value(m.previous_value, m.unit, m.currency)}")
        if m.change_pct is not None:
            detail.append(f"change {m.change_pct:+.2f}%")
        if m.note:
            detail.append(m.note)
        value = m.text_value if m.unit == Unit.TEXT else format_value(m.value, m.unit, m.currency)
        rows.append(
            ["KPI", m.label, "Period", value or "", _unit(m.unit, m.currency), "; ".join(detail)]
        )
    return rows


def _trend_rows(chart: Trend) -> list[list[str]]:
    return [
        [
            chart.title,
            s.label,
            point.period,
            format_value(point.value, chart.unit, chart.currency),
            _unit(chart.unit, chart.currency),
            "",
        ]
        for s in chart.series
        for point in s.points
    ]


def _breakdown_rows(chart: Breakdown) -> list[list[str]]:
    rows = []
    for r in chart.rows:
        detail = (
            "hidden: fewer than 3 people"
            if r.suppressed
            else (f"count {r.count}" if r.count is not None else "")
        )
        rows.append(
            [
                chart.title,
                r.label,
                "",
                format_value(r.value, chart.unit, chart.currency),
                _unit(chart.unit, chart.currency),
                detail,
            ]
        )
    return rows


def section_table(
    title: str, filename: str, response: BaseModel, metadata: list[str], currency: str
) -> ReportTable:
    rows: list[list[str]] = []
    definitions: list[list[str]] = []
    for name in type(response).model_fields:
        value = getattr(response, name)
        if name == "kpis":
            rows += _kpi_rows(value)
            definitions += [["Definition", m.label, "", "", "", m.definition] for m in value]
        elif isinstance(value, Trend):
            rows += _trend_rows(value)
            definitions.append(["Definition", value.title, "", "", "", value.definition])
        elif isinstance(value, Breakdown):
            rows += _breakdown_rows(value)
            definitions.append(["Definition", value.title, "", "", "", value.definition])
        elif isinstance(value, list) and value and isinstance(value[0], DeadlineOut):
            rows += [
                [
                    "Upcoming deadlines",
                    f"{d.scheme} ({d.authority})",
                    f"due {d.due_date}",
                    money(d.amount_minor, currency),
                    currency,
                    f"{d.status}{', overdue' if d.overdue else ''}; period {d.period_start} to {d.period_end}",
                ]
                for d in value
            ]
        elif isinstance(value, list) and value and isinstance(value[0], BudgetActualRow):
            rows += [
                [
                    "Budget vs actual",
                    b.name,
                    f"{b.period_start} to {b.period_end}",
                    money(b.actual_minor, currency),
                    currency,
                    f"budgeted {money(b.budgeted_minor, currency)}; variance {money(b.variance_minor, currency)}",
                ]
                for b in value
            ]
    return ReportTable(
        title=title,
        filename=filename,
        headers=_HEADERS,
        rows=rows + definitions,
        subtitle=metadata,
        numeric={3},
    )


def records_table(
    title: str,
    filename: str,
    columns: list[RecordColumn],
    rows: list[dict[str, Any]],
    metadata: list[str],
    *,
    truncated: bool,
    limit: int,
    currency: str,
) -> ReportTable:
    def cell(column: RecordColumn, value: Any) -> str:
        if value is None:
            return ""
        if column.kind == "money":
            return money(int(value), currency)
        return str(value)

    notes = [*metadata]
    if truncated:
        notes.append(f"Note: only the first {limit:,} rows; narrow the filters for the rest.")
    return ReportTable(
        title=title,
        filename=filename,
        headers=[c.label for c in columns],
        rows=[[cell(c, r.get(c.key)) for c in columns] for r in rows],
        subtitle=notes,
        numeric={i for i, c in enumerate(columns) if c.kind in ("money", "count", "days", "hours")},
    )


def export_filename(name: str, filters: AnalyticsFilters) -> str:
    return f"analytics-{name}-{filters.date_from:%Y%m%d}-{filters.date_to:%Y%m%d}"


def generated_now() -> datetime:
    return datetime.now(UTC)
