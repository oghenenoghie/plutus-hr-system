import uuid
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models.employee_checklist_item import (
    ChecklistItemStatus,
    ChecklistType,
    EmployeeChecklistItem,
)


def add_checklist_item(
    db: Session,
    *,
    org_id: uuid.UUID,
    employee_id: uuid.UUID,
    checklist_type: ChecklistType,
    title: str,
    due_date: date | None = None,
) -> EmployeeChecklistItem:
    item = EmployeeChecklistItem(
        org_id=org_id,
        employee_id=employee_id,
        checklist_type=checklist_type,
        title=title,
        due_date=due_date,
    )
    db.add(item)
    db.flush()
    return item


def complete_checklist_item(
    db: Session, item: EmployeeChecklistItem, *, completed_by: uuid.UUID | None
) -> EmployeeChecklistItem:
    if item.status == ChecklistItemStatus.DONE:
        raise ValueError("checklist item is already done")
    item.status = ChecklistItemStatus.DONE
    item.completed_at = datetime.now(UTC)
    item.completed_by = completed_by
    db.add(item)
    return item
