import uuid

from sqlalchemy.orm import Session

from app.models.branch import Branch


def register_branch(
    db: Session,
    *,
    org_id: uuid.UUID,
    name: str,
    state: str | None = None,
    address: str | None = None,
    manager_id: uuid.UUID | None = None,
) -> Branch:
    branch = Branch(org_id=org_id, name=name, state=state, address=address, manager_id=manager_id)
    db.add(branch)
    db.flush()
    return branch
