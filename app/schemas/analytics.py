"""Response contracts for Analytics & Insights (docs/analytics-architecture.md).

Three building blocks carry every figure: a Metric (one KPI, with its
comparison), a Trend (one or more Series over the same month buckets) and a
Breakdown (a value per category). Each section response names its own
charts as fields, so a payroll chart can never be mistaken for a headcount
one. Every block states its unit and, for money, its currency; amounts are
integer minor units like everywhere else in the API.
"""

import enum
import uuid
from datetime import date, datetime

from pydantic import BaseModel


class Unit(enum.StrEnum):
    COUNT = "count"
    PERCENT = "percent"
    MONEY = "money"  # integer minor units of `currency`
    DAYS = "days"
    HOURS = "hours"
    YEARS = "years"
    RATING = "rating"
    TEXT = "text"


class CompareMode(enum.StrEnum):
    PREVIOUS_PERIOD = "previous_period"
    PREVIOUS_YEAR = "previous_year"
    NONE = "none"


class Section(enum.StrEnum):
    WORKFORCE = "workforce"
    PAYROLL = "payroll"
    ATTENDANCE = "attendance"
    LEAVE = "leave"
    RECRUITMENT = "recruitment"
    PERFORMANCE = "performance"
    COMPLIANCE = "compliance"
    FINANCIAL = "financial"


class Metric(BaseModel):
    key: str
    label: str
    unit: Unit
    value: float | None
    previous_value: float | None = None
    change: float | None = None
    # None when the comparison value is zero or missing: a percentage
    # change from nothing is not a number.
    change_pct: float | None = None
    currency: str | None = None
    # True: up is good; False: up is bad; None: neither (a count of hires).
    higher_is_better: bool | None = None
    text_value: str | None = None
    definition: str
    # The analytics page (and drill-down dataset) holding the source records.
    href: str | None = None
    dataset: str | None = None
    note: str | None = None


class SeriesPoint(BaseModel):
    period: str  # "YYYY-MM"
    value: float | None


class Series(BaseModel):
    key: str
    label: str
    points: list[SeriesPoint]


class Trend(BaseModel):
    key: str
    title: str
    unit: Unit
    currency: str | None = None
    # Stacked only when the series add up to a meaningful total.
    stacked: bool = False
    series: list[Series]
    definition: str
    dataset: str | None = None


class BreakdownRow(BaseModel):
    key: str
    label: str
    value: float | None
    # People (or records) behind the value, so a reader can judge it.
    count: int | None = None
    # The group was too small to show without exposing an individual.
    suppressed: bool = False


class Breakdown(BaseModel):
    key: str
    title: str
    unit: Unit
    currency: str | None = None
    rows: list[BreakdownRow]
    definition: str
    dataset: str | None = None


class Unsupported(BaseModel):
    key: str
    label: str
    reason: str


class PeriodOut(BaseModel):
    date_from: date
    date_to: date
    compare: CompareMode
    compare_from: date | None
    compare_to: date | None
    months: list[str]


class AppliedFilters(BaseModel):
    department_ids: list[uuid.UUID]
    location_ids: list[uuid.UUID]
    employment_types: list[str]
    statuses: list[str]
    payroll_status: str
    country: str


class Meta(BaseModel):
    section: str
    period: PeriodOut
    filters: AppliedFilters
    currency: str
    # Set for a department manager: the departments every figure is limited to.
    department_scope: list[uuid.UUID] | None
    generated_at: datetime
    notes: list[str]
    unsupported: list[Unsupported]


class WorkforceOut(BaseModel):
    meta: Meta
    kpis: list[Metric]
    headcount_trend: Trend
    hires_vs_departures: Trend
    turnover_trend: Trend
    by_department: Breakdown
    by_job_title: Breakdown
    by_status: Breakdown
    by_location: Breakdown
    by_employment_type: Breakdown
    tenure_bands: Breakdown
    age_bands: Breakdown


