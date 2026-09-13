import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models.employee import LifecycleState
from app.models.employee_history_event import EmployeeHistoryEvent, EmployeeHistoryEventType

_COMPENSATION_FIELDS = (
    "basic_minor",
    "housing_minor",
    "transport_minor",
    "other_earnings_minor",
    "pay_frequency",
)


def record_status_change(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    from_state: LifecycleState,
    to_state: LifecycleState,
    effective_date: date,
    recorded_by: uuid.UUID | None,
) -> None:
    if from_state == to_state:
        return
    db.add(
        EmployeeHistoryEvent(
            org_id=org_id,
            employee_id=employee_id,
            event_type=EmployeeHistoryEventType.STATUS_CHANGE,
            effective_date=effective_date,
            detail={"from": from_state.value, "to": to_state.value},
            recorded_by=recorded_by,
        )
    )


def record_compensation_change(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    before: dict[str, object],
    after: dict[str, object],
    effective_date: date,
    recorded_by: uuid.UUID | None,
) -> None:
    """Compares only the fixed set of pay-affecting fields in
    _COMPENSATION_FIELDS — any other key present in before/after (e.g. an
    unrelated field updated in the same request) is ignored. Records
    nothing if none of those fields actually changed."""
    changed_from = {}
    changed_to = {}
    for field in _COMPENSATION_FIELDS:
        if field not in after:
            continue
        old_value = before.get(field)
        new_value = after[field]
        if old_value == new_value:
            continue
        changed_from[field] = old_value.value if hasattr(old_value, "value") else old_value
        changed_to[field] = new_value.value if hasattr(new_value, "value") else new_value

    if not changed_to:
        return
    db.add(
        EmployeeHistoryEvent(
            org_id=org_id,
            employee_id=employee_id,
            event_type=EmployeeHistoryEventType.COMPENSATION_CHANGE,
            effective_date=effective_date,
            detail={"from": changed_from, "to": changed_to},
            recorded_by=recorded_by,
        )
    )
