import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, aliased

from app.core.deps import get_current_claims, get_tenant_db
from app.core.security import TokenClaims
from app.models.account import Account
from app.models.membership import Membership
from app.models.task import Task, TaskStatus
from app.schemas.tasks import TaskCreate, TaskOut, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])

_CreatedBy = aliased(Account)
_AssignedTo = aliased(Account)


def _serialize(task: Task, *, assigned_to_email: str, created_by_email: str) -> TaskOut:
    return TaskOut(
        id=task.id,
        title=task.title,
        description=task.description,
        status=task.status,
        priority=task.priority,
        due_date=task.due_date,
        assigned_to_account_id=task.assigned_to_account_id,
        assigned_to_email=assigned_to_email,
        created_by_account_id=task.created_by_account_id,
        created_by_email=created_by_email,
        related_employee_id=task.related_employee_id,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
    )


def _select_with_emails() -> Select[tuple[Task, str, str]]:
    return (
        select(Task, _AssignedTo.email, _CreatedBy.email)
        .join(_AssignedTo, _AssignedTo.id == Task.assigned_to_account_id)
        .join(_CreatedBy, _CreatedBy.id == Task.created_by_account_id)
    )


def _get_task_or_404(db: Session, org_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = db.scalar(select(Task).where(Task.id == task_id, Task.org_id == org_id))
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    return task


def _require_membership(db: Session, org_id: uuid.UUID, account_id: uuid.UUID) -> None:
    """A task can only be assigned to a real member of this org — Membership
    carries no RLS of its own (pre-tenant-session login-discovery data), so
    this filters by org_id explicitly, same as the /memberships router."""
    exists = db.scalar(
        select(Membership.id).where(
            Membership.account_id == account_id, Membership.org_id == org_id
        )
    )
    if exists is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="assigned_to_account_id is not a member of this organisation",
        )


@router.get("", response_model=list[TaskOut])
def list_tasks(
    scope: str = Query("mine", pattern="^(mine|all)$"),
    status_filter: TaskStatus | None = Query(None, alias="status"),
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> list[TaskOut]:
    """'mine' (default) is every task assigned to or created by the caller
    — available to any role, including Employee, since tasks are
    account-scoped rather than gated by employee visibility rules. 'all'
    additionally requires no HTTP-level role check: any authenticated
    account can ask for the org's full task list (this is a lightweight
    coordination tool, not a compliance-sensitive record), which also
    means a Manager can see what their assignees are on with no per-role
    special-casing to maintain here."""
    stmt = _select_with_emails().where(Task.org_id == claims.org_id)
    if scope == "mine":
        stmt = stmt.where(
            (Task.assigned_to_account_id == claims.account_id)
            | (Task.created_by_account_id == claims.account_id)
        )
    if status_filter is not None:
        stmt = stmt.where(Task.status == status_filter)
    rows = db.execute(
        stmt.order_by(Task.due_date.is_(None), Task.due_date, Task.created_at.desc())
    ).all()
    return [
        _serialize(task, assigned_to_email=assigned_email, created_by_email=created_email)
        for task, assigned_email, created_email in rows
    ]


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(
    body: TaskCreate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> TaskOut:
    assigned_to_account_id = body.assigned_to_account_id or claims.account_id
    if assigned_to_account_id != claims.account_id:
        _require_membership(db, claims.org_id, assigned_to_account_id)
    task = Task(
        org_id=claims.org_id,
        title=body.title,
        description=body.description,
        assigned_to_account_id=assigned_to_account_id,
        created_by_account_id=claims.account_id,
        related_employee_id=body.related_employee_id,
        priority=body.priority,
        due_date=body.due_date,
    )
    db.add(task)
    db.flush()
    row = db.execute(_select_with_emails().where(Task.id == task.id)).one()
    task, assigned_email, created_email = row
    return _serialize(task, assigned_to_email=assigned_email, created_by_email=created_email)


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: uuid.UUID,
    body: TaskUpdate,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> TaskOut:
    task = _get_task_or_404(db, claims.org_id, task_id)
    if claims.account_id not in (task.assigned_to_account_id, task.created_by_account_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only the task's assignee or creator can update it",
        )
    changes = body.model_dump(exclude_unset=True)
    if "assigned_to_account_id" in changes and changes["assigned_to_account_id"] is not None:
        _require_membership(db, claims.org_id, changes["assigned_to_account_id"])
    for field, value in changes.items():
        setattr(task, field, value)
    if "status" in changes:
        task.completed_at = datetime.now(UTC) if task.status == TaskStatus.DONE else None
    db.add(task)
    db.flush()
    row = db.execute(_select_with_emails().where(Task.id == task.id)).one()
    task, assigned_email, created_email = row
    return _serialize(task, assigned_to_email=assigned_email, created_by_email=created_email)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: uuid.UUID,
    db: Session = Depends(get_tenant_db),
    claims: TokenClaims = Depends(get_current_claims),
) -> None:
    task = _get_task_or_404(db, claims.org_id, task_id)
    if claims.account_id != task.created_by_account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only the task's creator can delete it",
        )
    db.delete(task)