class PayrollOut(BaseModel):
    meta: Meta
    kpis: list[Metric]
    cost_trend: Trend
    gross_net_trend: Trend
    employer_contribution_trend: Trend
    deduction_trend: Trend
    overtime_trend: Trend
    cost_by_department: Breakdown
    average_gross_by_department: Breakdown
    cost_by_employment_type: Breakdown
    runs_by_status: Breakdown


class AttendanceOut(BaseModel):
    meta: Meta
    kpis: list[Metric]
    rate_trend: Trend
    late_trend: Trend
    hours_trend: Trend
    overtime_hours_trend: Trend
    rate_by_department: Breakdown
    rate_by_location: Breakdown
    rate_by_weekday: Breakdown


class LeaveOut(BaseModel):
    meta: Meta
    kpis: list[Metric]
    by_status: Breakdown
    days_by_type: Breakdown
    monthly_trend: Trend
    utilisation_by_department: Breakdown
    balance_bands: Breakdown


class RecruitmentOut(BaseModel):
    meta: Meta
    kpis: list[Metric]
    applications_trend: Trend
    candidates_by_stage: Breakdown
    vacancies_by_department: Breakdown


class PerformanceOut(BaseModel):
    meta: Meta
    kpis: list[Metric]
    completion_trend: Trend
    reviews_by_status: Breakdown
    rating_distribution: Breakdown
    rating_by_department: Breakdown
    training_by_status: Breakdown


class DeadlineOut(BaseModel):
    id: uuid.UUID
    scheme: str
    category: str
    authority: str
    period_start: date
    period_end: date
    due_date: date
    amount_minor: int
    status: str
    overdue: bool


class ComplianceOut(BaseModel):
    meta: Meta
    country_name: str
    kpis: list[Metric]
    obligations_trend: Trend
    obligations_by_category: Breakdown
    obligations_by_status: Breakdown
    input_vat_trend: Trend
    deadlines: list[DeadlineOut]


class BudgetActualRow(BaseModel):
    budget_id: uuid.UUID
    name: str
    department_name: str | None
    period_start: date
    period_end: date
    budgeted_minor: int
    actual_minor: int
    variance_minor: int


class FinancialOut(BaseModel):
    meta: Meta
    kpis: list[Metric]
    revenue_expense_trend: Trend
    payroll_share_trend: Trend
    cash_movement_trend: Trend
    expenses_by_department: Breakdown
    expenses_by_account: Breakdown
    budget_vs_actual: list[BudgetActualRow]


class OverviewOut(BaseModel):
    meta: Meta
    kpis: list[Metric]
    headcount_trend: Trend | None
    payroll_cost_trend: Trend | None
    headcount_by_department: Breakdown | None
    deadlines: list[DeadlineOut] | None
    # Sections the caller may not see; their KPIs and charts are omitted.
    restricted_sections: list[Section]


class SectionAccess(BaseModel):
    section: Section
    allowed: bool


class AccessOut(BaseModel):
    can_view: bool
    sections: list[SectionAccess]
    can_export: bool
    can_view_individual_pay: bool
    department_scope: list[uuid.UUID] | None


class Option(BaseModel):
    value: str
    label: str


class CountryOption(BaseModel):
    code: str
    name: str
    currency: str
    status: str


class FilterOptionsOut(BaseModel):
    departments: list[Option]
    locations: list[Option]
    employment_types: list[Option]
    statuses: list[Option]
    payroll_statuses: list[Option]
    countries: list[CountryOption]
    default_from: date
    default_to: date
    max_range_months: int


class RecordColumn(BaseModel):
    key: str
    label: str
    kind: str  # text | date | count | money | hours | days | percent


class RecordsPageOut(BaseModel):
    dataset: str
    title: str
    currency: str
    columns: list[RecordColumn]
    rows: list[dict[str, str | int | float | None]]
    page: int
    page_size: int
    total: int
