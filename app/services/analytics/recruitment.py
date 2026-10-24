"""Recruitment analytics. A candidate records only their current status and
applied date: no stage history, hire date, offer date or source. So the
stage figures are a snapshot of where candidates are today, and time to
hire, offer acceptance, source performance and funnel conversion are
reported as unsupported rather than estimated. Definitions:
docs/analytics-metrics.md §5.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.candidate import Candidate, CandidateStatus
from app.models.job_posting import JobPosting, JobPostingStatus
from app.schemas.analytics import Metric, RecruitmentOut, Unit, Unsupported
from app.services.analytics.access import AnalyticsAccess
from app.services.analytics.common import (
    NO_DEPARTMENT,
    breakdown,
    build_meta,
    department_names,
    metric,
    row,
    series,
    trend,
)
from app.services.analytics.filters import AnalyticsFilters, month_keys

HREF = "/analytics/recruitment"

_STAGE_LABELS = {
    CandidateStatus.APPLIED: "Applied",
    CandidateStatus.INTERVIEWING: "Interviewing",
    CandidateStatus.OFFERED: "Offered",
    CandidateStatus.HIRED: "Hired",
    CandidateStatus.REJECTED: "Rejected",
}

UNSUPPORTED = [
    Unsupported(
        key="time_to_hire",
        label="Time to hire",
        reason="Candidates have no hire date, only their current status.",
    ),
    Unsupported(
        key="offer_acceptance",
        label="Offer acceptance rate",
        reason="Offer and decline events aren't recorded, so declined offers can't be told "
        "apart from candidates rejected earlier.",
    ),
    Unsupported(
        key="source",
        label="Hiring source performance",
        reason="Candidates have no source field.",
    ),
    Unsupported(
        key="funnel",
        label="Funnel conversion",
        reason="Stage history isn't kept: a rejected candidate's furthest stage is unknown.",
    ),
]


def _department_condition(filters: AnalyticsFilters) -> list[Any]:
    return [JobPosting.department_id.in_(filters.department_ids)] if filters.department_ids else []


def _candidates(filters: AnalyticsFilters, org_id: uuid.UUID, *columns: Any) -> Any:
    return (
        select(*columns)
        .select_from(Candidate)
        .join(JobPosting, Candidate.job_posting_id == JobPosting.id)
        .where(
            Candidate.org_id == org_id,
            Candidate.applied_date.between(filters.date_from, filters.date_to),
            *_department_condition(filters),
        )
    )


def _period(db: Session, org_id: uuid.UUID, filters: AnalyticsFilters) -> dict[str, int]:
    applications, hired = db.execute(
        _candidates(
            filters,
            org_id,
            func.count(),
            func.count().filter(Candidate.status == CandidateStatus.HIRED),
        )
    ).one()
    opened = db.scalar(
        select(func.count())
        .select_from(JobPosting)
        .where(
            JobPosting.org_id == org_id,
            JobPosting.opened_date.between(filters.date_from, filters.date_to),
            *_department_condition(filters),
        )
    )
    return {"applications": applications, "hired": hired, "opened": opened or 0}


def recruitment(db: Session, access: AnalyticsAccess, filters: AnalyticsFilters) -> RecruitmentOut:
    org_id = access.org_id
    months = month_keys(filters.date_from, filters.date_to)
    now = _period(db, org_id, filters)
    previous_filters = filters.comparison()
    before = _period(db, org_id, previous_filters) if previous_filters else {}
    compare = previous_filters is not None
    open_now = (
        db.scalar(
            select(func.count())
            .select_from(JobPosting)
            .where(
                JobPosting.org_id == org_id,
                JobPosting.status == JobPostingStatus.OPEN,
                *_department_condition(filters),
            )
        )
        or 0
    )
    in_pipeline = db.scalar(
        select(func.count())
        .select_from(Candidate)
        .join(JobPosting, Candidate.job_posting_id == JobPosting.id)
        .where(
            Candidate.org_id == org_id,
            Candidate.status.in_(
                (CandidateStatus.APPLIED, CandidateStatus.INTERVIEWING, CandidateStatus.OFFERED)
            ),
            *_department_condition(filters),
        )
    )

    kpis: list[Metric] = [
        metric(
            key="open_vacancies",
            label="Open vacancies",
            unit=Unit.COUNT,
            value=open_now,
            compare=False,
            definition="Job postings open today.",
            href=HREF,
            dataset="candidates",
        ),
        metric(
            key="vacancies_opened",
            label="Vacancies opened",
            unit=Unit.COUNT,
            value=now["opened"],
            previous=before.get("opened"),
            compare=compare,
            definition="Job postings whose opened date falls in the period.",
            href=HREF,
        ),
        metric(
            key="applications",
            label="Applications received",
            unit=Unit.COUNT,
            value=now["applications"],
            previous=before.get("applications"),
            compare=compare,
            definition="Candidates whose applied date falls in the period.",
            href=HREF,
            dataset="candidates",
        ),
        metric(
            key="hired",
            label="Applicants now hired",
            unit=Unit.COUNT,
            value=now["hired"],
            previous=before.get("hired"),
            compare=compare,
            definition="Of the candidates who applied in the period, those whose status is "
            "Hired today. There is no hire date, so this is not hires made in the period.",
            href=HREF,
            dataset="candidates",
        ),
        metric(
            key="in_pipeline",
            label="Candidates in the pipeline",
            unit=Unit.COUNT,
            value=in_pipeline or 0,
            compare=False,
            definition="Candidates who are Applied, Interviewing or Offered today.",
            href=HREF,
            dataset="candidates",
        ),
    ]

    month = func.to_char(Candidate.applied_date, "YYYY-MM")
    applications = {
        key: count
        for key, count in db.execute(
            _candidates(filters, org_id, month, func.count()).group_by(month)
        ).tuples()
    }
    stages = {
        status: count
        for status, count in db.execute(
            _candidates(filters, org_id, Candidate.status, func.count()).group_by(Candidate.status)
        ).tuples()
    }
    names = department_names(db, org_id)
    vacancies = [
        row(
            dept or "none",
            names.get(dept, NO_DEPARTMENT) if dept else NO_DEPARTMENT,
            count,
            count=count,
        )
        for dept, count in db.execute(
            select(JobPosting.department_id, func.count())
            .where(
                JobPosting.org_id == org_id,
                JobPosting.status == JobPostingStatus.OPEN,
                *_department_condition(filters),
            )
            .group_by(JobPosting.department_id)
        ).tuples()
    ]

    return RecruitmentOut(
        meta=build_meta(
            "recruitment",
            filters,
            access,
            notes=[
                "Only the department filter applies: candidates are not employees.",
                "Stages are where candidates are today, not how they moved.",
            ],
            unsupported=UNSUPPORTED,
        ),
        kpis=kpis,
        applications_trend=trend(
            key="applications",
            title="Applications received",
            unit=Unit.COUNT,
            series_list=[series("applications", "Applications", months, applications)],
            definition="Candidates by the month of their applied date.",
            dataset="candidates",
        ),
        candidates_by_stage=breakdown(
            key="candidates_by_stage",
            title="Candidates by current stage",
            unit=Unit.COUNT,
            rows=[
                row(status.value, label, stages.get(status, 0), count=stages.get(status, 0))
                for status, label in _STAGE_LABELS.items()
            ],
            definition="Candidates who applied in the period, by their status today.",
            dataset="candidates",
            sort=False,
        ),
        vacancies_by_department=breakdown(
            key="vacancies_by_department",
            title="Open vacancies by department",
            unit=Unit.COUNT,
            rows=vacancies,
            definition="Job postings open today, by department.",
        ),
    )
