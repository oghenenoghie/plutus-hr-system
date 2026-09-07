import uuid
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models.disciplinary_case import (
    DisciplinaryCase,
    DisciplinaryCaseAction,
    DisciplinaryCaseCategory,
    DisciplinaryCaseStatus,
)


def register_disciplinary_case(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    category: DisciplinaryCaseCategory,
    description: str,
    incident_date: date,
    reported_by_id: uuid.UUID | None = None,
) -> DisciplinaryCase:
    case = DisciplinaryCase(
        org_id=org_id,
        employee_id=employee_id,
        reported_by_id=reported_by_id,
        category=category,
        description=description,
        incident_date=incident_date,
    )
    db.add(case)
    db.flush()
    return case


def resolve_disciplinary_case(
    db: Session,
    case: DisciplinaryCase,
    *,
    action_taken: DisciplinaryCaseAction,
    resolution_notes: str | None = None,
) -> DisciplinaryCase:
    if case.status in (DisciplinaryCaseStatus.RESOLVED, DisciplinaryCaseStatus.DISMISSED):
        raise ValueError(f"disciplinary case is already {case.status.value}")

    case.action_taken = action_taken
    case.resolution_notes = resolution_notes
    case.status = (
        DisciplinaryCaseStatus.DISMISSED
        if action_taken == DisciplinaryCaseAction.NONE
        else DisciplinaryCaseStatus.RESOLVED
    )
    case.resolution_date = datetime.now(UTC).date()
    db.add(case)
    return case
