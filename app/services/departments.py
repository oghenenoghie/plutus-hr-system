import uuid

from sqlalchemy.orm import Session

from app.models.department import Department


def register_department(
    db: Session,
    *,
    org_id: uuid.UUID,
    name: str,
    manager_id: uuid.UUID | None = None,
) -> Department:
    department = Department(org_id=org_id, name=name, manager_id=manager_id)
    db.add(department)
    db.flush()
    return department
